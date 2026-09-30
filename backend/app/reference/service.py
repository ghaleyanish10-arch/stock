"""Reference data: securities, sectors, brokers, mutual funds, corporate actions.

This is the "boring but load-bearing" layer: a screener, a chart, an alert and
a CSV import all need to turn a symbol into a name, a sector, a manager and a
dividend history. NEPSE exposes most of that, but spread across several
endpoints, so it is normalised and cached here.

Two honest gaps are represented as data, not as exceptions:

* Mutual fund NAV is `not_published` - NEPSE does not carry it, and the row
  says so with an explanation, so the UI shows "Not published by NEPSE"
  instead of a bare dash.
* Listed share counts and credit ratings are `NULL` when NEPSE omits them,
  which is different from a reported zero.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any, Iterable, Optional

from fastapi import HTTPException

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.provenance import NOT_PUBLISHED_BY_NEPSE, Measured, ValueStatus
from app.db.models import (
    Announcement,
    Broker,
    CorporateAction,
    Fund,
    FundNavPoint,
    Security,
    Sector,
    utcnow,
)
from app.nepse.client import NepseClientAdapter
from app.nepse.exceptions import SymbolNotFoundError
from app.nepse.service import validate_symbol

logger = logging.getLogger(__name__)


class ReferenceNotFoundError(SymbolNotFoundError):
    """A symbol has no NEPSE security id we can enrich from."""


def _join_names(value: Any) -> Optional[str]:
    """Comma-join a list of {name, description} objects or plain strings."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value or None
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            name = _text(
                item.get("description") or item.get("name") if isinstance(item, dict) else item
            )
            if name and name not in names:
                names.append(name)
        return ", ".join(names) if names else None
    return _text(value)


# NEPSE's instrument-type code for mutual funds. VERIFIED 2026-09-28 against
# C30MF / SFMF / MMF1 / MNMF1 / RMF1 / RMF2, all of which report
# `CDS` / "Mutual Funds".
#
# Two traps worth recording:
#   * The code is `CDS`, not `MF` - a substring test for "MF" silently matches
#     nothing.
#   * Laghubitta (microfinance cooperatives) are `EQ` with sector
#     "Microfinance", so name or sector matching would wrongly file them as
#     funds. Only the instrument type is authoritative.
MUTUAL_FUND_INSTRUMENT_CODE = "CDS"
MUTUAL_FUND_INSTRUMENT_NAME = "mutual fund"


def is_mutual_fund(code: Optional[str], description: Optional[str] = None) -> bool:
    """True when an instrument type identifies a mutual fund."""
    if (code or "").strip().upper() == MUTUAL_FUND_INSTRUMENT_CODE:
        return True
    return MUTUAL_FUND_INSTRUMENT_NAME in (description or "").strip().lower()


def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> Optional[int]:
    num = _num(value)
    return int(num) if num is not None else None


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _name_text(value: Any) -> Optional[str]:
    """For display names: collapse internal whitespace runs.

    NEPSE name fields arrive with irregular spacing ("Prabhu  Bank Limited",
    double space), which broke word-based search. Unlike `_text`, this must
    NOT be applied to body/structured text where line layout carries meaning.
    """
    text = _text(value)
    if text is None:
        return None
    return " ".join(text.split())


#: Labelled lines that carry dividend/book-closure/AGM facts inside
#: announcement text. Case-insensitive; the value is kept verbatim.
_NOTICE_LABELS: tuple[tuple[str, str], ...] = (
    ("cash dividend", "cash_dividend"),
    ("bonus share", "bonus_pct"),
    ("bonus", "bonus_pct"),
    ("book close", "book_close"),
    ("book closure", "book_close"),
    ("agm date", "agm_date"),
    ("agm no", "agm_no"),
    ("right share", "right_pct"),
    ("right issue", "right_pct"),
    ("rights issue", "right_pct"),
    ("fiscal year", "fiscal_year"),
)


def _parse_notice_body(body: Optional[str]) -> Optional[dict[str, str]]:
    """Extract labelled facts from announcement text, verbatim.

    NEPSE's corporate-actions rows carry only the bonus figures; the cash
    dividend, book-closure and AGM dates for NABIL exist only inside the AGM
    notice's `newsBody` (verified 2026-09-28). This reads *labelled* lines and
    stores them exactly as written, so a missing label stays missing and the
    UI can show the raw text next to the extraction.
    """
    if not body:
        return None
    plain = body.replace("<br", "\n<br").replace("<p>", "\n").replace("</p>", "\n")
    plain = plain.replace("&nbsp;", " ").replace("&amp;", "&")
    found: dict[str, str] = {}
    for line in plain.splitlines():
        label, sep, value = line.strip().partition(":")
        if not sep or not value.strip():
            continue
        cleaned = label.strip().lower()
        for prefix, key in _NOTICE_LABELS:
            if cleaned.startswith(prefix):
                found[key] = value.strip()
                break
    return found or None


def _parse_notice_datetime(value: Any) -> Optional[datetime]:
    """Parse NEPSE's announcement timestamps ('2026-09-27T13:24:23.201+05:45'
    or similar); returns None rather than guessing."""
    if value is None or value == "":
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_true(value: Any) -> Optional[bool]:
    """NEPSE mixes booleans, 'Y'/'N' and 'true'/'false'. None stays None."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("y", "yes", "true", "1", "a", "active"):
        return True
    if text in ("n", "no", "false", "0", "i", "inactive"):
        return False
    return None


class ReferenceService:
    """Loads and serves NEPSE reference data."""

    def __init__(self, client: NepseClientAdapter) -> None:
        self._client = client

    # -- securities ----------------------------------------------------

    async def sync_securities(self, session: Session) -> int:
        """Refresh the security master.

        Source: `nots/security?nonDelisted=true` via the library. VERIFIED
        2026-09-28: 568 rows, each with `id`, `symbol`, `securityName`, `name`
        and `activeStatus`.

        This is the only bulk source that carries a symbol. Richer fields
        (sector, instrument type, ISIN, listed shares) need one call per symbol
        and are added by `enrich_security` on demand, because enriching all 568
        would mean 568 upstream requests.
        """
        payload = await self._client.call(
            "get_security_master", self._client.get_security_master
        )
        rows = payload if isinstance(payload, list) else []
        count = 0
        for row in rows:
            symbol = _text(row.get("symbol") or row.get("securitySymbol"))
            if not symbol:
                continue
            symbol = symbol.upper()
            security = session.get(Security, symbol)
            if security is None:
                security = Security(symbol=symbol)
                session.add(security)
            security.name = (
                _name_text(row.get("securityName") or row.get("name")) or security.name
            )
            security.nepse_security_id = (
                _int(row.get("id") or row.get("securityId")) or security.nepse_security_id
            )
            active = _is_true(row.get("activeStatus"))
            if active is not None:
                security.is_active = active
            security.updated_at = utcnow()
            count += 1
        session.commit()
        logger.info("synced %d securities", count)
        return count

    async def enrich_missing_listed_shares(
        self, session: Session, limit: Optional[int] = None, resume: bool = True
    ) -> dict[str, Any]:
        """Bulk-fetch `stockListedShares` for securities that lack it.

        Market cap is `listed shares x LTP`, and NEPSE exposes listed shares only
        on the per-security detail endpoint, never in the 568-row security
        master. So a market-cap treemap or screener is unusable until most
        securities have been enriched. At the adapter's 120ms pacing the full
        master is about a minute of upstream traffic, which is why this is a
        resumable bulk operation rather than 568 ad-hoc page views.

        `resume=True` (the default) skips symbols that already have listed
        shares, so an interrupted run can simply be re-invoked. Failures are
        counted and the loop continues: one dead symbol must not abandon the
        other 480.

        Returns a summary including the symbols that could not be enriched, so
        the caller can report them rather than implying full coverage.
        """
        if limit is not None:
            rows = session.scalars(
                select(Security)
                .where(Security.listed_shares.is_(None))
                .order_by(Security.symbol)
                .limit(limit)
            ).all()
        elif resume:
            rows = session.scalars(
                select(Security)
                .where(Security.listed_shares.is_(None))
                .order_by(Security.symbol)
            ).all()
        else:
            rows = session.scalars(select(Security).order_by(Security.symbol)).all()

        enriched = 0
        failed: list[str] = []
        for i, security in enumerate(rows, 1):
            try:
                await self.enrich_security(session, security.symbol)
            except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the run
                failed.append(security.symbol)
                logger.warning(
                    "enrich failed for %s: %s", security.symbol, exc, exc_info=True
                )
                session.rollback()
                continue
            enriched += 1
            # Commit in batches so an interrupted run keeps its progress.
            if i % 25 == 0:
                session.commit()
                logger.info("enriched %d/%d", i, len(rows))

        session.commit()
        remaining = session.scalar(
            select(func.count()).select_from(Security).where(Security.listed_shares.is_(None))
        )
        return {
            "attempted": len(rows),
            "enriched": enriched,
            "failed": failed,
            "remaining_without_listed_shares": remaining or 0,
        }

    async def enrich_security(self, session: Session, symbol: str) -> dict[str, Any]:
        """Pull one symbol's full detail from `nots/security/{id}`.

        Adds sector, instrument type, ISIN, tick size, face value, listing date,
        credit rating and `stockListedShares` - the last of which the archive
        needs to derive market cap, since NEPSE's live `marketCapitalization`
        is null and its historical one is denominated in millions.

        Called on demand rather than for all 568 symbols.
        """
        sym = validate_symbol(symbol)
        security = session.get(Security, sym)
        if security is None or security.nepse_security_id is None:
            await self.sync_securities(session)
            security = session.get(Security, sym)
        if security is None or security.nepse_security_id is None:
            raise ReferenceNotFoundError(sym)

        detail = await self._client.call(
            f"security_detail:{sym}",
            lambda: self._client.get_security_detail_enriched(security.nepse_security_id),
        )
        detail = detail if isinstance(detail, dict) else {}
        inner = detail.get("security") if isinstance(detail.get("security"), dict) else {}

        company = inner.get("companyId") if isinstance(inner.get("companyId"), dict) else {}
        sector = company.get("sectorMaster") if isinstance(company.get("sectorMaster"), dict) else {}
        instrument = inner.get("instrumentType") if isinstance(inner.get("instrumentType"), dict) else {}

        security.name = _text(inner.get("securityName")) or security.name
        security.isin = _text(inner.get("isin")) or security.isin
        security.tick_size = _num(inner.get("tickSize")) or security.tick_size
        security.face_value = _num(inner.get("faceValue")) or security.face_value
        security.listing_date = (
            (str(inner.get("listingDate"))[:10] if inner.get("listingDate") else None)
            or security.listing_date
        )
        security.credit_rating = _text(inner.get("creditRating")) or security.credit_rating
        security.security_type = (
            _text(instrument.get("code")) or security.security_type
        )
        security.sector_code = (
            _text(sector.get("sectorDescription")) or security.sector_code
        )
        # `stockListedShares` is the archive's only route to a real market cap.
        # Promoter shares report null, so keep whatever we already had rather
        # than overwriting a good value with None.
        listed = _int(detail.get("stockListedShares"))
        if listed is not None:
            security.listed_shares = listed
        # Promoter/public split, from the same detail payload. VERIFIED
        # 2026-09-28 for NABIL: promoterShares=158121099, publicShares=112448885,
        # promoterPercentage=58.44, publicPercentage=41.56. Absent keys stay
        # absent (NULL = not reported), never coerced to zero.
        for column, key in (
            ("promoter_shares", "promoterShares"),
            ("public_shares", "publicShares"),
            ("promoter_pct", "promoterPercentage"),
            ("public_pct", "publicPercentage"),
        ):
            value = _num(detail.get(key))
            if value is not None:
                setattr(security, column, value)
        share_group = inner.get("shareGroupId")
        security.board = (
            _text(share_group.get("name") if isinstance(share_group, dict) else share_group)
            or security.board
        )
        security.updated_at = utcnow()

        # Persist the sector so it can be filtered on.
        sector_name = _text(sector.get("sectorDescription"))
        if sector_name:
            code = _text(sector.get("id")) or sector_name
            if session.scalar(select(Sector).where(Sector.code == str(code))) is None:
                session.add(
                    Sector(code=str(code), name=sector_name,
                           index_symbol=_text(sector.get("indexSymbol")))
                )

        # Mutual fund instruments become fund rows so the registry is real.
        # Only classify as fund if instrument type is CDS (Mutual Funds), not NCD (debentures) etc.
        instrument_code = _text(instrument.get("code"))
        instrument_desc = _text(instrument.get("description"))
        is_fund = is_mutual_fund(instrument_code, instrument_desc)
        # Additional safety: explicitly exclude NCD (Non-Convertible Debentures)
        if instrument_code and instrument_code.upper() == "NCD":
            is_fund = False
        if is_fund:
            self._upsert_fund(session, security, detail)

        session.commit()
        return {
            "symbol": sym,
            "sector": security.sector_code,
            "security_type": security.security_type,
            "security_type_name": _text(instrument.get("description")),
            "is_mutual_fund": is_fund,
            "listed_shares": security.listed_shares,
            "isin": security.isin,
            "credit_rating": security.credit_rating,
        }

    def _upsert_fund(self, session: Session, security: Security, detail: dict) -> None:
        fund = session.get(Fund, security.symbol)
        if fund is None:
            fund = Fund(code=security.symbol, nav=None, nav_date=None)
            session.add(fund)
        fund.name = security.name or fund.name
        fund.category = security.security_type
        # Populate fund metadata from NEPSE security detail (enrich_security)
        # detail is the raw response from nots/security/{id}
        if detail:
            sec = detail.get("security") if isinstance(detail.get("security"), dict) else {}
            fund.scheme_description = _text(sec.get("schemeDescription"))
            fund.scheme_name = _name_text(sec.get("schemeName"))
            fund.isin = _text(sec.get("isin")) or fund.isin
            fund.face_value = _num(sec.get("faceValue")) or fund.face_value
            fund.listing_date = (
                str(sec.get("listingDate"))[:10] if sec.get("listingDate") else None
            ) or fund.listing_date
            fund.units = _int(detail.get("stockListedShares")) or fund.units
            # Fund size = units * face_value (derivable)
            if fund.units is not None and fund.face_value is not None:
                fund.fund_size = float(fund.units) * float(fund.face_value)
            # Determine close_ended from scheme_description
            if fund.scheme_description:
                desc_lower = fund.scheme_description.lower()
                if "close" in desc_lower and ("end" in desc_lower or "maturity" in desc_lower):
                    fund.close_ended = True
                else:
                    fund.close_ended = False
# Try to extract maturity date from scheme_description (e.g., "10 years maturity")
        if fund.scheme_description and fund.close_ended:
            import re
            # Match various formats: "10 years maturity", "10 years Maturity", "10 years of Maturity", 
            # "7 years of maturity", "12 years of Maturity", etc.
            match = re.search(r'(\d+)\s*years?\s*(?:of\s+)?maturity', fund.scheme_description, re.IGNORECASE)
            if not match:
                # Fallback: for close-ended funds, "X years" often implies maturity
                match = re.search(r'(\d+)\s*years?', fund.scheme_description, re.IGNORECASE)
            if match and fund.listing_date:
                try:
                    years = int(match.group(1))
                    from datetime import datetime, timedelta
                    list_date = datetime.strptime(fund.listing_date, "%Y-%m-%d")
                    maturity = list_date + timedelta(days=years * 365)
                    fund.maturity_date = maturity.strftime("%Y-%m-%d")
                except (ValueError, TypeError):
                    pass
        # NEPSE publishes no NAV, so this stays not_published until a CSV or
        # manual import supplies one.
        if fund.nav is None:
            fund.nav_status = ValueStatus.NOT_PUBLISHED
            fund.nav_source = "nepse"
        fund.updated_at = utcnow()

    def list_securities(
        self, session: Session, active_only: bool = True, search: Optional[str] = None
    ) -> list[Security]:
        stmt = select(Security)
        if active_only:
            stmt = stmt.where(Security.is_active.is_(True))
        if search:
            # Upstream names carry irregular spacing ("Prabhu  Bank Limited",
            # double space) and users type natural queries ("prabhu bank"), so
            # collapse runs of whitespace on both sides before the LIKE: each
            # word is matched by a %..% pattern joined with AND.
            words = search.split()
            for w in words:
                stmt = stmt.where(
                    Security.symbol.ilike(f"%{w}%") | Security.name.ilike(f"%{w}%")
                )
        return list(session.scalars(stmt.order_by(Security.symbol).limit(2000)))

    # -- sectors -------------------------------------------------------

    async def sync_sectors(self, session: Session) -> int:
        """Refresh the sector master from `nots/sector`.

        VERIFIED 2026-09-28: 200, 12 sectors with `id`, `sectorDescription`,
        `activeStatus` and `regulatoryBody`.
        """
        payload = await self._client.call("get_sectors", self._client.get_sectors)
        rows = payload if isinstance(payload, list) else []
        count = 0
        for row in rows:
            name = _text(row.get("sectorDescription") or row.get("name"))
            if not name:
                continue
            code = _text(row.get("id")) or name.upper().replace(" ", "_")[:32]
            sector = session.scalar(select(Sector).where(Sector.code == str(code)))
            if sector is None:
                sector = Sector(code=str(code), name=name)
                session.add(sector)
            sector.name = name
            active = _is_true(row.get("activeStatus"))
            sector.index_symbol = _text(row.get("indexSymbol")) or sector.index_symbol
            count += 1
        session.commit()
        logger.info("synced %d sectors", count)
        return count

    def list_sectors(self, session: Session) -> list[Sector]:
        return list(session.scalars(select(Sector).order_by(Sector.name)))

    # -- brokers -------------------------------------------------------

    async def sync_brokers(self, session: Session) -> int:
        """Refresh the official broker registry (`nots/member`).

        VERIFIED 2026-09-28: 200, `content` with 92 members. `memberCode` is an
        integer; `provinceList`/`districtList` can hold several entries, so
        they are stored comma-joined rather than arbitrarily picking the first.

        This is real, useful reference data (directory, contact details,
        province filter) even though it cannot be joined to floorsheet rows -
        see docs/data-sources.md.
        """
        payload = await self._client.call("get_brokers", self._client.get_brokers)
        rows = payload if isinstance(payload, list) else []
        count = 0
        for row in rows:
            code = _text(row.get("memberCode") or row.get("code"))
            name = _name_text(row.get("memberName") or row.get("name"))
            if not code or not name:
                continue
            broker = session.get(Broker, code)
            if broker is None:
                broker = Broker(member_code=code, member_name=name)
                session.add(broker)
            broker.member_name = name
            broker.is_dealer = _is_true(row.get("isDealer"))
            broker.is_active = _is_true(row.get("activeStatus"))
            broker.province = _join_names(row.get("provinceList") or row.get("province"))
            broker.district = _join_names(row.get("districtList") or row.get("district"))
            # `authorizedContactPerson` is usually null while the flat number
            # field is populated, so prefer the flat fields.
            contact = row.get("authorizedContactPerson")
            broker.phone = (
                _text(row.get("authorizedContactPersonNumber"))
                or (_text(contact.get("contactNumber")) if isinstance(contact, dict) else None)
                or broker.phone
            )
            broker.email = (
                _text(row.get("email"))
                or (_text(contact.get("email")) if isinstance(contact, dict) else None)
                or broker.email
            )
            broker.website = _text(row.get("website") or row.get("webUrl")) or broker.website
            broker.updated_at = utcnow()
            count += 1
        session.commit()
        logger.info("synced %d brokers", count)
        return count

    def list_brokers(
        self,
        session: Session,
        active_only: bool = False,
        province: Optional[str] = None,
        search: Optional[str] = None,
    ) -> list[Broker]:
        stmt = select(Broker)
        if active_only:
            stmt = stmt.where(Broker.is_active.is_(True))
        if province:
            stmt = stmt.where(Broker.province == province)
        if search:
            # Same whitespace-tolerant word matching as list_securities.
            for w in search.split():
                stmt = stmt.where(Broker.member_name.ilike(f"%{w}%"))
        return list(session.scalars(stmt.order_by(Broker.member_name).limit(1000)))

    def broker_provinces(self, session: Session) -> list[str]:
        rows = session.scalars(select(Broker.province).distinct().order_by(Broker.province))
        return [p for p in rows if p]

    # -- mutual funds --------------------------------------------------

    def sync_funds_from_securities(self, session: Session) -> int:
        """Create fund rows for symbols already known to be mutual funds.

        Fund identity comes from `enrich_security`, which records NEPSE's
        instrument type. Matching is on the `CDS` code (see
        `MUTUAL_FUND_INSTRUMENT_CODE`), never on the security name or sector:
        laghubitta cooperatives are `EQ` with sector "Microfinance" and must
        not be filed as funds.

        Only symbols that have already been enriched can be identified, so this
        is a materialisation pass, not a discovery pass.
        """
        stmt = select(Security).where(
            Security.security_type == MUTUAL_FUND_INSTRUMENT_CODE
        )
        securities = list(session.scalars(stmt))
        count = 0
        for security in securities:
            existed = session.get(Fund, security.symbol) is not None
            self._upsert_fund(session, security, {})
            if not existed:
                count += 1
        session.commit()
        logger.info(
            "ensured %d fund rows from %d enriched mutual-fund securities",
            count,
            len(securities),
        )
        return count

    def list_funds(self, session: Session) -> list[Fund]:
        return list(session.scalars(select(Fund).order_by(Fund.code)))

    def fund_nav_measured(self, fund: Fund) -> Measured[float]:
        """A fund's NAV as a `Measured`, explaining itself when it is missing."""
        if fund.nav is None:
            return Measured.not_published(
                "Mutual fund NAV",
                source=fund.nav_source or "nepse",
                note=NOT_PUBLISHED_BY_NEPSE["fund_nav"],
            )
        return Measured.of(fund.nav, source=fund.nav_source or "manual", as_of=fund.nav_date)

    # -- corporate actions ----------------------------------------------

    async def sync_corporate_actions(
        self, session: Session, symbol: str, security_id: int
    ) -> int:
        """Store dividends/bonus for one symbol.

        VERIFIED 2026-09-28: 5 rows for NABIL. A `0` cash dividend is stored
        as 0 (a real "no dividend" declaration) rather than being dropped.
        """
        payload = await self._client.call(
            f"corporate_actions:{symbol}", lambda: self._client.get_corporate_actions(security_id)
        )
        rows = payload if isinstance(payload, list) else []
        symbol = symbol.strip().upper()
        count = 0
        for row in rows:
            fiscal_year = _text(row.get("fiscalYear") or row.get("fiscalYearName"))
            key = fiscal_year or "unknown"
            existing = session.scalar(
                select(CorporateAction).where(
                    CorporateAction.symbol == symbol,
                    CorporateAction.fiscal_year == key,
                )
            )
            if existing is None:
                existing = CorporateAction(symbol=symbol, fiscal_year=key)
                session.add(existing)
            existing.cash_dividend_pct = _num(row.get("cashDividend"))
            existing.bonus_pct = _num(row.get("bonusPercentage"))
            existing.right_pct = _num(row.get("rightPercentage"))
            existing.book_close = _text(row.get("bookCloseDate") or row.get("bookClose"))
            existing.agm_date = _text(row.get("agmDate") or row.get("generalMeetingDate"))
            existing.updated_at = utcnow()
            count += 1
        session.commit()
        logger.info("synced %d corporate actions for %s", count, symbol)
        return count

    def corporate_actions(self, session: Session, symbol: str) -> list[CorporateAction]:
        return list(
            session.scalars(
                select(CorporateAction)
                .where(CorporateAction.symbol == symbol.strip().upper())
                .order_by(CorporateAction.fiscal_year.desc())
            )
        )

    async def sync_announcements(self, session: Session, symbol: str) -> int:
        """Store company news/notices for one symbol from `application/company-news/{id}`.

        VERIFIED 2026-09-28 for NABIL (id 131): 39 items. The body text often
        carries the only structured-adjacent source of cash dividend, book
        closure and AGM dates (the corporate-actions rows do not), so `parsed`
        extracts those *labelled* lines verbatim. A value that is not in the
        text is absent from `parsed` - never an empty string, never a zero.
        """
        security = session.get(Security, symbol.strip().upper())
        if security is None or security.nepse_security_id is None:
            await self.sync_securities(session)
            security = session.get(Security, symbol.strip().upper())
        if security is None or security.nepse_security_id is None:
            raise ReferenceNotFoundError(symbol)

        payload = await self._client.call(
            f"company_news:{symbol}",
            lambda: self._client.get_company_news(security.nepse_security_id),
        )
        rows = payload if isinstance(payload, list) else []
        symbol = symbol.strip().upper()
        seen: set[str] = set()
        count = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            news = row.get("companyNews") if isinstance(row.get("companyNews"), dict) else row
            news_id = _text(news.get("id"))
            if news_id:
                seen.add(news_id)
            existing = (
                session.scalar(
                    select(Announcement).where(
                        Announcement.symbol == symbol,
                        Announcement.nepse_news_id == news_id,
                    )
                )
                if news_id
                else None
            )
            if existing is None:
                existing = Announcement(symbol=symbol, nepse_news_id=news_id)
                session.add(existing)
            existing.headline = _text(news.get("newsHeadline"))
            existing.body = _text(news.get("newsBody"))
            existing.news_type = _text(news.get("newsType"))
            existing.news_source = _text(news.get("newsSource"))
            existing.published_at = _parse_notice_datetime(news.get("addedDate"))
            existing.parsed = _parse_notice_body(existing.body)
            existing.updated_at = utcnow()
            count += 1
        session.commit()
        logger.info("synced %d announcements for %s", count, symbol)
        return count

    def announcements(self, session: Session, symbol: str) -> list[Announcement]:
        """Stored announcements for one symbol, newest first."""
        return list(
            session.scalars(
                select(Announcement)
                .where(Announcement.symbol == symbol.strip().upper())
                .order_by(func.coalesce(Announcement.published_at, Announcement.updated_at).desc())
            )
        )

    def dividend_measured(self, action: CorporateAction, field: str) -> Measured[float]:
        """A dividend/bonus percentage with its status.

        `0` here means "declared as zero", which the UI must show as a value,
        not as a gap.
        """
        value = action.cash_dividend_pct if field == "cash" else action.bonus_pct
        return Measured.of(
            value,
            source="nepse:corporate-actions",
            as_of=action.fiscal_year,
            note=f"Fiscal year {action.fiscal_year}" if action.fiscal_year else None,
        )

    # -- holidays -------------------------------------------------------

    async def sync_holidays(self, session: Session, year: int) -> list[str]:
        """Fetch NEPSE's holiday list so non-sessions can be named, not guessed."""
        payload = await self._client.call(
            f"holidays:{year}", lambda: self._client.get_holidays(year)
        )
        rows = payload if isinstance(payload, list) else []
        dates = [
            (r.get("holidayDate") or "")[:10]
            for r in rows
            if isinstance(r, dict) and r.get("holidayDate")
        ]
        logger.info("fetched %d holidays for %d", len(dates), year)
        return dates

    async def import_nav(
        self,
        session: Session,
        symbol: str,
        payload: dict,
    ) -> dict[str, Any]:
        """Import a NAV point for a fund. Admin only.

        Payload: {"nav": 10.5, "nav_date": "2026-09-28", "source": "manual"}
        """
        from app.db.models import FundNavPoint
        from app.core.provenance import ValueStatus
        
        sym = symbol.strip().upper()
        fund = session.get(Fund, sym)
        if fund is None:
            raise HTTPException(status_code=404, detail=f"Fund {sym} not found")
        
        # Extract and validate payload
        nav = payload.get("nav")
        nav_date = payload.get("nav_date")
        source = payload.get("source", "manual")
        
        if nav is None:
            raise HTTPException(status_code=400, detail="nav is required")
        
        if nav_date is None:
            raise HTTPException(status_code=400, detail="nav_date is required")
        
        # Validate date format YYYY-MM-DD
        import re
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", nav_date):
            raise HTTPException(status_code=400, detail="nav_date must be YYYY-MM-DD")
        
        # Validate NAV is positive
        try:
            nav_val = float(nav)
            if nav_val <= 0:
                raise HTTPException(status_code=400, detail="nav must be a positive number")
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="nav must be a valid number")
        
        # Upsert NAV point
        existing = session.scalar(
            select(FundNavPoint).where(
                FundNavPoint.fund_code == sym, FundNavPoint.nav_date == nav_date
            )
        )
        if existing is None:
            existing = FundNavPoint(fund_code=sym, nav_date=nav_date, nav=nav_val, source=source)
            session.add(existing)
        else:
            existing.nav = nav_val
            existing.source = source
        
        # Update fund's current NAV
        fund.nav = nav_val
        fund.nav_date = nav_date
        fund.nav_status = "ok"
        fund.nav_source = source
        fund.updated_at = utcnow()
        
        session.commit()
        return {"code": sym, "nav": nav_val, "nav_date": nav_date, "source": source}
        
        session.commit()
        return {"code": sym, "nav": nav, "nav_date": nav_date, "source": source}
