"""The brokers API must stay registry-only.

NEPSE does not publish per-broker trade flow, so the endpoint must never grow
buy/sell/net columns that it cannot fill. This test fails the build if someone
adds them, and pins the explanation that the UI shows.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

#: Words that would only appear if the endpoint started inventing flow data.
FLOW_WORDS = (
    "buy",
    "sell",
    "net_flow",
    "netflow",
    "net_buy",
    "net_sell",
    "turnover",
    "volume",
    "traded",
    "amount",
    "debit",
    "credit",
)


def test_brokers_response_has_no_flow_fields() -> None:
    with TestClient(app) as client:
        payload = client.get("/api/reference/brokers").json()

    assert payload["count"] > 0
    assert payload["brokers"], "the official member registry must not be empty"

    # Only the broker rows are scanned. The `attribution` block deliberately
    # *mentions* buyer/seller fields, because that is the explanation of why
    # they are absent.
    blob = repr(payload["brokers"]).lower()
    for word in FLOW_WORDS:
        assert word not in blob, f"a broker row mentions {word!r}; the registry must be registry-only"

    # No flow section may appear at the top level either.
    for word in FLOW_WORDS:
        assert not any(word in key.lower() for key in payload), f"top-level key mentions {word!r}"


def test_brokers_states_attribution_is_unavailable() -> None:
    with TestClient(app) as client:
        payload = client.get("/api/reference/brokers").json()

    attribution = payload["attribution"]
    assert attribution["available"] is False
    reason = attribution["reason"].lower()
    # The reason must name the cause, so the page can explain it rather than
    # leaving a blank panel.
    assert "nepalstock" in reason or "nepse" in reason
    assert "null" in reason or "not honoured" in reason or "not honored" in reason


def test_broker_rows_expose_only_registry_fields() -> None:
    expected = {
        "member_code",
        "member_name",
        "is_dealer",
        "is_active",
        "province",
        "district",
        "phone",
        "email",
        "website",
    }
    with TestClient(app) as client:
        rows = client.get("/api/reference/brokers").json()["brokers"]

    for row in rows[:20]:
        assert set(row) == expected
