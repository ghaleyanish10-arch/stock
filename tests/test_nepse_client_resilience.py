"""Tests for the adapter's failure translation and resilience layers.

Covers: specific error mapping (auth flap / rate limit / outage), the
re-auth retry on token rejection, 429/5xx backoff retries, session
hardening, and the raw diagnostics fetch (status + content-type +
body[:500] logging contract).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests

from app.nepse import client as client_module
from app.nepse.client import NepseClientAdapter, _normalize_exception
from app.nepse.exceptions import (
    NepseAuthError,
    NepseInvalidResponseError,
    NepseRateLimitedError,
    NepseServiceError,
    NepseTimeoutError,
    NepseUnavailableError,
)


# ----------------------------------------------------------------------
# _normalize_exception mapping
# ----------------------------------------------------------------------


def test_json_decode_error_maps_to_auth():
    # The library maps NEPSE's HTTP 401 + HTML page to JSONDecodeError.
    exc = ValueError("Expecting value: line 1 column 1 (char 0)")
    assert isinstance(_normalize_exception(exc), NepseAuthError)


def test_auth_page_text_maps_to_auth():
    exc = RuntimeError("<html>WARNING: UNAUTHORIZED ACCESS</html>")
    assert isinstance(_normalize_exception(exc), NepseAuthError)


def test_http_429_maps_to_rate_limited():
    response = SimpleNamespace(status_code=429)
    exc = requests.exceptions.HTTPError("429", response=response)
    assert isinstance(_normalize_exception(exc), NepseRateLimitedError)


def test_http_401_and_403_map_to_auth():
    for status in (401, 403):
        response = SimpleNamespace(status_code=status)
        exc = requests.exceptions.HTTPError(str(status), response=response)
        assert isinstance(_normalize_exception(exc), NepseAuthError), status


def test_http_5xx_maps_to_unavailable():
    response = SimpleNamespace(status_code=503)
    exc = requests.exceptions.HTTPError("503", response=response)
    assert isinstance(_normalize_exception(exc), NepseUnavailableError)


def test_timeout_maps_to_timeout():
    assert isinstance(_normalize_exception(TimeoutError()), NepseTimeoutError)
    assert isinstance(_normalize_exception(RuntimeError("read timed out")), NepseTimeoutError)


def test_unknown_error_stays_generic():
    assert type(_normalize_exception(RuntimeError("mystery"))) is NepseServiceError


def test_service_errors_pass_through_unchanged():
    original = NepseInvalidResponseError()
    assert _normalize_exception(original) is original


# ----------------------------------------------------------------------
# call(): re-auth retry and 429/5xx backoff
# ----------------------------------------------------------------------


class _AuthStub:
    """Minimal stand-in for the library Nepse object."""

    def __init__(self) -> None:
        self.authenticate_calls = 0

    def authenticate(self) -> None:
        self.authenticate_calls += 1


def _adapter_with_stub() -> tuple[NepseClientAdapter, _AuthStub]:
    adapter = NepseClientAdapter(timeout=5)
    stub = _AuthStub()
    adapter._client = stub  # bypass start(); raw property returns the stub
    # Token is 100s old: young enough to skip the proactive refresh
    # (< AUTH_REFRESH_SECONDS), old enough to allow a forced re-auth
    # (>= REAUTH_MIN_GAP_SECONDS).
    adapter._last_auth = client_module.time.time() - 100.0
    return adapter, stub


async def test_call_retries_once_after_reauth_on_auth_flap():
    adapter, stub = _adapter_with_stub()
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return "OK"

    assert await adapter.call("op", flaky) == "OK"
    assert calls["n"] == 2
    assert stub.authenticate_calls == 1  # one forced re-auth


async def test_call_raises_auth_error_when_reauth_retry_fails():
    adapter, stub = _adapter_with_stub()

    def always_flaky() -> None:
        raise ValueError("Expecting value: line 1 column 1 (char 0)")

    with pytest.raises(NepseAuthError):
        await adapter.call("op", always_flaky)
    assert stub.authenticate_calls == 1


async def test_call_single_flight_skips_reauth_when_token_is_fresh():
    """Concurrent rejections must share one re-auth, not stampede the auth
    endpoint: a token that is recent *and proven* is reused as-is."""
    adapter, stub = _adapter_with_stub()
    adapter._last_auth = client_module.time.time()  # just refreshed
    # Proven: some earlier request already succeeded with this token, so it is
    # known-good and a concurrent rejection should not spend another auth call.
    adapter._auth_proven = True
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return "OK"

    assert await adapter.call("op", flaky) == "OK"
    assert calls["n"] == 2  # still retried with the existing token
    assert stub.authenticate_calls == 0


async def test_call_reauthenticates_when_recent_token_is_unproven():
    """A recent token that has never succeeded is not trusted.

    Without this, a sequential caller - the backfill, retrying every 0.9s -
    reuses a dead token forever instead of refreshing it.
    """
    adapter, stub = _adapter_with_stub()
    adapter._last_auth = client_module.time.time()  # recent, but unproven
    assert adapter._auth_proven is False
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return "OK"

    assert await adapter.call("op", flaky) == "OK"
    assert stub.authenticate_calls == 1


async def test_call_retries_429_with_backoff_then_gives_up(monkeypatch):
    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: None)
    adapter, _ = _adapter_with_stub()
    calls = {"n": 0}

    def always_429() -> None:
        calls["n"] += 1
        raise requests.exceptions.HTTPError(
            "429", response=SimpleNamespace(status_code=429)
        )

    with pytest.raises(NepseRateLimitedError):
        await adapter.call("op", always_429)
    assert calls["n"] == client_module.HTTP_RETRIES + 1


async def test_call_retries_5xx_then_succeeds(monkeypatch):
    monkeypatch.setattr(client_module.time, "sleep", lambda seconds: None)
    adapter, _ = _adapter_with_stub()
    calls = {"n": 0}

    def one_503_then_ok() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.exceptions.HTTPError(
                "503", response=SimpleNamespace(status_code=503)
            )
        return "OK"

    assert await adapter.call("op", one_503_then_ok) == "OK"
    assert calls["n"] == 2


async def test_call_does_not_retry_4xx_client_errors():
    adapter, _ = _adapter_with_stub()
    calls = {"n": 0}

    def always_404() -> None:
        calls["n"] += 1
        raise requests.exceptions.HTTPError(
            "404", response=SimpleNamespace(status_code=404)
        )

    with pytest.raises(NepseServiceError):
        await adapter.call("op", always_404)
    assert calls["n"] == 1


# ----------------------------------------------------------------------
# Session hardening
# ----------------------------------------------------------------------


def test_harden_session_adds_browser_headers_and_timeout():
    import requests as requests_lib

    adapter = NepseClientAdapter(timeout=7)
    session = requests_lib.Session()
    adapter._client = SimpleNamespace(session=session)

    # Install a sentinel BEFORE hardening: the wrapper captures the original
    # request at harden time and must delegate to it with a timeout injected.
    captured = {}

    def fake_request(method, url, **kwargs):
        captured.update(kwargs)
        raise AssertionError("network not allowed in test")

    session.request = fake_request
    adapter._harden_session()

    assert "Mozilla/5.0" in session.headers["User-Agent"]
    assert session.headers["Referer"] == "https://www.nepalstock.com.np/"

    with pytest.raises(AssertionError, match="network not allowed"):
        session.request("GET", "https://example.invalid")
    assert captured["timeout"] == 7


# ----------------------------------------------------------------------
# _get_json_with_diagnostics: forensics contract
# ----------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code, text, content_type, json_value=None):
        self.status_code = status_code
        self.text = text
        self.headers = {"content-type": content_type}
        self._json_value = json_value

    def json(self):
        if self._json_value is None:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._json_value


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.requested_urls: list[str] = []

    def get(self, url, headers=None):
        self.requested_urls.append(url)
        return self.response


def _adapter_with_response(response: _FakeResponse) -> NepseClientAdapter:
    adapter = NepseClientAdapter(timeout=5)
    adapter._client = SimpleNamespace(
        session=_FakeSession(response), _get_auth_headers=lambda: {}
    )
    return adapter


async def test_diagnostics_auth_page_raises_auth_error_and_logs(caplog):
    adapter = _adapter_with_response(
        _FakeResponse(
            status_code=401,
            text="<html>WARNING: UNAUTHORIZED ACCESS</html>",
            content_type="text/html",
        )
    )
    with caplog.at_level("WARNING", logger="app.nepse.client"):
        with pytest.raises(NepseAuthError):
            adapter.get_nepse_index()
    text = caplog.text
    assert "HTTP 401" in text
    assert "content-type: text/html" in text
    assert "UNAUTHORIZED ACCESS" in text  # body[:500] is in the log


async def test_diagnostics_429_raises_rate_limited(caplog):
    adapter = _adapter_with_response(
        _FakeResponse(status_code=429, text="slow down", content_type="text/plain")
    )
    with caplog.at_level("WARNING", logger="app.nepse.client"):
        with pytest.raises(NepseRateLimitedError):
            adapter.get_sub_indices()
    assert "HTTP 429" in caplog.text


async def test_diagnostics_500_raises_invalid_response(caplog):
    adapter = _adapter_with_response(
        _FakeResponse(status_code=500, text="boom", content_type="text/html")
    )
    with caplog.at_level("WARNING", logger="app.nepse.client"):
        with pytest.raises(NepseInvalidResponseError):
            adapter.get_nepse_index()
    assert "HTTP 500" in caplog.text


async def test_diagnostics_non_json_200_logs_body_and_raises_invalid(caplog):
    adapter = _adapter_with_response(
        _FakeResponse(status_code=200, text="<html>weird</html>", content_type="text/html")
    )
    with caplog.at_level("WARNING", logger="app.nepse.client"):
        with pytest.raises(NepseInvalidResponseError):
            adapter.get_nepse_index()
    text = caplog.text
    assert "non-JSON" in text
    assert "content-type: text/html" in text
    assert "<html>weird</html>" in text


async def test_diagnostics_success_returns_parsed_json():
    adapter = _adapter_with_response(
        _FakeResponse(
            status_code=200,
            text='[{"index": "NEPSE Index", "close": 2600.0}]',
            content_type="application/json",
            json_value=[{"index": "NEPSE Index", "close": 2600.0}],
        )
    )
    payload = adapter.get_nepse_index()
    assert payload[0]["close"] == 2600.0
