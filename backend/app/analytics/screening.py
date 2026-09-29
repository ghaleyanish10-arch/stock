"""Per-symbol screening metrics over the local archive.

One pass over `daily_bars` produces every number the screener, the treemap and
the company page need. They are computed in one place so the screener table,
the treemap tiles, the chart's right-hand panel and any CSV export can never
disagree with each other.

The honesty rules of the rest of the app apply without exception:

* A metric that cannot be computed is `None`, never `0`.
* `None` always travels with a reason, so the UI can say *why* instead of
  printing a bare dash.
* Look-backs are **calendar** based, not "N trading sessions". A user asking for
  1Y means a year, and NEPSE runs ~228 sessions a year, so counting sessions
  would quietly give them 10 months of data labelled as a year. When the archive
  does not reach far enough back, the metric is `None` with
  ``reason="needs more history"`` and the UI states the covered window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Iterable, Optional, Sequence

from app.analytics.indicators import Bar, rsi, vwap

#: Selector value -> calendar days. `None` means "today only" (no look-back).
PERIOD_DAYS: dict[str, Optional[int]] = {
    "1D": None,
    "1W": 7,
    "1M": 31,
    "3M": 92,
    "6M": 183,
    "1Y": 366,
    "YTD": None,  # handled specially: back to 1 January
}

PERIOD_LABELS: dict[str, str] = {
    "1D": "Today",
    "1W": "1 week",
    "1M": "1 month",
    "3M": "3 months",
    "6M": "6 months",
    "1Y": "1 year",
    "YTD": "Year to date",
}

#: How the treemap sizes its tiles.
SIZE_METRICS = ("market_cap", "volume", "turnover")

NOT_ENOUGH_HISTORY = "Needs more history than the archive holds."


@dataclass(slots=True)
class SymbolSeries:
    """One symbol's bars, oldest first, as fetched."""

    symbol: str
    name: Optional[str] = None
    sector: Optional[str] = None
    listed_shares: Optional[int] = None
    dates: list[str] = field(default_factory=list)
    open: list[Optional[float]] = field(default_factory=list)
    high: list[Optional[float]] = field(default_factory=list)
    low: list[Optional[float]] = field(default_factory=list)
    close: list[Optional[float]] = field(default_factory=list)
    prev_close: list[Optional[float]] = field(default_factory=list)
    volume: list[Optional[float]] = field(default_factory=list)
    turnover: list[Optional[float]] = field(default_factory=list)
    trades: list[Optional[float]] = field(default_factory=list)
    market_cap: list[Optional[float]] = field(default_factory=list)
    high_52w: list[Optional[float]] = field(default_factory=list)
    low_52w: list[Optional[float]] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.dates)

    def bars(self) -> list[Bar]:
        return [
            Bar(date=d, open=o, high=h, low=l, close=c, volume=v)
            for d, o, h, l, c, v in zip(
                self.dates, self.open, self.high, self.low, self.close, self.volume
            )
        ]

    def index_on_or_after(self, target: str) -> Optional[int]:
        """First index whose date is >= `target`, or None if the series is shorter."""
        for i, d in enumerate(self.dates):
            if d >= target:
                return i
        return None

    def index_on_or_before(self, target: str) -> Optional[int]:
        """Last index whose date is <= `target`, or None."""
        found: Optional[int] = None
        for i, d in enumerate(self.dates):
            if d <= target:
                found = i
            else:
                break
        return found


def _last_present(values: Sequence[Optional[float]]) -> Optional[float]:
    """Most recent non-None value, or None.

    Used for metrics where "the latest known value" is the right answer even
    if the newest bar is missing a field - e.g. a market cap carried from the
    last enriched bar.
    """
    for v in reversed(values):
        if v is not None:
            return v
    return None


def period_base_index(series: SymbolSeries, period: str) -> tuple[Optional[int], Optional[str]]:
    """Index of the bar a `period` return is measured from.

    Returns `(index, reason_if_missing)`.
    """
    if period not in PERIOD_DAYS:
        raise ValueError(f"unknown period {period!r}; expected one of {sorted(PERIOD_DAYS)}")
    if not series.dates:
        return None, "No archived bars."

    as_of = series.dates[-1]
    as_of_date = date.fromisoformat(as_of)
    if period == "1D":
        # Measured against the previous session's close, not itself.
        prev = series.index_on_or_before(
            (as_of_date - timedelta(days=1)).isoformat()
        )
        return (prev, None) if prev is not None else (None, NOT_ENOUGH_HISTORY)
    if period == "YTD":
        start = date(as_of_date.year, 1, 1).isoformat()
    else:
        days = PERIOD_DAYS[period]
        assert days is not None
        start = (as_of_date - timedelta(days=days)).isoformat()

    idx = series.index_on_or_after(start)
    if idx is None:
        return None, NOT_ENOUGH_HISTORY
    if series.dates[0] > start:
        # The oldest bar we hold is *after* the window opened, so the return
        # spans a shorter stretch than asked for. Say so instead of passing a
        # short window off as a full period. Note the comparison is on dates,
        # not on `idx == 0`: a series whose first bar lands exactly on the
        # window start is fully covered, and refusing it would penalise the
        # symbol for having been listed a day early.
        return None, (
            f"Archive starts {series.dates[0]}, inside the {PERIOD_LABELS[period]} window."
        )
    return idx, None


def period_flow(
    series: SymbolSeries, attr: str, period: str
) -> tuple[Optional[float], Optional[str]]:
    """Total `volume` or `turnover` traded over the `period` window.

    The treemap offers volume and turnover as *period* sizing metrics, so a
    single day's volume would mislabel a 1Y map. This reuses
    `period_base_index` so the sizing window is exactly the window the return is
    measured over: same base bar, same "archive starts inside the window" rule,
    same 1D special case.

    Returns `(value, reason_if_missing)`.
    """
    values = getattr(series, attr)
    idx, reason = period_base_index(series, period)
    if idx is None:
        return None, reason
    # `idx` is the bar the return is measured *from*: its close is the
    # starting price, so the trading that produced it happened before the
    # window opened. The window is therefore the sessions after it, which also
    # makes 1D mean exactly one day of trading (the latest session) rather
    # than two.
    window = values[idx + 1 :]
    if not any(v is not None for v in window):
        return None, f"No {attr} reported in the {PERIOD_LABELS[period]} window."
    # Skip None cells rather than treating them as zero: a day NEPSE did not
    # report is unknown, not a session with no trading.
    return float(sum(v for v in window if v is not None)), None


def period_return(series: SymbolSeries, period: str) -> tuple[Optional[float], Optional[str]]:
    """Percentage change over `period`. `(value, reason_if_missing)`."""
    idx, reason = period_base_index(series, period)
    if idx is None:
        return None, reason
    base = series.close[idx]
    last = _last_present(series.close)
    if base is None or last is None:
        return None, "Missing a close at one end of the window."
    if base == 0:
        return None, "Previous close was zero; a percentage change is undefined."
    return (last - base) / base * 100.0, None


def _sum(values: Sequence[Optional[float]], start: int) -> Optional[float]:
    total = 0.0
    seen = False
    for v in values[start:]:
        if v is not None:
            total += float(v)
            seen = True
    return total if seen else None


def rolling_vwap(series: SymbolSeries, lookback_days: int) -> Optional[float]:
    """VWAP over the trailing `lookback_days` calendar days."""
    if not series.dates:
        return None
    start = (date.fromisoformat(series.dates[-1]) - timedelta(days=lookback_days)).isoformat()
    idx = series.index_on_or_after(start)
    if idx is None:
        return None
    window = series.bars()[idx:]
    if not window:
        return None
    return vwap(window)


@dataclass(slots=True)
class SymbolMetrics:
    """Every derived number for one symbol, each with its own reason when absent."""

    symbol: str
    name: Optional[str]
    sector: Optional[str]
    as_of: str
    sessions: int

    ltp: Optional[float] = None
    prev_close: Optional[float] = None
    change: Optional[float] = None
    change_pct: Optional[float] = None

    market_cap: Optional[float] = None
    listed_shares: Optional[int] = None

    volume: Optional[float] = None
    turnover: Optional[float] = None
    trades: Optional[float] = None

    day_high: Optional[float] = None
    day_low: Optional[float] = None

    ret_5d: Optional[float] = None
    ret_1m: Optional[float] = None
    ret_3m: Optional[float] = None
    ret_6m: Optional[float] = None
    ret_1y: Optional[float] = None
    ret_ytd: Optional[float] = None

    vwap_180d: Optional[float] = None
    rsi_14: Optional[float] = None

    high_52w: Optional[float] = None
    low_52w: Optional[float] = None

    #: metric key -> why it is None. Empty keys are not serialised.
    missing: dict[str, str] = field(default_factory=dict)

    #: period -> total volume traded in that window. Same for `turnover_flow`.
    volume_flow: dict[str, Optional[float]] = field(default_factory=dict)
    turnover_flow: dict[str, Optional[float]] = field(default_factory=dict)

    #: period -> why the flow is None, where it is.
    flow_missing: dict[str, str] = field(default_factory=dict)

    def period_return(self, period: str) -> Optional[float]:
        return {
            "1D": self.change_pct,
            "1W": self.ret_5d,
            "1M": self.ret_1m,
            "3M": self.ret_3m,
            "6M": self.ret_6m,
            "1Y": self.ret_1y,
            "YTD": self.ret_ytd,
        }[period]

    def size_value(self, metric: str, period: Optional[str] = None) -> Optional[float]:
        """Value to draw a tile by.

        `market_cap` is a point-in-time figure, so the period is ignored.
        `volume` and `turnover` are flows: with a period they sum the window,
        without one they fall back to the latest session's value.
        """
        if metric == "market_cap":
            return self.market_cap
        if metric == "volume":
            if period is not None:
                return self.volume_flow.get(period)
            return self.volume
        if metric == "turnover":
            if period is not None:
                return self.turnover_flow.get(period)
            return self.turnover
        raise ValueError(f"unknown size metric {metric!r}")

    def size_reason(self, metric: str, period: Optional[str] = None) -> Optional[str]:
        """Why the size value is None, when it is."""
        if self.size_value(metric, period) is not None:
            return None
        if metric in ("volume", "turnover") and period is not None:
            return self.flow_missing.get(f"{metric}:{period}")
        return self.missing.get(metric)

    def to_dict(self) -> dict[str, Any]:
        """Serialise, dropping the `missing` map keys that resolved.

        Every numeric key is always present so the frontend can bind to a
        stable shape; a `None` is accompanied by its reason in `reasons`.
        """
        reasons = dict(self.missing)
        return {
            "symbol": self.symbol,
            "name": self.name,
            "sector": self.sector,
            "as_of": self.as_of,
            "sessions": self.sessions,
            "ltp": self.ltp,
            "prev_close": self.prev_close,
            "change": self.change,
            "change_pct": self.change_pct,
            "market_cap": self.market_cap,
            "listed_shares": self.listed_shares,
            "volume": self.volume,
            "turnover": self.turnover,
            "trades": self.trades,
            "day_high": self.day_high,
            "day_low": self.day_low,
            "ret_5d": self.ret_5d,
            "ret_1m": self.ret_1m,
            "ret_3m": self.ret_3m,
            "ret_6m": self.ret_6m,
            "ret_1y": self.ret_1y,
            "ret_ytd": self.ret_ytd,
            "vwap_180d": self.vwap_180d,
            "rsi_14": self.rsi_14,
            "high_52w": self.high_52w,
            "low_52w": self.low_52w,
            "reasons": reasons,
        }


def compute_metrics(series: SymbolSeries, vwap_days: int = 180) -> SymbolMetrics:
    """Derive the full metric set for one symbol."""
    n = len(series)
    metrics = SymbolMetrics(
        symbol=series.symbol,
        name=series.name,
        sector=series.sector,
        as_of=series.dates[-1] if series.dates else "",
        sessions=n,
        listed_shares=series.listed_shares,
    )
    if n == 0:
        metrics.missing = {
            k: "No archived bars for this symbol yet."
            for k in (
                "ltp", "change", "change_pct", "market_cap", "volume", "turnover",
                "day_high", "day_low", "ret_5d", "ret_1m", "ret_3m", "ret_6m",
                "ret_1y", "ret_ytd", "vwap_180d", "rsi_14", "high_52w", "low_52w",
            )
        }
        return metrics

    last_close = _last_present(series.close)
    metrics.ltp = last_close
    metrics.day_high = _last_present(series.high)
    metrics.day_low = _last_present(series.low)
    metrics.volume = _last_present(series.volume)
    metrics.turnover = _last_present(series.turnover)
    metrics.trades = _last_present(series.trades)
    metrics.high_52w = _last_present(series.high_52w)
    metrics.low_52w = _last_present(series.low_52w)

    # Change is against the previous *close*, preferring the stored prev_close
    # and falling back to the prior bar so a missing field does not blank it.
    prev = _last_present(series.prev_close[:-1]) or _last_present(series.prev_close)
    if prev is None and n >= 2:
        prev = series.close[n - 2]
    metrics.prev_close = prev
    if last_close is not None and prev is not None:
        metrics.change = last_close - prev
        metrics.change_pct = (metrics.change / prev * 100.0) if prev != 0 else None
        if prev == 0:
            metrics.missing["change_pct"] = "Previous close was zero; undefined."

    # Market cap is *always* listed shares x LTP here, even when the bar carries
    # a stored figure, because `bar_from_row` froze the share count known at
    # ingest time. After a bonus or split that stored value is computed from a
    # share count NEPSE no longer reports, so it disagrees with the current
    # listing and with the LTP printed beside it. Recomputing keeps one
    # definition across the map, screener and company page.
    if series.listed_shares and last_close:
        metrics.market_cap = float(series.listed_shares) * float(last_close)
    else:
        metrics.missing["market_cap"] = (
            "NEPSE has not published this security's listed shares, so "
            "market cap (listed shares x LTP) cannot be derived."
        )

    for period, attr in (
        ("1W", "ret_5d"),
        ("1M", "ret_1m"),
        ("3M", "ret_3m"),
        ("6M", "ret_6m"),
        ("1Y", "ret_1y"),
        ("YTD", "ret_ytd"),
    ):
        value, reason = period_return(series, period)
        setattr(metrics, attr, value)
        if value is None and reason:
            metrics.missing[attr] = reason

    # Window totals for the flow-based treemap sizes. Computed for every period
    # including 1D, which is a single session.
    for period in PERIOD_DAYS:
        for attr, store in (("volume", metrics.volume_flow), ("turnover", metrics.turnover_flow)):
            value, reason = period_flow(series, attr, period)
            store[period] = value
            if value is None and reason:
                metrics.flow_missing[f"{attr}:{period}"] = reason

    metrics.vwap_180d = rolling_vwap(series, vwap_days)
    if metrics.vwap_180d is None:
        metrics.missing["vwap_180d"] = (
            f"Fewer than {vwap_days} days of volume-bearing bars are archived."
        )

    closes = list(series.close)
    rsi_series = rsi(closes, 14)
    metrics.rsi_14 = rsi_series[-1] if rsi_series else None
    if metrics.rsi_14 is None:
        metrics.missing["rsi_14"] = "Fewer than 15 closes are archived."

    if metrics.high_52w is None:
        metrics.missing["high_52w"] = "NEPSE did not publish a 52-week high."
    if metrics.low_52w is None:
        metrics.missing["low_52w"] = "NEPSE did not publish a 52-week low."

    return metrics


def build_series(rows: Iterable[Any], securities: dict[str, Any]) -> dict[str, SymbolSeries]:
    """Group `DailyBar` rows into per-symbol series, oldest first.

    `securities` maps symbol -> Security row, used for name, sector and listed
    shares. A symbol with no Security row still gets a series; its metadata
    simply stays `None` rather than being invented.
    """
    grouped: dict[str, list[Any]] = {}
    for row in rows:
        grouped.setdefault(row.symbol, []).append(row)

    out: dict[str, SymbolSeries] = {}
    for symbol, bar_rows in grouped.items():
        bar_rows.sort(key=lambda r: r.business_date)
        sec = securities.get(symbol)
        series = SymbolSeries(
            symbol=symbol,
            name=getattr(sec, "name", None),
            sector=getattr(sec, "sector_code", None),
            listed_shares=getattr(sec, "listed_shares", None),
        )
        for r in bar_rows:
            series.dates.append(r.business_date)
            series.open.append(r.open)
            series.high.append(r.high)
            series.low.append(r.low)
            series.close.append(r.close)
            series.prev_close.append(r.prev_close)
            series.volume.append(float(r.volume) if r.volume is not None else None)
            series.turnover.append(r.turnover)
            series.trades.append(float(r.trades) if r.trades is not None else None)
            series.market_cap.append(r.market_cap)
            series.high_52w.append(r.high_52w)
            series.low_52w.append(r.low_52w)
        out[symbol] = series
    return out


def treemap_tiles(
    metrics: list[SymbolMetrics], period: str, size: str
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Tiles for the treemap, plus why any symbol was dropped.

    A symbol with no value for the chosen size metric cannot be drawn, but it is
    reported in `skipped` rather than silently dropped - a market-cap treemap
    that quietly omits every unenriched security would look complete and be
    misleading.
    """
    tiles: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    change_key = {
        "1D": "change_pct",
        "1W": "ret_5d",
        "1M": "ret_1m",
        "3M": "ret_3m",
        "6M": "ret_6m",
        "1Y": "ret_1y",
        "YTD": "ret_ytd",
    }[period]
    for m in metrics:
        change = m.period_return(period)
        size_value = m.size_value(size, period)
        if size_value is None or size_value <= 0 or change is None:
            if size_value is None or size_value <= 0:
                reason = m.size_reason(size, period) or (
                    f"No {size} value for {PERIOD_LABELS[period].lower()}."
                )
            else:
                reason = m.missing.get(change_key) or (
                    f"No {PERIOD_LABELS[period].lower()} return for this symbol."
                )
            skipped.append({"symbol": m.symbol, "reason": reason})
            continue
        tiles.append(
            {
                "symbol": m.symbol,
                "name": m.name,
                "sector": m.sector,
                "size": size_value,
                "change_pct": change,
                "ltp": m.ltp,
                "market_cap": m.market_cap,
            }
        )
    tiles.sort(key=lambda t: t["size"], reverse=True)
    return tiles, skipped


def sector_breakdown(
    metrics: list[SymbolMetrics], period: str, size: str
) -> list[dict[str, Any]]:
    """Aggregate the treemap's chosen size metric by sector, for the pie view."""
    buckets: dict[str, dict[str, Any]] = {}
    for m in metrics:
        change = m.period_return(period)
        value = m.size_value(size, period)
        if value is None or value <= 0 or change is None:
            continue
        key = m.sector or "Unknown"
        bucket = buckets.setdefault(
            key,
            {"sector": key, "size": 0.0, "symbols": 0, "change_weighted": 0.0},
        )
        bucket["size"] += float(value)
        bucket["symbols"] += 1
        bucket["change_weighted"] += float(change) * float(value)
    out = []
    for b in buckets.values():
        b["change_pct"] = (b["change_weighted"] / b["size"]) if b["size"] else None
        out.append(b)
    out.sort(key=lambda b: b["size"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# Screener
# ---------------------------------------------------------------------------

#: Every column the screener can sort or filter on.
SCREENER_COLUMNS: dict[str, str] = {
    "symbol": "Symbol",
    "sector": "Sector",
    "ltp": "LTP",
    "change": "Change",
    "change_pct": "Change %",
    "market_cap": "Market cap",
    "volume": "Volume",
    "turnover": "Turnover",
    "ret_5d": "5D",
    "ret_1m": "1M",
    "ret_3m": "3M",
    "ret_6m": "6M",
    "ret_1y": "1Y",
    "ret_ytd": "YTD",
    "vwap_180d": "180D VWAP",
    "rsi_14": "RSI (14)",
    "day_high": "Day high",
    "day_low": "Day low",
}

#: Text columns: sortable and filterable, but never comparable as numbers.
SCREENER_TEXT = frozenset({"symbol", "sector"})

#: Numeric fields eligible for a min/max range filter.
SCREENER_NUMERIC = {
    k for k, v in SCREENER_COLUMNS.items() if k not in SCREENER_TEXT
}


@dataclass(slots=True)
class ScreenerFilter:
    """One column's constraint.

    `above_vwap` and `below_vwap` are separate booleans rather than a numeric
    comparison because "price above its 180-day VWAP" is the question traders
    actually ask, and expressing it as a range would need the VWAP per row.
    """

    field: str
    min: Optional[float] = None
    max: Optional[float] = None
    above_vwap: Optional[bool] = None


@dataclass(slots=True)
class ScreenerRejection:
    """Why a row was filtered out, counted per column.

    Surfaced in the response so the UI can say "12 rows dropped by the market
    cap filter" instead of leaving the user to guess.
    """

    field: str
    count: int


def apply_screener_filters(
    metrics: list[SymbolMetrics], filters: list[ScreenerFilter]
) -> tuple[list[SymbolMetrics], list[ScreenerRejection], list[dict[str, Any]]]:
    """Filter rows, returning `(kept, rejected_by_column, null_cells)`.

    `null_cells` records which rows dropped out because a filter needed a value
    they do not have, so a thin result can be explained rather than looking like
    the market has almost no candidates.

    A `None` never satisfies a min/max bound in either direction: a symbol with
    no market cap is *not* "under 1 billion", it is unknown. Otherwise a max
    filter would quietly sweep every missing value into the result set.
    """
    kept = list(metrics)
    rejections: list[ScreenerRejection] = []
    null_drops: list[dict[str, Any]] = []

    for flt in filters:
        survivors: list[SymbolMetrics] = []
        dropped = 0
        dropped_unknown = 0
        for m in kept:
            if flt.field == "sector":
                if flt.min is not None and m.sector != str(flt.min):
                    dropped += 1
                    continue
                survivors.append(m)
                continue

            value = getattr(m, flt.field, None)
            if value is None:
                dropped_unknown += 1
                continue
            if flt.min is not None and float(value) < flt.min:
                dropped += 1
                continue
            if flt.max is not None and float(value) > flt.max:
                dropped += 1
                continue
            if flt.above_vwap is not None:
                if m.vwap_180d is None:
                    dropped_unknown += 1
                    continue
                above = float(value) > float(m.vwap_180d)
                if above != flt.above_vwap:
                    dropped += 1
                    continue
            survivors.append(m)

        if dropped:
            rejections.append(ScreenerRejection(flt.field, dropped))
        if dropped_unknown:
            null_drops.append(
                {
                    "field": flt.field,
                    "count": dropped_unknown,
                    "reason": f"{dropped_unknown} symbol(s) have no {flt.field} value "
                    f"in the archive, so they cannot be tested against this filter.",
                }
            )
        kept = survivors

    return kept, rejections, null_drops


def sort_screener(
    metrics: list[SymbolMetrics], field: str, descending: bool = True
) -> list[SymbolMetrics]:
    """Sort by a column; rows missing it sink to the bottom either way.

    They cannot be ordered among themselves meaningfully, and putting them last
    keeps them from disappearing off the top of a descending sort.
    """
    if field not in SCREENER_COLUMNS:
        raise ValueError(f"unknown screener field {field!r}")
    present = [m for m in metrics if getattr(m, field, None) is not None]
    absent = [m for m in metrics if getattr(m, field, None) is None]
    if field in SCREENER_TEXT:
        # Symbol and sector are labels, not measures: they sort
        # alphabetically, and case is folded so "commercial" and
        # "Commercial Bank" land next to each other rather than in
        # separate upper/lower blocks.
        key = lambda m: str(getattr(m, field)).casefold()  # noqa: E731
    else:
        key = lambda m: float(getattr(m, field))  # type: ignore[arg-type]  # noqa: E731
    present.sort(key=key, reverse=descending)
    # The bucket of rows missing this field always reads in symbol order,
    # whatever the sort direction, so a descending sort cannot shuffle the
    # unknowns unpredictably between requests.
    absent.sort(key=lambda m: m.symbol)
    return present + absent
