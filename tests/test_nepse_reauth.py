"""Regression test for the sequential re-authentication path.

A long backfill re-runs the re-auth path on every date at sub-5s spacing. The
single-flight guard (never re-authenticate within REAUTH_MIN_GAP_SECONDS) was
written for *concurrent* callers, but it also blocked a sequential caller,
which then retried the same dead token on every date: 268 consecutive
NEPSE_AUTH_FAILED dates in one run. The escape hatch is that a re-auth which
does not fix the rejection disables the guard until it succeeds.
"""

from __future__ import annotations

import pytest
import requests

from app.nepse import client as client_module
from app.nepse.client import REAUTH_MIN_GAP_SECONDS, NepseClientAdapter
from app.nepse.exceptions import NepseAuthError


class FakeNepse:
    """Minimal stand-in for the library client, focused on auth behaviour."""

    def __init__(self, auth_fixes_rejection: bool = True) -> None:
        self.rejected = True
        self.auth_calls = 0
        # When False, re-authenticating does not clear the rejection, which is
        # what makes the guard's escape hatch observable.
        self.auth_fixes_rejection = auth_fixes_rejection

    def authenticate(self) -> None:
        self.auth_calls += 1
        if self.auth_fixes_rejection:
            self.rejected = False


def _http_401() -> requests.exceptions.HTTPError:
    response = requests.Response()
    response.status_code = 401
    response.url = "https://www.nepalstock.com.np/api/nots/nepse-data/market-open"
    return requests.exceptions.HTTPError("401 Client Error: Unauthorized", response=response)


def _call(fake: FakeNepse) -> str:
    if fake.rejected:
        raise _http_401()
    return "ok"


@pytest.fixture
def clock(monkeypatch):
    """Freeze `time.time` so the single-flight window is deterministic."""
    now = [1_000.0]
    monkeypatch.setattr(client_module.time, "time", lambda: now[0])
    return now


def _adapter(fake: FakeNepse) -> NepseClientAdapter:
    adapter = NepseClientAdapter(timeout=5)
    adapter._client = fake  # type: ignore[assignment]
    adapter._pace = lambda: None  # no sleeping in tests
    adapter._last_auth = 1_000.0  # a token was just acquired
    return adapter


async def test_sequential_failures_each_reauthenticate(clock):
    """A dead token must be refreshed on every rejection, not just the first.

    This is the exact shape of the backfill that produced 268 consecutive
    failures: each date 0.9s apart, all inside the 5s single-flight window.
    """
    fake = FakeNepse(auth_fixes_rejection=False)
    adapter = _adapter(fake)

    # Two back-to-back rejections, each still failing after a re-auth.
    for i in range(2):
        clock[0] += 0.9
        with pytest.raises(NepseAuthError):
            await adapter.call(f"date-{i}", lambda: _call(fake))

    # Two rejections, two re-auth attempts. Under the old guard the second one
    # would have been skipped, retrying the same dead token.
    assert fake.auth_calls == 2
    assert adapter._auth_retry_failed is True


async def test_escape_hatch_lets_a_later_call_recover(clock):
    """Once the token is actually good, the next call succeeds and re-arms."""
    fake = FakeNepse(auth_fixes_rejection=False)
    adapter = _adapter(fake)

    with pytest.raises(NepseAuthError):
        await adapter.call("date-1", lambda: _call(fake))
    assert adapter._auth_retry_failed is True

    # NEPSE's auth service recovers: a re-auth now yields a usable token.
    fake.auth_fixes_rejection = True
    clock[0] += 0.9  # still inside the single-flight window
    result = await adapter.call("date-2", lambda: _call(fake))

    assert result == "ok"
    assert fake.auth_calls == 2
    assert adapter._auth_retry_failed is False


async def test_guard_shares_a_proven_token(clock):
    """A token proven by a successful request is reused, not re-acquired.

    This is the real concurrency case: caller A re-authenticated and its
    request succeeded, so caller B (1s later, inside the window) can share the
    token instead of hammering NEPSE's auth endpoint again during a flap.
    """
    fake = FakeNepse(auth_fixes_rejection=True)
    adapter = _adapter(fake)
    # Caller A proved the token: it authenticated and then succeeded.
    await adapter.call("caller-a", lambda: _call(fake))
    assert adapter._auth_proven is True
    auth_after_a = fake.auth_calls

    # Caller B arrives inside the window and NEPSE flaps exactly once. Since
    # the shared token is proven, B retries it rather than re-authenticating.
    clock[0] += 1.0
    seen = {"n": 0}

    def flap_once() -> str:
        seen["n"] += 1
        if seen["n"] == 1:
            raise _http_401()
        return "ok"

    result = await adapter.call("caller-b", flap_once)

    assert result == "ok"
    assert fake.auth_calls == auth_after_a  # token shared, not re-acquired


async def test_unproven_recent_token_is_still_refreshed(clock):
    """A recent token that has never succeeded must not be trusted."""
    fake = FakeNepse(auth_fixes_rejection=True)
    adapter = _adapter(fake)
    adapter._last_auth = clock[0]  # just "authenticated", nothing proven yet
    fake.rejected = True

    result = await adapter.call("caller", lambda: _call(fake))

    assert result == "ok"
    assert fake.auth_calls == 1


async def test_successful_proactive_refresh_rearms_the_escape_hatch(clock):
    fake = FakeNepse()
    adapter = _adapter(fake)
    adapter._auth_retry_failed = True
    clock[0] += client_module.AUTH_REFRESH_SECONDS + 1

    adapter._refresh_auth_if_stale()

    assert fake.auth_calls == 1
    assert adapter._auth_retry_failed is False
