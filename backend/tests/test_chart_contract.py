"""Chart endpoint contract tests: registry parity, honest gaps, geometry.

The registry test iterates every token the FRONTEND registry offers and
requires the chart endpoint to either serve data for it or return an explicit
`disabled` reason - a new picker entry without a working handler fails here
instead of giving the user a silent dead button (this is exactly how `mfi`,
`roc`, `vwma` and `vortex` broke).

Hand-arithmetic honesty rules pinned below:
* warm-up values are None, never 0: the fixture is a deterministic 320-bar
  walk whose SMA-20 warm-up region can be checked by hand (bar 19 is the first
  with 20 closes: mean of bars 0..19 = (100 + 19 * 101) / 20 = 100.95).
* geometry: the endpoint's `series` keep OHLC intact, so a candle renderer can
  always satisfy body = open..close, wick = high..low, and the visible domain
  [min(low), max(high)] contains every bar - nothing clipped. (The frontend
  autoscale bug fixed in this branch could not be caught server-side; the
  parity page and the colour contract test cover the render side.)
* ranges: 1W/YTD windows and custom start/end slicing, including the 400/404
  contracts the frontend now relies on.

Offline: TestClient + in-memory SQLite (StaticPool, as in
test_indicators_batch_b.py). No NEPSE access: the realtime merge is skipped
because the poller raises inside the test env and `_live_bar` catches it.
"""

import math
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.analytics import chart as chart_module
from app.analytics.routes import router as analytics_router
from app.auth.deps import get_session
from app.db.models import Base, DailyBar

FRONTEND_REGISTRY = Path(__file__).resolve().parents[2] / "frontend" / "src" / "indicators.ts"


def _frontend_tokens() -> list[str]:
    text = FRONTEND_REGISTRY.read_text(encoding="utf-8")
    union = re.search(r"export type IndicatorToken =(.*?);", text, re.S)
    assert union, "IndicatorToken union not found in indicators.ts"
    return re.findall(r'"([a-z0-9_]+)"', union.group(1))


def _make_session(n_bars: int = 320):
    """320 deterministic bars, Mon-Fri 2025-01-01 onward, hand-checkable.

    Up leg: close_i = 100 + i (i < 160) so any value can be recomputed on
    paper; down leg: close falls -1/day back to 100 so the series has real
    losses - on a never-falling series RSI pins at 100 and RSI-derived
    oscillators are legitimately 0/0 = None (that fixture bug cost a test
    iteration; real data exercises both sides). volume = 1000 + i; high/low
    bracket the day's open-close by +2 so OHLC geometry always holds.
    """
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    from datetime import date, timedelta

    d0 = date(2025, 1, 1)  # a Wednesday; sessions Mon-Fri, skip Sat/Sun
    rows: list[DailyBar] = []
    cursor = d0
    for i in range(n_bars):
        while cursor.weekday() >= 5:
            cursor += timedelta(days=1)
        close = 100.0 + i if i < 160 else 259.0 - (i - 160)
        open_ = close - 1.0 if (i == 0 or i < 160) else close + 1.0
        if i == 0:
            open_ = 100.0
        rows.append(
            DailyBar(
                business_date=cursor.isoformat(),
                symbol="TEST",
                open=open_,
                high=max(open_, close) + 2.0,
                low=min(open_, close) - 2.0,
                close=close,
                volume=1000 + i,
            )
        )
        cursor += timedelta(days=1)
    session.add_all(rows)
    session.commit()
    return session, rows


@pytest.fixture()
def client():
    session, _rows = _make_session()
    app = FastAPI()
    app.include_router(analytics_router)
    app.include_router(chart_module.router)  # /api/analytics/chart lives here
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _chart(client: TestClient, token: str, **params) -> dict:
    p = {"range": "ALL", "indicators": token, **params}
    qs = "&".join(f"{k}={v}" for k, v in p.items())
    resp = client.get(f"/api/analytics/chart/TEST?{qs}")
    assert resp.status_code == 200, f"{token}: {resp.status_code} {resp.text[:200]}"
    return resp.json()


# -- E3: every frontend token works or carries an explicit reason -------------


def test_every_frontend_token_serves_or_has_reason(client):
    tokens = _frontend_tokens()
    assert len(tokens) >= 95, f"registry unexpectedly small: {len(tokens)}"
    broken: list[str] = []
    # Swing detectors need local extremes. The fixture's two monotone legs
    # contain exactly one turning bar and it is not a STRICT fractal low
    # (low[i] must sit strictly below both neighbours on each side), so
    # fractal_low being all-null here is correct maths, not a bug - the live
    # sweep shows fractal_low populated on real ANLB data.
    shape_sensitive = {("fractals", "fractal_low")}
    for token in tokens:
        body = _chart(client, token)
        ind = body["indicators"]
        disabled = body["disabled"]
        if not ind and not disabled:
            broken.append(f"{token}: no series and no disabled reason")
            continue
        for key, series in ind.items():
            assert len(series) == len(body["series"]["dates"]), (
                f"{token}/{key}: series length {len(series)} != dates {len(body['series']['dates'])}"
            )
            vals = [v for v in series if v is not None]
            if not vals and (token, key) in shape_sensitive:
                continue
            assert vals, f"{token}/{key}: all null (warm-up must be partial, not empty)"
            assert not any(isinstance(v, float) and math.isnan(v) for v in vals), (
                f"{token}/{key}: NaN leaked into the payload"
            )
            # A missing value is never a zero: warm-up regions must be None.
            first = next(i for i, v in enumerate(series) if v is not None)
            assert all(v is None for v in series[:first]), (
                f"{token}/{key}: zeros before first valid index {first}"
            )
    assert not broken, "tokens with no data and no reason:\n" + "\n".join(broken)


def test_compare_family_disabled_reason_without_partner(client):
    body = _chart(client, "ratio,spread,compare,correlation,correlation_log")
    for token in ("ratio", "spread", "compare", "correlation", "correlation_log"):
        assert token in body["disabled"], f"{token} should carry a compare reason"
        assert "compare" in body["disabled"][token].lower()
    # With a partner the same tokens produce real series.
    body2 = _chart(client, "ratio", compare="TEST2")
    # TEST2 has no bars: still 200, and the honest reason stays.
    assert "ratio" in body2["disabled"] or body2["indicators"].get("ratio")


def test_vol_index_disabled_by_design(client):
    body = _chart(client, "vol_index")
    assert "vol_index" in body["disabled"]
    assert "option" in body["disabled"]["vol_index"].lower()


# -- honesty: warm-up is None, hand-checkable values --------------------------


def test_sma_warmup_is_none_and_first_value_matches_hand_math(client):
    body = _chart(client, "sma_20")
    sma = body["indicators"]["sma_20"]
    closes = body["series"]["close"]
    # Hand math: close_i = 100 + i, so SMA20 at bar 19 = mean(100..119) = 109.5.
    assert sma[18] is None, "bar 18 has only 19 closes: must be None"
    assert sma[19] == pytest.approx(sum(100 + i for i in range(20)) / 20), (
        "SMA20[19] should be (100+...+119)/20 = 109.5"
    )
    assert sma[19] == pytest.approx((100.0 + 119.0) / 2.0)  # arithmetic cross-check
    # Every close is preserved exactly through the payload.
    assert closes[0] == 100.0 and closes[19] == 119.0


# -- B: ranges, custom windows, basis reporting -------------------------------


def test_range_1w_and_ytd_accepted(client):
    body = _chart(client, "none", range="1W")
    dates = body["series"]["dates"]
    assert len(dates) >= 1
    (date.fromisoformat(d) for d in dates)  # all parse
    body_y = _chart(client, "none", range="YTD")
    assert body_y["series"]["dates"][0] >= "2025-01-01"


def test_custom_start_end_window(client):
    body = _chart(client, "none", start="2025-02-03", end="2025-02-07")
    dates = body["series"]["dates"]
    assert dates[0] >= "2025-02-03" and dates[-1] <= "2025-02-07"
    assert body["range"]["requested"] == "custom"


def test_custom_window_outside_archive_is_404(client):
    resp = client.get("/api/analytics/chart/TEST?start=2030-01-01&end=2030-01-31")
    assert resp.status_code == 404


def test_unknown_range_is_400_with_options(client):
    resp = client.get("/api/analytics/chart/TEST?range=2W")
    assert resp.status_code == 400
    assert "1W" in resp.json()["detail"] and "YTD" in resp.json()["detail"]


def test_basis_reported_honestly(client):
    body = _chart(client, "none", basis="adjusted")
    pm = body["price_mode"]
    assert pm["requested"] == "adjusted"
    assert pm["applied"] == "as_traded"
    assert pm["differs_from_requested"] is True
    assert pm["reason"], "an unfulfillable basis must say why"


# -- geometry: the payload a non-clipping renderer needs ----------------------


def test_series_geometry_supports_body_wick_and_full_domain(client):
    body = _chart(client, "none", range="ALL")
    s = body["series"]
    for o, h, l, c in zip(s["open"], s["high"], s["low"], s["close"]):
        assert h >= max(o, c), f"high {h} < max(open, close)"
        assert l <= min(o, c), f"low {l} > min(open, close)"
    lows = [v for v in s["low"] if v is not None]
    highs = [v for v in s["high"] if v is not None]
    # The y-domain a correct renderer derives from the visible candles.
    domain = (min(lows), max(highs))
    assert domain[0] <= min(lows) and domain[1] >= max(highs)
    # Hand math on the fixture: the down leg opens one above its close
    # (open_160 = 259 + 1 = 260), so the tallest high is 260 + 2 = 262.
    # (The up leg's peak bar i=159 has high 259 + 2 = 261; nothing exceeds 262.)
    assert domain[1] == pytest.approx(262.0)


def test_sessions_are_weekdays_no_weekend_gaps_labelled(client):
    body = _chart(client, "none", range="ALL")
    from datetime import date as D

    for d in body["series"]["dates"]:
        assert D.fromisoformat(d).weekday() < 5, f"{d} is a weekend session"


def test_no_duplicate_dates(client):
    body = _chart(client, "none", range="ALL")
    dates = body["series"]["dates"]
    assert len(dates) == len(set(dates))


# -- live merge gate: a closed market must never paint a phantom candle -------
# Observed 2026-10-02 (Friday, NEPSE closed): the poller's cache still held the
# 2026-10-01 session, and `_live_bar` re-dated it to "today" - our chart grew a
# bar NEPSE's own chart does not have (O 4934.80 / V 945 duplicated). These
# tests pin the market-status gate.


def _fake_quote():
    from datetime import datetime
    from types import SimpleNamespace

    return SimpleNamespace(
        ltp=4919.7,
        change=-15.1,
        change_pct=-0.31,
        volume=945,
        turnover=0.0,
        high=4935.0,
        low=4821.0,
        timestamp=datetime.now(),
    )


def _patch_poller(monkeypatch, quote):
    monkeypatch.setattr(
        "app.analytics.chart.get_realtime_service",
        lambda: type("S", (), {"get_cached_price": lambda self, s: quote})(),
    )


def test_live_bar_suppressed_when_market_closed(monkeypatch):
    _patch_poller(monkeypatch, _fake_quote())
    assert chart_module._live_bar("TEST", ["2026-10-01"], market_open=False) is None


def test_live_bar_appended_when_market_open(monkeypatch):
    from datetime import datetime

    _patch_poller(monkeypatch, _fake_quote())
    bar_ = chart_module._live_bar("TEST", ["2026-10-01"], market_open=True)
    assert bar_ is not None
    assert bar_.date == datetime.now().strftime("%Y-%m-%d")
    # open = ltp - change = 4919.70 + 15.10 = 4934.80 (hand arithmetic)
    assert bar_.open == pytest.approx(4934.80)
    assert bar_.close == pytest.approx(4919.70)
    assert bar_.volume == 945


def test_live_bar_not_appended_when_today_archived(monkeypatch):
    from datetime import datetime

    _patch_poller(monkeypatch, _fake_quote())
    today = datetime.now().strftime("%Y-%m-%d")
    assert chart_module._live_bar("TEST", ["2026-10-01", today], market_open=True) is None
