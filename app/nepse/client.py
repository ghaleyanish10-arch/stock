"""Adapter around the `nepse-data-api` library (current nepalstock.com.np platform).

This is the ONLY module in the application that imports `nepse_data_api`.
Everything else talks to `NepseService` (see `service.py`), so the data
source can be replaced later without touching the rest of the codebase.

`nepse-data-api` is synchronous (requests/aiohttp) and handles NEPSE's
WASM token authentication internally. We run its calls in a worker thread
via `asyncio.to_thread` so the async service is never blocked, and wrap
every failure mode into application-level errors.

History note: the previous adapter used the `nepse-api` package (July 2021),
whose host `newweb.nepalstock.com` no longer exists (NXDOMAIN). NEPSE's
current platform is `www.nepalstock.com.np`.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import threading
import time
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional

import requests
import urllib3
from nepse_data_api import Nepse

from app.config import settings
from app.nepse.exceptions import (
    NepseAuthError,
    NepseDateOutOfRangeError,
    NepseInvalidResponseError,
    NepseRateLimitedError,
    NepseServiceError,
    NepseTimeoutError,
    NepseUnavailableError,
    SymbolNotFoundError,
)

logger = logging.getLogger(__name__)

# NEPSE's scrambled token proves short-lived; the library authenticates once
# and never refreshes, so a long-running process goes stale. Re-authenticate
# proactively (well under NEPSE's apparent token lifetime) and retry once on
# auth rejections.
AUTH_REFRESH_SECONDS = 240

# Retry with linear backoff on HTTP 429/5xx before giving up.
HTTP_RETRIES = 2
BACKOFF_BASE_SECONDS = 1.0

# Minimum gap between forced re-authentications (single-flight guard:
# concurrent auth rejections share one fresh token instead of each
# calling NEPSE's authenticate endpoint).
REAUTH_MIN_GAP_SECONDS = 5.0

# Browser-like headers. NEPSE's edge has been seen to fingerprint clients;
# the library's bare requests default ("python-requests/x.y") is fragile.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nepalstock.com.np/",
    "Origin": "https://www.nepalstock.com.np",
}

# HTML bodies that mean "your token was rejected" regardless of status code.
_AUTH_PAGE_MARKERS = ("unauthorized access", "access denied")


def _looks_like_auth_page(exc: Exception) -> bool:
    """True when an upstream response body is one of NEPSE's auth-rejection
    HTML pages (the library hides the status code, so sniff the text)."""
    text = str(exc).lower()
    return any(marker in text for marker in _AUTH_PAGE_MARKERS)


def _normalize_exception(exc: Exception) -> NepseServiceError:
    """Map library/network exceptions to application errors."""
    if isinstance(exc, NepseServiceError):
        return exc
    if _looks_like_auth_page(exc) or isinstance(exc, ValueError):
        # ValueError covers json.JSONDecodeError: the library maps rejected
        # tokens (HTTP 401 + HTML body) to "Expecting value ...".
        return NepseAuthError()
    text = str(exc).lower()
    if "429" in text or "too many requests" in text:
        return NepseRateLimitedError()
    if isinstance(exc, requests.exceptions.HTTPError):
        status = getattr(exc.response, "status_code", None)
        if status == 429:
            return NepseRateLimitedError()
        if status in (401, 403):
            return NepseAuthError()
        return NepseUnavailableError()
    if isinstance(exc, (socket.timeout, TimeoutError)) or "timed out" in text:
        return NepseTimeoutError()
    if isinstance(exc, socket.gaierror) or "getaddrinfo" in text or "name or service" in text:
        return NepseUnavailableError()
    if "connection" in text or "max retries" in text or "unreachable" in text:
        return NepseUnavailableError()
    if "401" in text or "403" in text or "unauthorized" in text or "forbidden" in text:
        # NEPSE rejecting our token even after a refresh attempt.
        return NepseAuthError()
    if "404" in text or "no data" in text:
        return SymbolNotFoundError()
    if "500" in text or "502" in text or "503" in text:
        # NEPSE upstream endpoint broken (e.g. graphdata 500s as of 2026-09).
        return NepseInvalidResponseError()
    return NepseServiceError()


class NepseClientAdapter:
    """Owns the `nepse-data-api` client and normalizes its failure modes."""

    def __init__(self, timeout: Optional[int] = None) -> None:
        self._timeout = timeout if timeout is not None else settings.timeout
        self._client: Optional[Nepse] = None
        self._last_auth: float = 0.0
        # Auth-token state for the single-flight guard in `call`:
        #   _auth_proven      - a request has succeeded since _last_auth, so the
        #                       token is known-good and safe to share;
        #   _auth_retry_failed- a forced re-auth did not clear the rejection.
        self._auth_proven = False
        self._auth_retry_failed = False
        # The library's requests.Session is not thread-safe; serialize calls.
        self._lib_lock = threading.Lock()
        # Outbound pacing. NEPSE answers bursts by closing the connection
        # (observed 2026-09 while enumerating securities), so every upstream
        # call waits its turn behind this gate.
        self._min_interval = settings.outbound_min_interval_ms / 1000.0
        self._last_request: float = 0.0

    async def start(self) -> None:
        """Create the library client and authenticate once (idempotent)."""
        if self._client is not None:
            return
        self._client = Nepse(enable_cache=False)
        self._harden_session()
        self._last_auth = time.time()
        logger.info("NEPSE client initialized (timeout=%ss)", self._timeout)

    def _harden_session(self) -> None:
        """Make the library's requests.Session less fragile.

        - Browser-like headers (the library sends a bare python-requests UA).
        - A per-request timeout (the library omits `timeout` on most calls,
        which can hang a worker thread indefinitely).
        - Silence urllib3's InsecureRequestWarning (the library intentionally
        disables TLS verification for this public-data session).
        """
        session = self.raw.session
        session.headers.update(BROWSER_HEADERS)

        original_request = session.request

        def request_with_timeout(method: str, url: str, **kwargs: Any) -> Any:
            kwargs.setdefault("timeout", self._timeout)
            return original_request(method, url, **kwargs)

        session.request = request_with_timeout  # type: ignore[method-assign]
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    async def close(self) -> None:
        """Release the client (idempotent; the library holds no persistent
        session that requires closing, this just drops the reference)."""
        self._client = None
        logger.info("NEPSE client closed")

    def _refresh_auth_if_stale(self) -> None:
        if time.time() - self._last_auth >= AUTH_REFRESH_SECONDS:
            logger.info("NEPSE token stale; re-authenticating")
            self.raw.authenticate()
            self._last_auth = time.time()
            # A new token is unproven until a request succeeds with it.
            self._auth_proven = False
            self._auth_retry_failed = False

    @staticmethod
    def _is_auth_error(exc: BaseException) -> bool:
        """True when this failure means "NEPSE rejected our token".

        Two shapes occur, and both must be recognised or the re-auth retry
        never runs:

        * a genuine ``requests.HTTPError`` with status 401/403 - this is what
          the backfill actually hit (the library re-raises the status error
          from `raise_for_status` on some endpoints);
        * a ``json.JSONDecodeError``/``ValueError`` ("Expecting value ...")
          plus NEPSE's HTML rejection pages, which is how the library surfaces
          a rejected token on the endpoints that parse the body themselves.

        An earlier version only handled the second shape, so every 401 fell
        straight through to `raise mapped` and the re-authentication path was
        unreachable.
        """
        if isinstance(exc, requests.exceptions.HTTPError):
            status = getattr(exc.response, "status_code", None)
            if status in (401, 403):
                return True
        if isinstance(exc, ValueError):  # json.JSONDecodeError subclasses ValueError
            return True
        return _looks_like_auth_page(exc)

    def _pace(self) -> None:
        """Sleep so consecutive upstream calls are at least `min_interval` apart.

        Must be called while holding `_lib_lock`, which is what makes the
        simple "time since last call" check safe.
        """
        if self._min_interval <= 0:
            return
        elapsed = time.time() - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request = time.time()

    async def call(self, operation: str, fn: Callable[[], Any]) -> Any:
        """Run one library call in a worker thread, translating failures.

        `operation` is only used for logging, e.g. "get_market_status".
        Resilience layers, in order:
        1. proactive token refresh when older than AUTH_REFRESH_SECONDS;
        2. outbound pacing (NEPSE drops connections on bursts);
        3. retry with backoff on HTTP 429 / 5xx;
        4. one forced re-authentication + retry when NEPSE rejects the token.
        Everything is then mapped to a specific NepseServiceError subclass.
        """
        if self._client is None:
            await self.start()

        logger.info("NEPSE request started: %s", operation)

        def _attempt() -> Any:
            last_exc: Optional[Exception] = None
            for attempt in range(HTTP_RETRIES + 1):
                try:
                    with self._lib_lock:
                        self._refresh_auth_if_stale()
                        self._pace()
                        return fn()
                except requests.exceptions.HTTPError as exc:
                    status = getattr(exc.response, "status_code", None)
                    retryable = status == 429 or (status is not None and status >= 500)
                    if retryable and attempt < HTTP_RETRIES:
                        delay = BACKOFF_BASE_SECONDS * (attempt + 1)
                        logger.warning(
                            "NEPSE upstream HTTP %s on %s; retrying in %.1fs "
                            "(attempt %d/%d)",
                            status, operation, delay, attempt + 1, HTTP_RETRIES,
                        )
                        last_exc = exc
                        time.sleep(delay)
                        continue
                    raise
                except ValueError:
                    # Auth flaps surface as JSONDecodeError (a ValueError);
                    # hand them to the re-auth path below without retrying here.
                    raise
            raise last_exc  # pragma: no cover - loop always returns or raises

        result: Any = None
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(_attempt), timeout=self._timeout
            )
        except asyncio.TimeoutError as exc:
            logger.warning("NEPSE request timed out: %s", operation)
            raise NepseTimeoutError() from exc
        except Exception as exc:
            if not self._is_auth_error(exc):
                mapped = _normalize_exception(exc)
                if mapped.code in (NepseUnavailableError.code, NepseTimeoutError.code):
                    logger.warning("NEPSE request failed (network): %s: %s", operation, exc)
                else:
                    logger.info("NEPSE request failed: %s: %s", operation, exc)
                raise mapped from exc
            # Token rejected by NEPSE: force re-auth and retry once.
            logger.info("NEPSE auth rejected; re-authenticating and retrying: %s", operation)

            def _reattempt() -> Any:
                with self._lib_lock:
                    # Single-flight: when a *concurrent* caller just
                    # re-authenticated and its request then succeeded, that
                    # token is proven good, so reuse it rather than hammering
                    # NEPSE's auth endpoint with N simultaneous requests
                    # during a flap (which makes the throttling worse).
                    #
                    # A recent token is not automatically trustworthy. If no
                    # request has succeeded since it was acquired, or the last
                    # re-auth failed to clear the rejection, it is unproven and
                    # must be refreshed. Without that, a sequential caller -
                    # the archive backfill, which retries every 0.9s - would
                    # reuse the same dead token on every date: 268
                    # consecutive NEPSE_AUTH_FAILED dates in one run.
                    proven = self._auth_proven and not self._auth_retry_failed
                    recent = time.time() - self._last_auth
                    if recent >= REAUTH_MIN_GAP_SECONDS or not proven:
                        self.raw.authenticate()
                        self._last_auth = time.time()
                        self._auth_proven = False
                        self._auth_retry_failed = False
                    self._pace()
                    try:
                        out = fn()
                    except Exception:
                        # A re-auth that did not fix it must not be trusted.
                        self._auth_retry_failed = True
                        raise
                    self._auth_proven = True
                    self._auth_retry_failed = False
                    return out

            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(_reattempt), timeout=self._timeout
                )
            except asyncio.TimeoutError as exc2:
                logger.warning("NEPSE request timed out (after re-auth): %s", operation)
                raise NepseTimeoutError() from exc2
            except Exception as exc2:
                mapped = _normalize_exception(exc2)
                logger.warning("NEPSE request failed (after re-auth): %s: %s", operation, exc2)
                raise mapped from exc2

        logger.info("NEPSE request succeeded: %s", operation)
        # Any success proves the current token, which is what lets a
        # concurrent caller share it instead of re-authenticating.
        self._auth_proven = True
        return result

    # ------------------------------------------------------------------
    # Typed accessors for library methods the service uses.
    # Only methods verified against nepse-data-api 1.0.0.4 are exposed.
    # ------------------------------------------------------------------

    @property
    def raw(self) -> Nepse:
        if self._client is None:
            raise RuntimeError("NEPSE client not started")
        return self._client

    def _get_json_with_diagnostics(self, url: str) -> Any:
        """GET JSON via the library session, with full failure forensics.

        Bypasses the library's parsing so we can log (on any failure): HTTP
        status, Content-Type, and the first 500 characters of the raw body.
        The original error is never swallowed - it is chained via `raise
        ... from exc`.

        This is the one and only accessor for the nepse-index / sub-indices
        endpoints; the former library-passthrough variants were removed so
        every index request keeps its diagnostics.
        """
        response = self.raw.session.get(url, headers=self.raw._get_auth_headers())
        content_type = response.headers.get("content-type", "")
        if response.status_code != 200:
            logger.warning(
                "NEPSE upstream %s -> HTTP %s (content-type: %s); body[:500]: %r",
                url,
                response.status_code,
                content_type,
                response.text[:500],
            )
            if response.status_code == 429:
                raise NepseRateLimitedError()
            if response.status_code in (401, 403) or _looks_like_auth_page(
                Exception(response.text)
            ):
                raise NepseAuthError()
            raise NepseInvalidResponseError()
        if "json" not in content_type.lower():
            logger.warning(
                "NEPSE upstream %s -> HTTP 200 but content-type %r; "
                "body[:500]: %r",
                url,
                content_type,
                response.text[:500],
            )
        try:
            return response.json()
        except ValueError as exc:
            logger.warning(
                "NEPSE upstream %s returned non-JSON (content-type: %s); "
                "body[:500]: %r",
                url,
                content_type,
                response.text[:500],
            )
            if _looks_like_auth_page(exc):
                raise NepseAuthError() from exc
            raise NepseInvalidResponseError() from exc

    def get_nepse_index(self) -> list:
        """NEPSE main index via the diagnostic raw fetch (see above)."""
        return self._get_json_with_diagnostics(
            "https://www.nepalstock.com.np/api/nots/nepse-index"
        )

    def get_sub_indices(self) -> list:
        """Sector sub-indices via the diagnostic raw fetch (see above)."""
        return self._get_json_with_diagnostics(
            "https://www.nepalstock.com.np/api/nots"
        )

    def get_market_status(self) -> dict:
        """Blocking; run via self.call()."""
        return self.raw.get_market_status(use_cache=False)

    def get_market_summary(self) -> list:
        return self.raw.get_market_summary(use_cache=False)

    def get_stocks(self) -> list:
        trades = self.raw.get_stocks()
        if trades:
            return trades
        # NEPSE's live-market list is empty before the trading session opens
        # (verified 2026-09-28 ~10:30 NPT, before the 11:00 open) even though
        # the price/volume feed still lists every security with the last
        # session's prices. Fall back to it so callers get data instead of
        # an empty list pre-open.
        fallback = self.raw.get_price_volume(use_cache=False)
        if fallback:
            logger.info(
                "get_stocks() returned 0 rows; "
                "using get_price_volume() fallback (%d rows)",
                len(fallback),
            )
        return fallback

    def get_stock_info(self, symbol: str) -> Any:
        """Filter the live market list by symbol (the sync Nepse class has
        no per-symbol endpoint; this is what its async variant does).

        Uses the adapter's get_stocks() (with its pre-open fallback) rather
        than the raw library list, so symbol lookups work pre-open too.
        Matches both `symbol` and the legacy `securitySymbol` key spelling
        (the upstream live-market rows have been seen using either)."""
        wanted = symbol.upper()

        def _match(trade: Any) -> bool:
            if not isinstance(trade, dict):
                return False
            key = trade.get("symbol") or trade.get("securitySymbol") or ""
            return str(key).strip().upper() == wanted

        for trade in self.get_stocks():
            if _match(trade):
                return trade
        return None

    def find_in_price_volume(self, symbol: str) -> Any:
        """Second-pass lookup in the price/volume list.

        The service calls this (through the retry-capable call()) when the
        live-market list has no matching row: pre-open it only carries a
        partial auction snapshot, and its auth flaps swallow errors into
        empty lists."""
        wanted = symbol.upper()
        for trade in self.raw.get_price_volume(use_cache=False):
            if isinstance(trade, dict):
                key = trade.get("symbol") or trade.get("securitySymbol") or ""
                if str(key).strip().upper() == wanted:
                    return trade
        return None

    def get_price_volume(self) -> list:
        return self.raw.get_price_volume(use_cache=False)

    def get_security_details(self, security_id: int) -> dict:
        return self.raw.get_security_details(security_id, use_cache=False)

    def get_security_list(self) -> list:
        return self.raw.get_security_list(use_cache=False)

    def get_marcapbydate(self, date: Optional[str] = None) -> list:
        return self.raw.get_marcapbydate(date=date, use_cache=False)

    def get_index_history(
        self,
        index: Any,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list:
        return self.raw.get_index_history(
            index, start_date=start_date, end_date=end_date, use_cache=False
        )

    def get_historical_chart(
        self, security_id: int, start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list:
        return self.raw.get_historical_chart(
            security_id, start_date=start_date, end_date=end_date, use_cache=False
        )

    def get_top_gainers(self, limit: Optional[int] = None) -> list:
        return self.raw.get_top_gainers(limit=limit, use_cache=False)

    def get_top_losers(self, limit: Optional[int] = None) -> list:
        return self.raw.get_top_losers(limit=limit, use_cache=False)

    # ------------------------------------------------------------------
    # Endpoints found in NEPSE's own frontend bundle (main.*.js) that the
    # `nepse-data-api` library never calls. Discovered 2026-09-28 by
    # searching the Angular bundle served from nepalstock.com; see
    # scripts/research_nepse_site.py and docs/data-sources.md.
    #
    # Each was verified with a live request before being added here, and each
    # notes whether it actually works, so nobody re-adds a dead endpoint.
    # ------------------------------------------------------------------

    _API = "https://www.nepalstock.com.np/api/nots"

    def get_json(self, path: str) -> Any:
        """GET an arbitrary `nots/...` path through the diagnostic fetch.

        Uses the library's authenticated session, so WASM token handling stays
        inside the adapter. Returns the decoded JSON body.
        """
        return self._get_json_with_diagnostics(f"{self._API}/{path.lstrip('/')}")

    def get_brokers(self, size: int = 500) -> list:
        """Official broker/member registry.

        VERIFIED 2026-09-28: 200, a paged envelope whose `content` holds 92
        members. Fields: `memberCode` (an int), `memberName`,
        `membershipTypeMaster.membershipType`, `activeStatus` ("A"),
        `provinceList` / `districtList` (possibly several),
        `authorizedContactPerson` (usually null) and
        `authorizedContactPersonNumber`.
        """
        payload = self.get_json(f"member?&size={int(size)}")
        if isinstance(payload, dict):
            return payload.get("content") or []
        return payload if isinstance(payload, list) else []

    def get_sectors(self) -> list:
        """The sector master. VERIFIED 2026-09-28: 200, 12 sectors.

        Use this, not `nots/sectorwise`: `sectorwise` is a market aggregate
        whose rows come back with `businessDate: "1970-01-01"` and all-zero
        turnover, so it carries no usable sector metadata.
        """
        payload = self.get_json("sector")
        if isinstance(payload, dict):
            return payload.get("sectors") or []
        return payload if isinstance(payload, list) else []

    def get_security_master(self) -> list:
        """Security master: symbol, numeric id, name, active flag.

        VERIFIED 2026-09-28: 568 rows from `nots/security?nonDelisted=true`.
        This is the only bulk source that actually carries `symbol`.

        NOTE: `nots/securities` also exists and returns 441 rows, but every row
        has `securitySymbol: null`, so it cannot be used as a master. Rich
        per-security metadata (sector, ISIN, tick size, instrument type) is
        only available per symbol via `nots/security/{id}` - see
        `get_security_details`.
        """
        return self.get_security_list()

    def get_security_detail_enriched(self, security_id: int) -> dict:
        """Full per-security detail. VERIFIED 2026-09-28 for NABIL (131).

        Returns `security` (with `instrumentType`, `companyId.sectorMaster`,
        `isin`, `faceValue`, `tickSize`, `creditRating`, `listingDate`) plus
        `stockListedShares`, `paidUpCapital`, `publicShares`/`publicPercentage`
        and `promoterShares`/`promoterPercentage`.

        `stockListedShares` is what the archive needs to derive market cap,
        because the live feed's own `marketCapitalization` is null and the
        historical one is denominated in millions.
        """
        return self.get_security_details(security_id)

    def get_sectorwise(self) -> list:
        """Per-sector market aggregate. VERIFIED: 200, 16 rows.

        Carries `sectorName` plus turnover/transactions, but returns
        `businessDate: 1970-01-01` and zeroed aggregates, so it is kept for
        completeness and is NOT used to build the sector master.
        """
        return self.get_json("sectorwise")

    def get_market_summary_history(self) -> list:
        """Whole-market history (turnover, shares, transactions).
        VERIFIED: 200, 228 rows, ~one year, date params ignored."""
        return self.get_json("market-summary-history")

    def get_securities(self) -> list:
        """Metadata-only security list. VERIFIED: 200, 441 rows.

        KEPT FOR REFERENCE ONLY: every row has `securitySymbol: null`
        (verified 2026-09-28), so it cannot be used as a security master. Use
        `get_security_master()` instead. Listed here so the dead end is
        documented rather than rediscovered.
        """
        return self.get_json("securities")


    def get_margin_list(self) -> list:
        """Margin-trading list. VERIFIED: 200, 122 records."""
        return self.get_json("company/margin-list")

    def get_company_news(self, security_id: int) -> list:
        """Company news/announcements. VERIFIED 2026-09-28 for NABIL (131):
        200, 39 items. Rows wrap a `companyNews` object carrying `newsHeadline`,
        `newsBody` (may be HTML), `newsType` ("Annual General Meeting",
        "Dividend Declaration", "Others", ...), `newsSource` and `newsDate`,
        plus the nested `security` object.
        """
        return self.get_json(f"application/company-news/{int(security_id)}")

    def get_market_depth(self, security_id: int) -> Any:
        """Live order book. VERIFIED 2026-09-28 (NABIL, 131): HTTP 200 with an
        EMPTY body outside the trading session (content-type ''). The endpoint
        exists - NEPSE's own frontend calls it - but only serves rows while the
        market is open. Callers must treat an empty payload as 'no live order
        book right now' (status upstream_unavailable/not_published by session),
        never as a structural gap and never as a zero.

        Returns None when the endpoint returns HTTP 200 with an empty body,
        otherwise returns the parsed JSON payload.
        """
        url = f"{self._API}/nepse-data/marketdepth/{int(security_id)}"
        response = self.raw.session.get(url, headers=self.raw._get_auth_headers())
        if response.status_code != 200:
            logger.warning(
                "NEPSE upstream %s -> HTTP %s; body[:500]: %r",
                url,
                response.status_code,
                response.text[:500],
            )
            if response.status_code == 429:
                raise NepseRateLimitedError()
            if response.status_code in (401, 403) or _looks_like_auth_page(
                Exception(response.text)
            ):
                raise NepseAuthError()
            raise NepseInvalidResponseError()
        # Empty body (e.g. outside trading hours) -> return None, not an error
        if not response.text or not response.text.strip():
            logger.info("Market depth endpoint returned empty body for security %s", security_id)
            return None
        try:
            return response.json()
        except ValueError as exc:
            logger.warning(
                "NEPSE market depth returned non-JSON for security %s; body[:500]: %r",
                security_id,
                response.text[:500],
            )
            if _looks_like_auth_page(exc):
                raise NepseAuthError() from exc
            raise NepseInvalidResponseError() from exc

    def get_news_and_alerts(self) -> list:
        """Market-wide news feed. VERIFIED 2026-09-28: 200, 1733 items from
        `nots/news/media/news-and-alerts`. Rows carry the same `companyNews`
        shape as per-company news, so both feed one renderer.
        """
        return self.get_json("news/media/news-and-alerts")

    def get_security_profile(self, security_id: int) -> dict:
        """Company profile text. VERIFIED: 200 for known ids."""
        return self.get_json(f"security/profile/{int(security_id)}")

    def get_board_of_directors(self, security_id: int) -> dict:
        """Board of directors. VERIFIED: 200 for known ids."""
        return self.get_json(f"security/boardOfDirectors/{int(security_id)}")

    def get_security_classification(self, security_id: int) -> Any:
        """Industry classification for a security. VERIFIED: 200."""
        return self.get_json(f"security/classification/{int(security_id)}")

    def get_corporate_actions(self, security_id: int) -> list:
        """Dividends and bonus shares. VERIFIED: 200, e.g. 5 rows for NABIL.

        Rows carry cashDividend, bonusPercentage, fiscalYear, ratioNum/Den,
        book close and AGM dates. A `0` here is a real declared value, which
        is why the archive stores it with a status rather than discarding it.
        """
        return self.get_json(f"security/corporate-actions/{int(security_id)}")

    def get_report_types(self) -> list:
        """Available NEPSE reports. VERIFIED: 200, 5 types.

        These are *market* statistics (Weekly/Monthly/Annual/AGM/Other), not
        company financial statements.
        """
        return self.get_json("report/report-types")

    def get_security_price_history_page(
        self, security_id: int, page: int = 0, size: int = 100
    ) -> dict:
        """Raw paged envelope of per-symbol daily OHLCV.

        VERIFIED 2026-09-28 for NABIL (id 131): 200 with
        `{"content": [100 rows], "totalPages": 3, "totalElements": 227,
        "last": false}`, i.e. ~227 sessions across 3 pages. Page 3 is empty.

        Each row nests a full `security` object, which is how the reference
        layer gets sector, ISIN, tick size, face value, listing date, credit
        rating and company contact *without extra requests*.
        """
        return self.get_json(
            f"market/security/price/{int(security_id)}?size={int(size)}&page={int(page)}"
        )

    def get_security_price_history(
        self, security_id: int, page: int = 0, size: int = 100
    ) -> list:
        """`content` rows of the per-symbol price history (see above)."""
        envelope = self.get_security_price_history_page(security_id, page, size)
        if isinstance(envelope, dict):
            return envelope.get("content") or []
        return envelope if isinstance(envelope, list) else []

    def get_security_price_history_total(self, security_id: int) -> int:
        """How many sessions NEPSE holds for this symbol (227 for NABIL)."""
        envelope = self.get_security_price_history_page(security_id, 0, 1)
        if isinstance(envelope, dict):
            return int(envelope.get("totalElements") or 0)
        return 0

    def get_floorsheet(
        self,
        business_date: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
        buyer_broker: Optional[int] = None,
        seller_broker: Optional[int] = None,
    ) -> dict:
        """Session floorsheet envelope (contracts, value, trades, totals).

        VERIFIED: 200, `{"floorsheet": [100 rows], "totalAmount", ...}`.

        IMPORTANT LIMITATION, verified 2026-09-28: the `buyerBroker` /
        `sellerBroker` filters that NEPSE's own UI sends are **ignored by the
        API** - `buyerBroker=1`, `=3` and `=4` all returned byte-identical
        results. The per-security variant (`nots/security/floorsheet/{id}`)
        returns 403 behind NEPSE's WAF. Both `buyerMemberId` and
        `sellerMemberId` are null in practice, and NEPSE's own website renders
        " - " for them.

        Consequence: per-broker attribution is impossible from official data,
        so the parameters are kept only so the block is reproducible.
        """
        params = [f"limit={int(limit)}", f"offset={int(offset)}"]
        if business_date:
            params.append(f"date={business_date}")
        if buyer_broker is not None:
            params.append(f"buyerBroker={int(buyer_broker)}")
        if seller_broker is not None:
            params.append(f"sellerBroker={int(seller_broker)}")
        return self.get_json("nepse-data/floorsheet?" + "&".join(params))

    # ------------------------------------------------------------------
    # Archive-grade accessors.
    #
    # These deliberately do NOT delegate to the library's own helpers, because
    # those swallow every exception and `return []`:
    #
    #     except Exception as e:
    #         print(f"Error fetching today price: {e}")
    #         return []
    #
    # For the archive that is fatal: an empty list would be indistinguishable
    # from a holiday, and a holiday would be recorded as "no change" instead of
    # "not a session". The methods below raise, so the caller can tell the two
    # apart and retry only what actually failed.
    # ------------------------------------------------------------------

    def get_today_price_page(
        self, business_date: Optional[str] = None, page: int = 0, size: int = 500
    ) -> dict:
        """One page of `today-price`: whole-market OHLCV for one business date.

        VERIFIED 2026-09-28: works for current and historical dates
        (2025-09-28 and 2025-12-01 confirmed; 2025-08-24 is outside NEPSE's
        ~227-session window and returns 500).

        Returns the raw envelope `{"content": [...], "totalPages": N, ...}` so
        the caller can paginate. Raises instead of returning `[]` on failure -
        see the note above.
        """
        url = f"{self._API}/nepse-data/today-price?size={int(size)}&page={int(page)}"
        if business_date:
            url += f"&businessDate={business_date}"

        # NEPSE validates this scrambled id against the CURRENT date, not the
        # requested business date; using businessDate here causes HTTP 401.
        # (Documented in the library's own get_today_price.)
        payload_id = self.raw._get_floorsheet_payload_id(0, datetime.now())
        response = self.raw.session.post(
            url, headers=self.raw._get_auth_headers(), json={"id": payload_id}
        )
        if response.status_code != 200:
            logger.warning(
                "NEPSE today-price %s page %s -> HTTP %s; body[:300]: %r",
                business_date, page, response.status_code, response.text[:300],
            )
            # NEPSE's out-of-history answer: permanent, and used by the backfill
            # to find the earliest servable date. Detected before the generic
            # 5xx handling so it is not mistaken for a transient outage.
            if "searched date is not valid" in response.text.lower():
                raise NepseDateOutOfRangeError() from None
            if response.status_code in (401, 403):
                raise NepseAuthError()
            if response.status_code == 429:
                raise NepseRateLimitedError()
            raise NepseUnavailableError()
        try:
            return response.json()
        except ValueError as exc:
            if _looks_like_auth_page(exc):
                raise NepseAuthError() from exc
            raise NepseInvalidResponseError() from exc

    def get_holidays(self, year: int) -> list:
        """NEPSE's published holiday list for a year.

        VERIFIED 2026-09-28: 200, 46 entries for 2025, each with
        `holidayDate` and `holidayDescription`. This lets the archive label a
        date as a known non-session from the exchange's own calendar rather
        than inferring it from an empty response.
        """
        payload = self.get_json(f"holiday/list?year={int(year)}")
        if isinstance(payload, dict):
            for key in ("content", "holidays", "data"):
                if isinstance(payload.get(key), list):
                    return payload[key]
            return []
        return payload if isinstance(payload, list) else []


