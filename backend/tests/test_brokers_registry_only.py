"""The brokers API must stay registry-only.

NEPSE does not publish per-broker trade flow, so the endpoint must never grow
buy/sell/net columns that it cannot fill. This test fails the build if someone
adds them, and pins the explanation that the UI shows.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def seeded_brokers():
    """Seed two broker rows: the endpoint is a READER, it never seeds.

    Before the conftest isolation guard this test silently relied on broker
    rows an admin sync had left in the developer's database; on a fresh DB it
    read count=0 and failed. Registry rows here are hand-written minimal
    members covering both dealer and dealer-less rows, and cleanup removes
    them so the run stays repeatable on any database.
    """
    from app.db.session import SessionLocal

    from app.db.models import Broker

    with SessionLocal() as s:
        existing = s.get(Broker, "1")
        created = False
        if existing is None:
            s.add(Broker(member_code="1", member_name="Test Broker One", is_dealer=False, is_active=True, province="Bagmati"))
            s.add(Broker(member_code="2", member_name="Test Dealer Two", is_dealer=True, is_active=True, province="Koshi"))
            s.commit()
            created = True
    try:
        yield
    finally:
        if created:
            with SessionLocal() as s:
                for code in ("1", "2"):
                    row = s.get(Broker, code)
                    if row is not None and row.member_name.startswith("Test "):
                        s.delete(row)
                s.commit()

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


def test_brokers_response_has_no_flow_fields(seeded_brokers) -> None:
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


def test_brokers_states_attribution_is_unavailable(seeded_brokers) -> None:
    with TestClient(app) as client:
        payload = client.get("/api/reference/brokers").json()

    attribution = payload["attribution"]
    assert attribution["available"] is False
    reason = attribution["reason"].lower()
    # The reason must name the cause, so the page can explain it rather than
    # leaving a blank panel.
    assert "nepalstock" in reason or "nepse" in reason
    assert "null" in reason or "not honoured" in reason or "not honored" in reason


def test_broker_rows_expose_only_registry_fields(seeded_brokers) -> None:
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
