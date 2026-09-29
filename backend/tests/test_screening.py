"""Tests for the shared screener/visualisation engine.

The values here are chosen so an error is visible rather than plausible:
a 5-day window has a known base bar, a bonus issue changes the share count, and
a partially reported month distinguishes "sum what we have" from "treat the
gap as zero".
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.analytics.screening import (
    SCREENER_COLUMNS,
    SymbolMetrics,
    SymbolSeries,
    compute_metrics,
    period_base_index,
    period_flow,
    sector_breakdown,
    sort_screener,
    treemap_tiles,
)


def sessions_after_base(series: SymbolSeries, period: str) -> int:
    """How many sessions the period window covers, per the shared base rule.

    The expected flow is derived from the same helper the implementation uses,
    so a change to the window definition moves both sides together while the
    test still fails if the *summing* is wrong.
    """
    idx, _ = period_base_index(series, period)
    assert idx is not None
    return len(series) - idx - 1


def make_series(
    symbol: str = "TEST",
    *,
    start: str = "2026-01-01",
    n: int = 200,
    close_from: float = 100.0,
    step: float = 1.0,
    volume: float = 1000.0,
    turnover: float = 100_000.0,
    listed_shares: int | None = 1_000_000,
    sector: str = "Commercial Banks",
    name: str = "Test Bank Ltd",
    market_cap: float | None = None,
) -> SymbolSeries:
    """A business-day series with known, easily checked arithmetic."""
    d = date.fromisoformat(start)
    dates: list[str] = []
    closes: list[float | None] = []
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d.isoformat())
            closes.append(close_from + step * len(dates))
        d += timedelta(days=1)
    return SymbolSeries(
        symbol=symbol,
        name=name,
        sector=sector,
        dates=dates,
        open=[c for c in closes],
        high=[c + 2 for c in closes],
        low=[c - 2 for c in closes],
        close=closes,
        prev_close=[None] + [c for c in closes[:-1]],
        volume=[volume] * n,
        turnover=[turnover] * n,
        trades=[10] * n,
        high_52w=[None] * n,
        low_52w=[None] * n,
        market_cap=[market_cap] * n,
        listed_shares=listed_shares,
    )


class TestMarketCapDefinition:
    def test_is_listed_shares_times_ltp(self) -> None:
        s = make_series(n=10, close_from=100.0, step=0.0, listed_shares=1_000_000)
        m = compute_metrics(s)
        assert m.ltp == 100.0
        assert m.market_cap == 100_000_000.0

    def test_recomputed_when_stored_cap_used_a_stale_share_count(self) -> None:
        """A stored cap from a pre-bonus share count must lose to the formula.

        The bar carries 100,000,000 (1M shares x 100) but the security now has
        2M shares outstanding. Reporting the stored figure would show a market
        cap half the true one, next to the same LTP.
        """
        s = make_series(
            n=10, close_from=100.0, step=0.0, listed_shares=2_000_000, market_cap=100_000_000.0
        )
        m = compute_metrics(s)
        assert m.market_cap == 200_000_000.0

    def test_missing_listed_shares_stays_missing_with_a_reason(self) -> None:
        s = make_series(n=10, listed_shares=None)
        m = compute_metrics(s)
        assert m.market_cap is None
        assert "listed shares" in m.missing["market_cap"]


class TestPeriodFlow:
    def test_one_day_volume_is_a_single_session(self) -> None:
        s = make_series(n=30, volume=500.0)
        value, reason = period_flow(s, "volume", "1D")
        assert value == 500.0
        assert reason is None
        # 1D must not quietly mean "the base bar and today".
        assert sessions_after_base(s, "1D") == 1

    def test_flow_sums_the_window_not_the_latest_bar(self) -> None:
        """The treemap sizes 1W by volume traded *in the week*.

        Using the latest bar instead would make a 1W map and a 1D map identical
        whenever only volume sizing is chosen.
        """
        s = make_series(n=30, volume=500.0)
        m = compute_metrics(s)
        assert m.volume == 500.0  # latest session
        assert m.volume_flow["1D"] == 500.0
        week = m.volume_flow["1W"]
        assert week is not None
        assert sessions_after_base(s, "1W") > 1
        assert week == sessions_after_base(s, "1W") * 500.0

    def test_turnover_sums_too(self) -> None:
        s = make_series(n=30, turnover=1_000.0)
        m = compute_metrics(s)
        assert m.turnover_flow["1W"] == sessions_after_base(s, "1W") * 1_000.0

    def test_gap_is_skipped_not_counted_as_zero(self) -> None:
        """A session NEPSE did not report is unknown, not a zero-volume day."""
        s = make_series(n=30, volume=500.0)
        idx, _ = period_base_index(s, "1W")
        assert idx is not None
        s.volume[idx + 1] = None  # one unreported session inside the window
        value, _ = period_flow(s, "volume", "1W")
        assert value == (sessions_after_base(s, "1W") - 1) * 500.0

    def test_no_data_in_window_is_missing_with_a_reason(self) -> None:
        s = make_series(n=30, volume=500.0)
        s.volume = [None] * 30
        value, reason = period_flow(s, "volume", "1W")
        assert value is None
        assert reason is not None and "1W" in reason or "week" in reason.lower()

    def test_size_value_sums_when_period_given(self) -> None:
        s = make_series(n=30, volume=500.0)
        m = compute_metrics(s)
        assert m.size_value("volume") == 500.0  # latest, no period
        assert m.size_value("volume", "1W") == sessions_after_base(s, "1W") * 500.0
        # Market cap is a point-in-time figure, so the period is ignored.
        assert m.size_value("market_cap", "1W") == m.market_cap


class TestTreemapAndSectors:
    def test_tiles_use_period_sized_volume(self) -> None:
        a = make_series("AAA", n=30, volume=500.0, step=1.0)
        b = make_series("BBB", n=30, volume=2500.0, step=1.0)
        metrics = [compute_metrics(a), compute_metrics(b)]
        tiles, skipped = treemap_tiles(metrics, "1D", "volume")
        # 1D: both sized by one session, so the 5x volume ratio holds.
        sizes = {t["symbol"]: t["size"] for t in tiles}
        assert sizes["AAA"] == 500.0 and sizes["BBB"] == 2500.0
        assert skipped == []

        tiles_week, _ = treemap_tiles(metrics, "1W", "volume")
        week_sizes = {t["symbol"]: t["size"] for t in tiles_week}
        # The 1W tiles must exceed the 1D ones by the window length, or the
        # "period" selector is cosmetic for flow sizing.
        assert week_sizes["AAA"] == sizes["AAA"] * sessions_after_base(a, "1W")
        assert week_sizes["BBB"] == sizes["BBB"] * sessions_after_base(b, "1W")

    def test_symbol_without_size_is_skipped_with_reason(self) -> None:
        a = make_series("AAA", n=30, listed_shares=None)
        tiles, skipped = treemap_tiles([compute_metrics(a)], "1D", "market_cap")
        assert tiles == []
        assert len(skipped) == 1
        assert "listed shares" in skipped[0]["reason"]

    def test_sector_totals_use_period_sized_flows(self) -> None:
        a = make_series("AAA", n=30, sector="Banks", volume=500.0)
        b = make_series("BBB", n=30, sector="Banks", volume=500.0)
        metrics = [compute_metrics(a), compute_metrics(b)]
        rows = sector_breakdown(metrics, "1W", "volume")
        assert len(rows) == 1
        assert rows[0]["symbols"] == 2
        assert rows[0]["size"] == 2 * sessions_after_base(a, "1W") * 500.0


class TestPeriodWindowBoundaries:
    def test_series_starting_exactly_on_the_window_start_is_usable(self) -> None:
        """A base bar landing on the boundary is full coverage, not short.

        The old guard refused any series whose base index was 0, which
        penalised a symbol for having been archived one day early.
        """
        # Six sessions from a Monday to the next Monday span exactly 7 days,
        # so the 1W window start is the first bar itself.
        s = make_series(start="2026-03-02", n=6, step=0.0)  # Monday
        as_of = date.fromisoformat(s.dates[-1])
        start = (as_of - timedelta(days=7)).isoformat()
        assert s.dates[0] == start
        idx, reason = period_base_index(s, "1W")
        assert idx == 0
        assert reason is None

    def test_series_starting_inside_the_window_is_refused(self) -> None:
        s = make_series(start="2026-01-01", n=10, step=0.0)
        idx, reason = period_base_index(s, "1Y")
        assert idx is None
        assert reason is not None and s.dates[0] in reason

    def test_coverage_span_is_gap_between_endpoints_not_inclusive_count(self) -> None:
        """365 days apart is 365 days of return window, not 366.

        A 1Y return needs a base bar 366 days back; an archive spanning
        2025-09-28..2026-09-28 holds 366 dates but its earliest possible base is
        only 365 days back, so 1Y must be reported unavailable.
        """
        from app.analytics.visualize import _coverage_days

        span = _coverage_days(
            {"first": "2025-09-28", "last": "2026-09-28", "sessions": 228}
        )
        assert span == 365
        assert span < 366  # the 1Y window

    def test_empty_coverage_has_no_span(self) -> None:
        from app.analytics.visualize import _coverage_days

        assert _coverage_days({"first": None, "last": None, "sessions": 0}) is None


class TestSorting:
    def _m(self, symbol: str, **kw) -> SymbolMetrics:
        kw.setdefault("sector", "Banks")
        return SymbolMetrics(
            symbol=symbol, name=symbol, as_of="2026-09-28", sessions=10, **kw
        )

    def test_symbol_sorts_alphabetically(self) -> None:
        rows = [self._m("CHCL"), self._m("ADBL"), self._m("NABIL")]
        out = sort_screener(rows, "symbol", descending=False)
        assert [m.symbol for m in out] == ["ADBL", "CHCL", "NABIL"]

    def test_sector_sorts_without_a_numeric_cast(self) -> None:
        """Regression: sector is text, and float("Commercial Banks") raises."""
        rows = [
            self._m("A", sector="Microfinance"),
            self._m("B", sector="Commercial Banks"),
            self._m("C", sector="Hydro Power"),
        ]
        out = sort_screener(rows, "sector", descending=False)
        assert [m.sector for m in out] == ["Commercial Banks", "Hydro Power", "Microfinance"]

    def test_unknown_field_still_raises(self) -> None:
        with pytest.raises(ValueError):
            sort_screener([self._m("A")], "name", descending=True)

    def test_every_column_is_reachable_by_sort(self) -> None:
        for field in SCREENER_COLUMNS:
            rows = [self._m("A"), self._m("B")]
            sort_screener(rows, field, descending=True)
