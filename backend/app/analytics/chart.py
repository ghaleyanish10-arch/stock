"""Chart series endpoint: candles, volume and the indicator suite.

The existing `/indicators/{symbol}` route already computes the maths. This adds
what the chart page needs around it:

* an explicit ADJUSTED / UNADJUSTED mode switch, and
* the right-hand panel's day range, 52-week range, 5-day dots and performance
  grid.

On adjustment: NEPSE publishes no split or bonus ex-dates, so a genuinely
adjusted series cannot be built. Rather than shipping a fake "adjusted" mode that
silently returns the same numbers as unadjusted, the endpoint reports the
requested mode, whether the two differ, and why. When NEPSE later publishes
ex-dates this is the single place that has to change.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.analytics.indicators import (
    accumulation_distribution_line,
    adx,
    aroon,
    alma,
    asi,
    atr,
    average_price,
    accelerator_oscillator,
    chande_kroll_stop,
    chop_zone,
    choppiness,
    ama,
    cmo,
    connors_rsi,
    coppock,
    awesome_oscillator,
    bollinger,
    bollinger_on_valid,
    camarilla_pivots,
    chaikin_money_flow,
    chaikin_oscillator,
    chaikin_volatility,
    cci,
    cumulative_volume_delta,
    balance_of_power,
    correlation,
    correlation_log,
    dema,
    demark_pivots,
    gmma,
    donchian,
    ease_of_movement,
    ema,
    ema_cross,
    ema_on_valid,
    fibonacci_extension,
    fibonacci_fan,
    fibonacci_retracement,
    force_index,
    historical_volatility,
    hma,
    ichimoku,
    keltner,
    klinger_oscillator,
    macd,
    macd_on_valid,
    standard_error,
    standard_error_bands,
    volatility_c2c,
    volatility_ohlc,
    volatility_zero_trend_c2c,
    alligator,
    fisher,
    kst,
    dpo,
    price_oscillator,
    rci,
    relative_volatility_index,
    envelopes,
    mass_index,
    smi_ergodic,
    fractals,
    majority_rule,
    lsma,
    ma_channel,
    ma_cross,
    ma_ema_cross,
    ma_hamming,
    ma_multiple,
    linreg_curve,
    linreg_slope,
    linreg_trend,
    mcginley,
    money_flow_index,
    smma,
    momentum,
    high_low_52w,
    obv,
    pivot_points,
    psar,
    rsi,
    rsi_on_valid,
    sma,
    sma_on_valid,
    stochastic,
    stoch_rsi,
    stdev_series,
    supertrend,
    tema,
    tsi,
    trix,
    ultimate_oscillator,
    volume_price_trend,
    volume_profile,
    trend_strength,
    volume_oscillator,
    vwap_series,
    williams_r,
    zigzag,
    wma,
    rvi,
    Bar,
    woodie_pivots,
    correlation_log,
    ratio,
    spread,
    compare,
    median_price,
    typical_price,
    price_channel,
    force_index,
    technical_ratings,
    roc,
    vwma,
    vortex,
)
from app.realtime.service import get_realtime_service
from app.archive.service import ArchiveService
from app.auth.deps import DbSession
from app.db.models import DailyBar, Security
from app.nepse.registry import get_adapter
from app.nepse.service import NepseService, validate_symbol

router = APIRouter(prefix="/api/analytics", tags=["chart"])

_archive = ArchiveService(get_adapter())
_nepse = NepseService(get_adapter())

#: Calendar look-backs offered as range shortcuts. Availability depends on how
#: far back the local archive reaches, which is reported per range.
RANGE_DAYS: dict[str, int] = {
    "1W": 7,
    "1M": 31,
    "3M": 92,
    "6M": 183,
    "1Y": 366,
    "ALL": 3650,
}

#: Shortcut order as offered on the chart card. YTD is computed from Jan 1 of
#: the latest bar's year rather than a fixed look-back, so it lives in
#: RANGE_ORDER instead of RANGE_DAYS.
RANGE_ORDER: list[str] = ["1W", "1M", "3M", "6M", "YTD", "1Y", "ALL"]


def _want_date(latest: str, range_key: str) -> str:
    """First calendar date a range shortcut covers, measured from `latest`."""
    if range_key == "YTD":
        return date.fromisoformat(latest).replace(month=1, day=1).isoformat()
    return (date.fromisoformat(latest) - timedelta(days=RANGE_DAYS[range_key])).isoformat()

#: Performance grid columns, as (label, calendar days).
PERFORMANCE_GRID: list[tuple[str, int]] = [
    ("1D", 1),
    ("1W", 7),
    ("1M", 31),
    ("3M", 92),
    ("6M", 183),
    ("1Y", 366),
]


def _live_bar(
    sym: str,
    dates: list[str],
    market_open: Optional[bool] = None,
) -> Optional[Bar]:
    """Today's live session as a synthetic bar, from the shared poller cache.

    The nightly ingest only adds a bar after NEPSE publishes the EOD file, so
    between market open and the evening backfill the archived series ends
    yesterday - and every indicator computed on it is a day stale. The
    realtime poller's cache (one upstream NEPSE poll per 30s, fan-out to all
    readers) carries today's LTP/high/low/volume, so we append it as the last
    bar BEFORE computing: every indicator then includes the live session.

    Rules:
    * Only appended when the market is OPEN (`market_open is True`). The
      poller refreshes its cache even on non-trading days, so an ungated
      append re-dates the last session's quote to "today" and paints a
      phantom candle NEPSE's own chart does not have (observed 2026-10-02,
      a Friday, duplicating the 2026-10-01 session as a new bar).
    * `market_open is None` (status unreadable) keeps the pre-gate behaviour
      so direct callers/tests of the quote plumbing stay meaningful; the
      endpoint always passes a concrete True/False, never None.
    * Only appended when today is not already archived (no duplicates).
    * `open` uses the day reference (LTP - change) and `close` the LTP, so
      the candle renders like any other bar.
    * Zero volume (pre-open feed) yields a bar with volume None rather than a
      fake 0, and the bar is skipped entirely when LTP is unusable.
    * Returns None when the poller has no fresh quote - indicators then
      compute on archived data only, exactly as before.
    """
    if market_open is False:
        return None  # market closed: the archive's last bar is the last session
    try:
        quote = get_realtime_service().get_cached_price(sym)
    except Exception:
        # A poller outage must never take the chart down.
        return None
    if quote is None:
        return None
    today = datetime.now().strftime("%Y-%m-%d")
    if dates and today <= dates[-1]:
        return None  # already archived (or clock ahead of the data)
    if quote.ltp is None or quote.ltp <= 0:
        return None
    ref = quote.ltp - quote.change if quote.change else quote.ltp
    vol = float(quote.volume) if quote.volume else None
    return Bar(
        date=today,
        open=ref,
        high=max(quote.high, quote.ltp, ref),
        low=min(quote.low if quote.low and quote.low > 0 else quote.ltp, quote.ltp, ref),
        close=quote.ltp,
        volume=vol,
    )


def _range_first(dates: list[str], latest: str, days: int) -> str:
    """First archived date inside a calendar look-back window."""
    want = (date.fromisoformat(latest) - timedelta(days=days)).isoformat()
    return next((d for d in dates if d >= want), dates[0])


def _range_complete(dates: list[str], latest: str, days: int) -> bool:
    """True when the archive reaches past the window's start date."""
    want = (date.fromisoformat(latest) - timedelta(days=days)).isoformat()
    return dates[0] < want


# -- timeframe aggregation (D / W / M) ---------------------------------------

TF_ORDER = ("D", "W", "M")

#: Auto ("NEPSE-style") mapping. Observed: NEPSE's 3M view draws ~13 candles,
#: one per trading week (user report for AHL), so quarters and years collapse
#: to weeks and the whole history to months. The 1m/6m/1y/All counts are an
#: open question with the user; adjust here when they answer.
#: UNVERIFIED: 1m/6m/1y/All counts not confirmed with NEPSE; marked spec_status=unverified.
AUTO_TF_BY_RANGE = {
    "1W": "D",
    "1M": "D",
    "3M": "W",
    "6M": "W",
    "YTD": "W",
    "1Y": "W",
    "ALL": "W",
}

#: Custom windows collapse by calendar span (days).
AUTO_TF_BY_DAYS = ((120, "D"), (550, "W"))


def _auto_timeframe(range_requested: str, days: Optional[int]) -> str:
    """Which bar size the Auto mode picks for a range (or custom span)."""
    if range_requested != "custom":
        return AUTO_TF_BY_RANGE.get(range_requested, "D")
    if days is None:
        return "D"
    for limit, tf in AUTO_TF_BY_DAYS:
        if days <= limit:
            return tf
    return "M"


def _nepse_week_start(d: date, week_start: str = "sunday") -> date:
    """The week start date for the NEPSE trading week containing d.

    NEPSE trades Sunday-Thursday. The week bucket is determined by week_start:
    - week_start="sunday" (default): week is Sun-Thu, bucket = most recent Sunday
    - week_start="monday": week is Mon-Fri, bucket = most recent Monday

    weekday() is Mon=0..Sun=6.
    For week_start="sunday": (weekday + 1) % 7 maps Sun->0, Mon->1 .. Thu->4
    For week_start="monday": weekday() maps Mon->0, Tue->1 .. Fri->4
    """
    if week_start == "monday":
        return d - timedelta(days=d.weekday())
    return d - timedelta(days=(d.weekday() + 1) % 7)


def _nepse_week_sunday(d: date) -> date:
    """Backward-compatible wrapper for week_start='sunday'."""
    return _nepse_week_start(d, week_start="sunday")


def _aggregate_ohlcv(
    dates: list[str],
    opens: list[Optional[float]],
    highs: list[Optional[float]],
    lows: list[Optional[float]],
    closes: list[Optional[float]],
    volumes: list[Optional[float]],
    timeframe: str,
    week_start: str = "sunday",
    bar_label_mode: str = "last_session",
) -> tuple[
    list[str],
    list[Optional[float]],
    list[Optional[float]],
    list[Optional[float]],
    list[Optional[float]],
    list[Optional[float]],
]:
    """Collapse daily bars into weekly or monthly bars (B: timeframe selector).

    Weekly = the NEPSE trading week (Sun-Thu or Mon-Fri); a session joins
    the bucket of the week-start day that starts its week (the archive holds no
    Friday/Saturday sessions, asserted by the contract tests). Monthly = the
    calendar month.

    Bar label: the period's LAST session date by default, so the running (incomplete)
    week carries the day its close was actually observed on and lines up with
    the latest daily session. Set bar_label_mode="period_start" to use the
    first session's date instead.

    Aggregation: open = first open, high = max high, low = min low,
    close = last close, volume = sum of the non-null dailies (None only when
    every daily volume is null - a missing value is never turned into a zero).
    """
    from datetime import date, timedelta

    buckets: dict[str, list[int]] = {}
    for i, ds in enumerate(dates):
        d = date.fromisoformat(ds)
        if timeframe == "W":
            key = _nepse_week_start(d, week_start).isoformat()
        else:
            key = ds[:7]  # YYYY-MM
        buckets.setdefault(key, []).append(i)

    out_dates: list[str] = []
    out_o: list[Optional[float]] = []
    out_h: list[Optional[float]] = []
    out_l: list[Optional[float]] = []
    out_c: list[Optional[float]] = []
    out_v: list[Optional[float]] = []
    for idxs in buckets.values():
        i0, i1 = idxs[0], idxs[-1]
        h_present = [highs[i] for i in idxs if highs[i] is not None]
        l_present = [lows[i] for i in idxs if lows[i] is not None]
        v_present = [volumes[i] for i in idxs if volumes[i] is not None]
        if bar_label_mode == "period_start":
            out_dates.append(dates[i0])
        else:
            out_dates.append(dates[i1])
        out_o.append(opens[i0])
        out_h.append(max(h_present) if h_present else None)
        out_l.append(min(l_present) if l_present else None)
        out_c.append(closes[i1])
        out_v.append(sum(v_present) if v_present else None)
    return out_dates, out_o, out_h, out_l, out_c, out_v


@router.get("/chart/{symbol}", summary="Candles, indicators and panel data")
async def chart(
    symbol: str,
    session: DbSession,
    # Named `range_key`, not `range`: the latter would shadow the builtin
    # `range()` this module uses. The wire name stays `range`.
    range_key: str = Query("1Y", alias="range", description="1M | 3M | 6M | 1Y | ALL"),
    mode: str = Query("UNADJUSTED", description="ADJUSTED | UNADJUSTED"),
    indicators: str = Query(
        "sma_20,ema_20,rsi_14,macd,bb,vwap,obv,ad,cmf",
        description="Comma-separated indicator keys, or 'none'",
    ),
    compare: Optional[str] = Query(
        None,
        description="Second symbol for correlation / ratio / spread / compare tokens",
    ),
    basis: str = Query("as_traded", description="as_traded | adjusted"),
    start: Optional[str] = Query(None, description="Custom window start (YYYY-MM-DD)"),
    end: Optional[str] = Query(None, description="Custom window end (YYYY-MM-DD)"),
    tf: str = Query(
        "auto",
        alias="tf",
        description="Bar timeframe: D | W | M | auto (NEPSE-style per range)",
    ),
    week_start: str = Query(
        "monday",
        alias="week_start",
        description="Week start day for W timeframe: sunday | monday (default monday inferred from NEPSE AHL 3M labels; spec_status: unverified)",
    ),
    bar_label_mode: str = Query(
        "period_start",
        alias="bar_label_mode",
        description="Bar date label: last_session (last session date) | period_start (period start date, default inferred from NEPSE AHL 3M labels; spec_status: unverified)",
    ),
) -> dict[str, Any]:
    """Everything the chart renders, in one response.

    `range` is a calendar window measured back from the latest archived bar. A
    window longer than the archive holds comes back flagged `unavailable` with
    the reason, so the UI can grey the shortcut out rather than silently
    showing a shorter period than the user asked for.
    """
    sym = validate_symbol(symbol)
    if range_key not in RANGE_ORDER:
        raise HTTPException(400, f"Unknown range {range_key!r}. Expected one of {RANGE_ORDER}.")
    if mode not in ("ADJUSTED", "UNADJUSTED"):
        raise HTTPException(400, "mode must be ADJUSTED or UNADJUSTED.")
    if basis not in ("as_traded", "adjusted"):
        raise HTTPException(400, "basis must be as_traded or adjusted.")
    if tf not in ("D", "W", "M", "auto"):
        raise HTTPException(400, "tf must be one of D, W, M, auto.")
    try:
        start_d = date.fromisoformat(start) if start else None
        end_d = date.fromisoformat(end) if end else None
    except ValueError as exc:
        raise HTTPException(400, "start and end must be YYYY-MM-DD dates.") from exc
    if start_d and end_d and start_d > end_d:
        raise HTTPException(400, "start must be on or before end.")
    # `adjusted` and the legacy ADJUSTED mode both ask for a corrected series;
    # neither can be honoured today (see price_mode below).
    wants_adjusted = basis == "adjusted" or mode == "ADJUSTED"

    rows = session.scalars(
        select(DailyBar).where(DailyBar.symbol == sym).order_by(DailyBar.business_date)
    ).all()
    if not rows:
        raise HTTPException(
            404,
            f"No archived bars for {sym}. Run POST /api/archive/backfill to populate it.",
        )

    security = session.get(Security, sym)
    dates = [r.business_date for r in rows]

    # Cross-symbol tokens need a second series aligned by date.
    compare_closes_by_date: dict[str, Optional[float]] = {}
    if compare:
        compare_sym = validate_symbol(compare)
        c_rows = session.scalars(
            select(DailyBar)
            .where(DailyBar.symbol == compare_sym)
            .order_by(DailyBar.business_date)
        ).all()
        compare_closes_by_date = {r.business_date: r.close for r in c_rows}

    opens = [r.open for r in rows]
    highs = [r.high for r in rows]
    lows = [r.low for r in rows]
    closes = [r.close for r in rows]
    volumes = [float(r.volume) if r.volume is not None else None for r in rows]
    latest = dates[-1]

    # -- live session merge -------------------------------------------------
    # Today's quote from the shared poller becomes a synthetic bar appended
    # before any computation, so every indicator below is live-aware. When
    # there is no fresh quote the series is untouched and `live` says so.
    # The merge only happens while NEPSE reports the market OPEN: the poller
    # keeps its cache warm on closed days too, and re-dating that stale quote
    # to today would paint a phantom candle the exchange's own chart lacks.
    live_quote = None
    try:
        q = get_realtime_service().get_cached_price(sym)
        live_quote = (
            {
                "ltp": q.ltp,
                "change": q.change,
                "change_pct": q.change_pct,
                "volume": q.volume,
                "timestamp": q.timestamp.isoformat(),
            }
            if q is not None
            else None
        )
    except Exception:
        live_quote = None
    market_open: Optional[bool] = None
    status_as_of: Optional[str] = None
    if live_quote is not None:
        # Only reachable when a quote exists, so tests without a poller never
        # touch the upstream status call; NEPSE's status is TTL-cached anyway.
        try:
            st = await _nepse.get_market_status()
            market_open = st.is_open
            status_as_of = st.as_of
        except Exception:
            market_open = None  # unreadable: no live bar is trusted
    live_bar = _live_bar(sym, dates, market_open=market_open)
    live_mode: Optional[str] = None
    if live_bar is not None:
        dates = dates + [live_bar.date]
        opens = opens + [live_bar.open]
        highs = highs + [live_bar.high]
        lows = lows + [live_bar.low]
        closes = closes + [live_bar.close]
        volumes = volumes + [live_bar.volume]
        latest = live_bar.date
        live_mode = "appended"
    elif (
        market_open is not False
        and live_quote is not None
        and dates
        and dates[-1] == datetime.now().strftime("%Y-%m-%d")
    ):
        # Today's row is archived but the close may not be published yet (the
        # ingest runs after NEPSE's EOD file). Overlay the live session onto
        # that bar so the indicators still carry the live session; when the
        # close already exists the bar is complete and left untouched.
        i = len(dates) - 1
        if closes[i] is None:
            q_ltp = float(live_quote["ltp"])
            q_chg = float(live_quote["change"] or 0.0)
            q_vol = live_quote["volume"]
            closes[i] = q_ltp
            opens[i] = opens[i] if opens[i] is not None else (q_ltp - q_chg if q_chg else q_ltp)
            hi = float(highs[i]) if highs[i] is not None else q_ltp
            lo = float(lows[i]) if lows[i] is not None else q_ltp
            highs[i] = max(hi, q_ltp)
            lows[i] = min(lo, q_ltp)
            volumes[i] = float(q_vol) if q_vol else volumes[i]
            live_mode = "overlay"

    # -- timeframe resolution + aggregation ----------------------------------
    # "auto" picks the bar size NEPSE-style for the requested range (weekly for
    # a 3M view, etc.). The DAILY series is kept for the right-hand panel -
    # day change, 52-week range and the performance grid are daily facts even
    # when the chart draws weekly bars. The live bar (only while NEPSE reports
    # the market open) joins its week/month like any other session.
    custom_window = start_d is not None or end_d is not None
    if custom_window:
        eff_s = start_d or date.fromisoformat(dates[0])
        eff_e = end_d or date.fromisoformat(dates[-1])
        auto_tf = _auto_timeframe("custom", (eff_e - eff_s).days)
    else:
        auto_tf = _auto_timeframe(range_key, None)
    applied_tf = tf if tf != "auto" else auto_tf

    daily_dates, daily_opens = dates, opens
    daily_highs, daily_lows = highs, lows
    daily_closes, daily_volumes = closes, volumes
    if applied_tf != "D":
        dates, opens, highs, lows, closes, volumes = _aggregate_ohlcv(
            dates, opens, highs, lows, closes, volumes, applied_tf, week_start, bar_label_mode
        )

    # -- window selection ----------------------------------------------------
    # A custom start/end (the card's date pickers) overrides the range
    # shortcuts. Either way the window is a slice of the (possibly aggregated)
    # series. Indicators are NOT computed on the slice: they run on the full
    # history through the window's last bar and are sliced afterwards, so a
    # 20-bar lookback is already warm at the window's left edge and SMA 20
    # starts at the first candle like NEPSE's own chart. A value the archive
    # genuinely cannot produce yet stays null and is reported with a reason -
    # missing is not zero.
    if start_d is not None or end_d is not None:
        eff_start = (start_d or date.fromisoformat(dates[0])).isoformat()
        eff_end = (end_d or date.fromisoformat(latest)).isoformat()
        start_idx = next((i for i, d in enumerate(dates) if d >= eff_start), None)
        end_idx = next(
            (i for i in range(len(dates) - 1, -1, -1) if dates[i] <= eff_end), None
        )
        if start_idx is None or end_idx is None or start_idx > end_idx:
            raise HTTPException(
                404,
                f"No archived bars for {sym} between {eff_start} and {eff_end}.",
            )
        range_requested = "custom"
        days_requested = (
            date.fromisoformat(eff_end) - date.fromisoformat(eff_start)
        ).days
    else:
        want = _want_date(latest, range_key)
        start_idx = next((i for i, d in enumerate(dates) if d >= want), None)
        if start_idx is None:
            start_idx = 0
        end_idx = len(dates) - 1
        range_requested = range_key
        days_requested = (
            (date.fromisoformat(latest) - date.fromisoformat(want)).days
            if range_key == "YTD"
            else RANGE_DAYS[range_key]
        )
    first_shown = dates[start_idx]
    window_last = dates[end_idx]

    # `available` means we can show a meaningful window at all. `complete` means
    # the archive reaches past the requested start, so the whole period is
    # genuinely covered. These differ by design: the archive holds 365 of the
    # 366 days a "1Y" label implies, and calling that unavailable would be
    # technically true and practically useless. Both numbers are reported and
    # the UI states the real first date.
    # `complete` means the archive reaches past the requested start, so the
    # whole period is genuinely covered. A custom window is complete when the
    # archive starts on or before the requested start date.
    if range_requested == "custom":
        want = None
        complete = daily_dates[0] <= eff_start
    else:
        want = _want_date(window_last, range_requested)
        complete = daily_dates[0] < want
    days_available = (date.fromisoformat(window_last) - date.fromisoformat(first_shown)).days
    range_available = first_shown <= window_last

    window = {
        "dates": dates[start_idx : end_idx + 1],
        "open": opens[start_idx : end_idx + 1],
        "high": highs[start_idx : end_idx + 1],
        "low": lows[start_idx : end_idx + 1],
        "close": closes[start_idx : end_idx + 1],
        "volume": volumes[start_idx : end_idx + 1],
    }

    from app.analytics.indicators import Bar

    # -- indicators: compute on FULL history, then slice to the window -------
    # The old code computed on the window slice, so every lookback restarted
    # inside the view: SMA 20 / EMA 20 / WMA 20 / MA crosses began ~20 candles
    # after the left edge (user report on AHL). Computing on the full series
    # through the window's last bar and slicing afterwards puts the first value
    # on the first candle whenever the archive is warm enough - which is what
    # NEPSE's own chart shows. Whole-lookback indicators (Fibonacci,
    # volume profile, zigzag) measure the full series through the window end.
    compute_end = end_idx + 1
    compute_dates = dates[:compute_end]
    compute_opens = opens[:compute_end]
    compute_highs = highs[:compute_end]
    compute_lows = lows[:compute_end]
    compute_closes = closes[:compute_end]
    compute_volumes = volumes[:compute_end]
    bars = [
        Bar(date=d, open=o, high=h, low=l, close=c, volume=v)
        for d, o, h, l, c, v in zip(
            compute_dates, compute_opens, compute_highs,
            compute_lows, compute_closes, compute_volumes,
        )
    ]

    # -- indicators --------------------------------------------------------
    wanted = {k.strip() for k in indicators.split(",") if k.strip()} - {"none", ""}
    out_indicators: dict[str, list[Optional[float]]] = {}
    # Compute-series aliases (full history through the window's last bar).
    w_closes = compute_closes
    dates_w = compute_dates
    if "sma_20" in wanted:
        out_indicators["sma_20"] = sma_on_valid(w_closes, 20)
    if "ema_20" in wanted:
        out_indicators["ema_20"] = ema_on_valid(w_closes, 20)
    if "wma_20" in wanted:
        out_indicators["wma_20"] = wma(w_closes, 20)
    if "hma_16" in wanted:
        out_indicators["hma_16"] = hma(w_closes, 16)
    if "dema_20" in wanted:
        out_indicators["dema_20"] = dema(w_closes, 20)
    if "tema_20" in wanted:
        out_indicators["tema_20"] = tema(w_closes, 20)
    if "trix_15" in wanted:
        out_indicators["trix_15"] = trix(w_closes, 15)
    if "adx" in wanted:
        plus_di, minus_di, dx, adx_line = adx(bars, 14)
        out_indicators["adx"] = adx_line
        out_indicators["plus_di"] = plus_di
        out_indicators["minus_di"] = minus_di
        out_indicators["dx"] = dx
    if "aroon" in wanted:
        aroon_up, aroon_down = aroon(bars, 14)
        out_indicators["aroon_up"] = aroon_up
        out_indicators["aroon_down"] = aroon_down
    if "psar" in wanted:
        out_indicators["psar"] = psar(bars)
    if "supertrend" in wanted:
        out_indicators["supertrend"] = supertrend(bars, 10, 3.0)
    if "vortex" in wanted:
        vplus, vminus = vortex(bars, 14)
        out_indicators["vortex_plus"] = vplus
        out_indicators["vortex_minus"] = vminus
    if "ichimoku" in wanted:
        tenkan, kijun, senkou_a, senkou_b, chikou = ichimoku(bars)
        out_indicators["ichimoku_tenkan"] = tenkan
        out_indicators["ichimoku_kijun"] = kijun
        out_indicators["ichimoku_senkou_a"] = senkou_a
        out_indicators["ichimoku_senkou_b"] = senkou_b
        out_indicators["ichimoku_chikou"] = chikou
    if "rsi_14" in wanted:
        out_indicators["rsi_14"] = rsi_on_valid(w_closes, 14)
    if "macd" in wanted:
        line, sig, hist = macd_on_valid(w_closes)
        out_indicators["macd"] = line
        out_indicators["macd_signal"] = sig
        out_indicators["macd_histogram"] = hist
    if "bb" in wanted:
        mid, up, lo, bw, pctb = bollinger_on_valid(w_closes, 20, 2.0)
        out_indicators["bb_upper"] = up
        out_indicators["bb_middle"] = mid
        out_indicators["bb_lower"] = lo
    if "vwap" in wanted:
        out_indicators["vwap"] = vwap_series(bars)
    if "obv" in wanted:
        out_indicators["obv"] = obv(bars)
    if "ad" in wanted:
        out_indicators["accumulation_distribution"] = accumulation_distribution_line(bars)
    if "cmf" in wanted:
        out_indicators["chaikin_money_flow_20"] = chaikin_money_flow(bars, 20)
        out_indicators["money_flow_index_14"] = money_flow_index(bars, 14)
    if "mfi" in wanted:
        # Was frontend-only before the chart fix: the MFI 14 picker chip called
        # a token no handler served, so the click silently did nothing.
        out_indicators["money_flow_index_14"] = money_flow_index(bars, 14)
    if "roc" in wanted:
        out_indicators["roc_1"] = roc(w_closes, 1)
    if "atr" in wanted:
        out_indicators["atr_14"] = atr(bars, 14)
    if "stoch" in wanted:
        k_line, d_line = stochastic(bars, 14, 3)
        out_indicators["stoch_k"] = k_line
        out_indicators["stoch_d"] = d_line
    if "stoch_rsi" in wanted:
        out_indicators["stoch_rsi"] = stoch_rsi(w_closes, 14, 14)
    if "cci" in wanted:
        out_indicators["cci_20"] = cci(bars, 20)
    if "williams_r" in wanted:
        out_indicators["williams_r_14"] = williams_r(bars, 14)
    if "momentum" in wanted:
        out_indicators["momentum_10"] = momentum(w_closes, 10)
    if "ultimate_osc" in wanted:
        out_indicators["ultimate_osc"] = ultimate_oscillator(bars, 7, 14, 28)
    if "awesome_osc" in wanted:
        out_indicators["awesome_osc"] = awesome_oscillator(bars, 5, 34)
    if "tsi" in wanted:
        out_indicators["tsi"] = tsi(w_closes, 25, 13)
    if "rvi" in wanted:
        rvi_line, rvi_sig = rvi(bars)
        out_indicators["rvi"] = rvi_line
        out_indicators["rvi_signal"] = rvi_sig
    if "stdev" in wanted:
        out_indicators["stdev_20"] = stdev_series(w_closes, 20)
    if "keltner" in wanted:
        k_mid, k_up, k_lo = keltner(bars, 20, 2.0, 10)
        out_indicators["keltner_upper"] = k_up
        out_indicators["keltner_middle"] = k_mid
        out_indicators["keltner_lower"] = k_lo
    if "donchian" in wanted:
        d_up, d_lo, d_mid = donchian(bars, 20)
        out_indicators["donchian_upper"] = d_up
        out_indicators["donchian_lower"] = d_lo
        out_indicators["donchian_middle"] = d_mid
    if "historical_vol" in wanted:
        out_indicators["historical_vol_20"] = historical_volatility(w_closes, 20, 252)
    if "chaikin_vol" in wanted:
        out_indicators["chaikin_volatility"] = chaikin_volatility(bars, 10, 10)
    if "vpt" in wanted:
        out_indicators["vpt"] = volume_price_trend(bars)
    if "emv" in wanted:
        out_indicators["emv_14"] = ease_of_movement(bars, 14)
    if "force_index" in wanted:
        out_indicators["force_index_13"] = force_index(bars, 13)
    if "volume_osc" in wanted:
        out_indicators["volume_osc"] = volume_oscillator(bars, 5, 20)
    if "klinger" in wanted:
        out_indicators["klinger"] = klinger_oscillator(bars, 34, 55)
    if "chaikin_osc" in wanted:
        out_indicators["chaikin_osc"] = chaikin_oscillator(bars, 3, 10)
    if "vwma" in wanted:
        out_indicators["vwma_20"] = vwma(w_closes, compute_volumes, 20)
    if "cvd" in wanted:
        out_indicators["cvd"] = cumulative_volume_delta(bars)
    if "pivots" in wanted:
        for key, series_ in pivot_points(bars).items():
            out_indicators[f"pivot_{key}"] = series_
    if "camarilla" in wanted:
        for key, series_ in camarilla_pivots(bars).items():
            out_indicators[f"cam_{key}"] = series_
    if "woodie" in wanted:
        for key, series_ in woodie_pivots(bars).items():
            out_indicators[f"wpiv_{key}"] = series_
    if "demark" in wanted:
        for key, series_ in demark_pivots(bars).items():
            out_indicators[f"dpiv_{key}"] = series_
    if "fib_retrace" in wanted:
        for key, series_ in fibonacci_retracement(bars).items():
            out_indicators[key] = series_
    if "fib_extension" in wanted:
        for key, series_ in fibonacci_extension(bars).items():
            out_indicators[key] = series_
    if "fib_fan" in wanted:
        for key, series_ in fibonacci_fan(bars).items():
            out_indicators[key] = series_
    if "volume_profile" in wanted:
        vp = volume_profile(bars, 24, 70.0)
        out_indicators["vp_poc"] = [vp["poc"]] * len(dates_w)
        out_indicators["vp_va_high"] = [vp["va_high"]] * len(dates_w)
        out_indicators["vp_va_low"] = [vp["va_low"]] * len(dates_w)

    # -- Batch B doc additions -----------------------------------------------
    if "alma" in wanted:
        out_indicators["alma_9"] = alma(w_closes, 9)
    if "asi" in wanted:
        out_indicators["asi"] = asi(bars)
    if "avg_price" in wanted:
        out_indicators["avg_price"] = average_price(bars)
    if "ema_cross" in wanted:
        ec = ema_cross(w_closes, 9, 21)
        out_indicators["ema_cross_fast"] = ec["fast"]
        out_indicators["ema_cross_slow"] = ec["slow"]
        out_indicators["ema_cross_signal"] = ec["signal"]
    if "ma_cross" in wanted:
        mc = ma_cross(w_closes, 9, 21)
        out_indicators["ma_cross_fast"] = mc["fast"]
        out_indicators["ma_cross_slow"] = mc["slow"]
        out_indicators["ma_cross_signal"] = mc["signal"]
    if "ma_ema_cross" in wanted:
        mec = ma_ema_cross(w_closes, 9, 21)
        out_indicators["ma_ema_cross_fast"] = mec["fast"]
        out_indicators["ma_ema_cross_slow"] = mec["slow"]
        out_indicators["ma_ema_cross_signal"] = mec["signal"]
    if "ama" in wanted:
        out_indicators["ama_9"] = ama(w_closes, 9)
    if "ma_hamming" in wanted:
        out_indicators["hamming_20"] = ma_hamming(w_closes, 20)
    if "ma_multi" in wanted:
        for key, series_ in ma_multiple(w_closes, (20, 50, 100, 200)).items():
            out_indicators[key] = series_
    if "ma_channel" in wanted:
        chan = ma_channel(w_closes, 20, 10.0)
        out_indicators["ma_channel_upper"] = chan["upper"]
        out_indicators["ma_channel_middle"] = chan["middle"]
        out_indicators["ma_channel_lower"] = chan["lower"]
    if "smma" in wanted:
        out_indicators["smma_20"] = smma(w_closes, 20)
    if "lsma" in wanted:
        out_indicators["lsma_25"] = lsma(w_closes, 25)
    if "linreg_curve" in wanted:
        out_indicators["linreg_curve_100"] = linreg_curve(w_closes, 100)
    if "linreg_slope" in wanted:
        out_indicators["linreg_slope_25"] = linreg_slope(w_closes, 25)
    if "linreg_trend" in wanted:
        lt = linreg_trend(w_closes, 100)
        out_indicators["linreg_trend_value"] = lt["value"]
        out_indicators["linreg_trend_direction"] = lt["direction"]
    if "mcginley" in wanted:
        out_indicators["mcginley_14"] = mcginley(w_closes, 14)
    if "gmma" in wanted:
        for key, series_ in gmma(w_closes).items():
            out_indicators[key] = series_
    if "majority_rule" in wanted:
        mr = majority_rule(bars)
        out_indicators["majority_score"] = mr["score"]
        out_indicators["majority_components"] = mr["components"]
    if "trend_strength" in wanted:
        out_indicators["trend_strength"] = trend_strength(w_closes)
    if "zigzag" in wanted:
        zz = zigzag(bars, 5.0)
        out_indicators["zigzag_price"] = zz["price"]
        out_indicators["zigzag_confirmed"] = zz["confirmed"]
    if "alligator" in wanted:
        ag = alligator(bars)
        out_indicators["alligator_jaw"] = ag["jaw"]
        out_indicators["alligator_teeth"] = ag["teeth"]
        out_indicators["alligator_lips"] = ag["lips"]
    if "fractals" in wanted:
        fr = fractals(bars)
        out_indicators["fractal_high"] = fr["high"]
        out_indicators["fractal_low"] = fr["low"]
        out_indicators["fractal_confirmed"] = fr["confirmed"]
    if "accel_osc" in wanted:
        out_indicators["accel_osc"] = accelerator_oscillator(bars)
    if "cmo" in wanted:
        out_indicators["cmo_14"] = cmo(w_closes, 14)
    if "connors_rsi" in wanted:
        out_indicators["connors_rsi"] = connors_rsi(w_closes)
    if "coppock" in wanted:
        out_indicators["coppock"] = coppock(w_closes)
    if "fisher" in wanted:
        out_indicators["fisher_9"] = fisher(w_closes, 9)
    if "kst" in wanted:
        out_indicators["kst"] = kst(w_closes)
    if "dpo" in wanted:
        out_indicators["dpo_21"] = dpo(w_closes, 21)
    if "smi_ergodic" in wanted:
        se = smi_ergodic(w_closes)
        out_indicators["smi_ergodic"] = se["value"]
        out_indicators["smi_ergodic_signal"] = se["signal"]
    if "rci" in wanted:
        out_indicators["rci_14"] = rci(w_closes, 14)
    if "price_osc" in wanted:
        po = price_oscillator(w_closes, 10, 30)
        out_indicators["price_osc_abs"] = po["abs"]
        out_indicators["price_osc_pct"] = po["pct"]
    if "rvi_volatility" in wanted:
        out_indicators["rvi_volatility_14"] = relative_volatility_index(w_closes, 14)
    if "chande_kroll" in wanted:
        ck = chande_kroll_stop(bars, 10, 1.0, 9)
        out_indicators["chande_kroll_long"] = ck["long_stop"]
        out_indicators["chande_kroll_short"] = ck["short_stop"]
    if "choppiness" in wanted:
        out_indicators["choppiness_14"] = choppiness(bars, 14)
    if "chop_zone" in wanted:
        out_indicators["chop_zone"] = chop_zone(bars, 21, 14)
    if "envelopes" in wanted:
        env = envelopes(w_closes, 20, 2.0)
        out_indicators["envelopes_upper"] = env["upper"]
        out_indicators["envelopes_middle"] = env["middle"]
        out_indicators["envelopes_lower"] = env["lower"]
    if "mass_index" in wanted:
        out_indicators["mass_index"] = mass_index(bars, 9, 25)
    if "std_error" in wanted:
        out_indicators["std_error_20"] = standard_error(w_closes, 20)
    if "std_error_bands" in wanted:
        seb = standard_error_bands(w_closes, 20, 2.0)
        out_indicators["seb_upper"] = seb["upper"]
        out_indicators["seb_middle"] = seb["middle"]
        out_indicators["seb_lower"] = seb["lower"]
    if "vol_c2c" in wanted:
        out_indicators["vol_c2c_20"] = volatility_c2c(w_closes, 20, 252.0)
    if "vol_zero_trend" in wanted:
        out_indicators["vol_zero_trend_20"] = volatility_zero_trend_c2c(w_closes, 20, 252.0)
    if "vol_ohlc" in wanted:
        out_indicators["vol_ohlc_20"] = volatility_ohlc(bars, 20, 252.0)

    # -- disabled indicators (not_applicable) --------------------------------
    # Volatility Index: needs option-implied data. NEPSE publishes no
    # derivatives or options series, so an implied-volatility index cannot be
    # computed from daily OHLCV - reported as disabled, never faked.
    disabled: dict[str, str] = {}
    if "vol_index" in wanted:
        disabled["vol_index"] = (
            "not_applicable: a volatility index needs option-implied data; "
            "NEPSE publishes no derivatives or options series, so it cannot "
            "be computed from daily OHLCV."
        )
    if "hl_52w" in wanted:
        hilo = high_low_52w(bars, 252)
        out_indicators["hl_52w_high"] = [hilo["high"]] * len(dates_w)
        out_indicators["hl_52w_low"] = [hilo["low"]] * len(dates_w)
    if "bop" in wanted:
        out_indicators["bop_14"] = balance_of_power(bars, 14)
    if "correlation" in wanted:
        if not compare or not compare_closes_by_date:
            disabled["correlation"] = (
                "needs a comparison symbol: pass compare=<SYMBOL> so the two "
                "close series can be aligned by date."
            )
        else:
            corr_pairs_idx = [
                i
                for i, d in enumerate(dates_w)
                if w_closes[i] is not None and compare_closes_by_date.get(d) is not None
            ]
            corr_a = [w_closes[i] for i in corr_pairs_idx]  # type: ignore[misc]
            corr_b = [compare_closes_by_date[dates_w[i]] for i in corr_pairs_idx]
            corr_vals = correlation(corr_a, corr_b, 20)
            corr_aligned: list[Optional[float]] = [None] * len(dates_w)
            for pos, i in enumerate(corr_pairs_idx):
                corr_aligned[i] = corr_vals[pos]
            out_indicators["correlation_20"] = corr_aligned

    # -- Batch B doc #49-#52 ----------------------------------------------------
    if "correlation_log" in wanted:
        if not compare or not compare_closes_by_date:
            disabled["correlation_log"] = (
                "needs a comparison symbol: pass compare=<SYMBOL> so the two "
                "close series can be aligned by date."
            )
        else:
            corr_pairs_idx = [
                i
                for i, d in enumerate(dates_w)
                if w_closes[i] is not None and compare_closes_by_date.get(d) is not None
            ]
            corr_a = [w_closes[i] for i in corr_pairs_idx]  # type: ignore[misc]
            corr_b = [compare_closes_by_date[dates_w[i]] for i in corr_pairs_idx]
            corr_vals = correlation_log(corr_a, corr_b, 20)
            corr_aligned: list[Optional[float]] = [None] * len(dates_w)
            for pos, i in enumerate(corr_pairs_idx):
                corr_aligned[i] = corr_vals[pos]
            out_indicators["correlation_log_20"] = corr_aligned

    if "ratio" in wanted:
        if not compare or not compare_closes_by_date:
            disabled["ratio"] = (
                "needs a comparison symbol: pass compare=<SYMBOL> so the two "
                "close series can be aligned by date."
            )
        else:
            ratio_pairs_idx = [
                i
                for i, d in enumerate(dates_w)
                if w_closes[i] is not None and compare_closes_by_date.get(d) is not None
            ]
            ratio_a = [w_closes[i] for i in ratio_pairs_idx]  # type: ignore[misc]
            ratio_b = [compare_closes_by_date[dates_w[i]] for i in ratio_pairs_idx]
            ratio_vals = ratio(ratio_a, ratio_b)
            ratio_aligned: list[Optional[float]] = [None] * len(dates_w)
            for pos, i in enumerate(ratio_pairs_idx):
                ratio_aligned[i] = ratio_vals[pos]
            out_indicators["ratio"] = ratio_aligned

    if "spread" in wanted:
        if not compare or not compare_closes_by_date:
            disabled["spread"] = (
                "needs a comparison symbol: pass compare=<SYMBOL> so the two "
                "close series can be aligned by date."
            )
        else:
            spread_pairs_idx = [
                i
                for i, d in enumerate(dates_w)
                if w_closes[i] is not None and compare_closes_by_date.get(d) is not None
            ]
            spread_a = [w_closes[i] for i in spread_pairs_idx]  # type: ignore[misc]
            spread_b = [compare_closes_by_date[dates_w[i]] for i in spread_pairs_idx]
            spread_vals = spread(spread_a, spread_b)
            spread_aligned: list[Optional[float]] = [None] * len(dates_w)
            for pos, i in enumerate(spread_pairs_idx):
                spread_aligned[i] = spread_vals[pos]
            out_indicators["spread"] = spread_aligned

    if "compare" in wanted:
        if not compare or not compare_closes_by_date:
            disabled["compare"] = (
                "needs a comparison symbol: pass compare=<SYMBOL> so the two "
                "close series can be aligned by date."
            )
        else:
            compare_pairs_idx = [
                i
                for i, d in enumerate(dates_w)
                if w_closes[i] is not None and compare_closes_by_date.get(d) is not None
            ]
            compare_a = [w_closes[i] for i in compare_pairs_idx]  # type: ignore[misc]
            compare_b = [compare_closes_by_date[dates_w[i]] for i in compare_pairs_idx]
            compare_vals = compare(compare_a, compare_b, "rebase")
            compare_aligned: list[Optional[float]] = [None] * len(dates_w)
            for pos, i in enumerate(compare_pairs_idx):
                compare_aligned[i] = compare_vals[pos]
            out_indicators["compare"] = compare_aligned

    # -- Batch B doc #53-#56 ----------------------------------------------------
    if "median_price" in wanted:
        out_indicators["median_price"] = median_price(bars)
    if "typical_price" in wanted:
        out_indicators["typical_price"] = typical_price(bars)
    if "price_channel" in wanted:
        pc_up, pc_lo, pc_mid = price_channel(bars, 20)
        out_indicators["price_channel_upper"] = pc_up
        out_indicators["price_channel_lower"] = pc_lo
        out_indicators["price_channel_middle"] = pc_mid
    if "force_index" in wanted:
        out_indicators["force_index_13"] = force_index(bars, 13)
    if "technical_ratings" in wanted:
        tr = technical_ratings(bars)
        # The ratings function returns scalars per component; project them onto
        # the shared date axis as one-value series (latest only) so the chart
        # can draw them like any other line.
        def _tr_series(v: Optional[float]) -> list[Optional[float]]:
            return [v if i == len(dates_w) - 1 else None for i in range(len(dates_w))]

        out_indicators["tech_overall"] = _tr_series(tr["overall"])
        out_indicators["tech_ma_rating"] = _tr_series(tr["ma_rating"])
        out_indicators["tech_osc_rating"] = _tr_series(tr["osc_rating"])

    # -- warm-up report, then slice to the window ----------------------------
    # Every series above is index-aligned with compute_dates. A requested token
    # with no value ANYWHERE means the archive is shorter than the lookback:
    # report the reason instead of a fabricated zero, then slice to the window
    # so the payload aligns with series.dates.
    warm_up: dict[str, dict[str, Optional[str]]] = {}
    for key, series_ in out_indicators.items():
        if isinstance(series_, list) and series_ and not any(v is not None for v in series_):
            warm_up[key] = {
                "first_available": None,
                "reason": (
                    f"the archive for {sym} ({len(daily_dates)} daily sessions"
                    + (
                        ""
                        if applied_tf == "D"
                        else f" = {len(dates)} {applied_tf} bars"
                    )
                    + ") is shorter than this indicator's lookback, so it has no "
                    "value on any bar; missing is reported, never zero"
                ),
            }
    out_indicators = {
        key: (series_[start_idx:] if isinstance(series_, list) else series_)
        for key, series_ in out_indicators.items()
    }

    # -- right-hand panel --------------------------------------------------
    def _change_over(days: int) -> Optional[float]:
        cutoff = (date.fromisoformat(latest) - timedelta(days=days)).isoformat()
        idx = next((i for i, d in enumerate(daily_dates) if d >= cutoff), None)
        if idx is None:
            idx = 0
        if idx == 0:
            return None  # nothing before the window to measure from
        base = daily_closes[idx]
        last = next((c for c in reversed(daily_closes) if c is not None), None)
        if base is None or last is None or base == 0:
            return None
        return (last - base) / base * 100.0

    # The panel's "day" is the most recent session that actually has a close.
    # The newest bar can be an intraday snapshot with close=None, and using it
    # would compare a bar against itself and report a change of 0.00 - which
    # reads as "flat" when the real answer is "not published yet".
    last_closed = next(
        (i for i in range(len(daily_closes) - 1, -1, -1) if daily_closes[i] is not None), None
    )
    if last_closed is None:
        day_block: dict[str, Any] = {
            "as_of": None,
            "reason": "No archived session has a published close yet.",
        }
    else:
        prior = next(
            (
                daily_closes[i]
                for i in range(last_closed - 1, -1, -1)
                if daily_closes[i] is not None
            ),
            None,
        )
        day_block = {
            "as_of": daily_dates[last_closed],
            "open": daily_opens[last_closed],
            "high": daily_highs[last_closed],
            "low": daily_lows[last_closed],
            "ltp": daily_closes[last_closed],
            "prev_close": prior,
            "change": (
                daily_closes[last_closed] - prior
                if prior is not None and daily_closes[last_closed] is not None
                else None
            ),
            "change_pct": (
                (daily_closes[last_closed] - prior) / prior * 100.0
                if prior not in (None, 0) and daily_closes[last_closed] is not None
                else None
            ),
        }
        if daily_dates[-1] > daily_dates[last_closed]:
            day_block["incomplete_note"] = (
                f"{daily_dates[-1]} is archived but has no published close yet, so the "
                f"day panel shows the last complete session ({daily_dates[last_closed]})."
            )

    year_ago = (date.fromisoformat(latest) - timedelta(days=366)).isoformat()
    y_idx = next((i for i, d in enumerate(daily_dates) if d >= year_ago), None)
    highs_52 = [h for h in (daily_highs[y_idx:] if y_idx is not None else []) if h is not None]
    lows_52 = [l for l in (daily_lows[y_idx:] if y_idx is not None else []) if l is not None]

    return {
        "symbol": sym,
        "name": getattr(security, "name", None),
        "sector": getattr(security, "sector_code", None),
        "as_of": latest,
        "series": window,
        "indicators": out_indicators,
        "disabled": disabled,
        "live": {
            "merged": live_mode is not None,
            "mode": live_mode,
            "quote": live_quote,
            "market_open": market_open,
            "note": (
                "Today's session from the live poller is included as the last bar, "
                "so indicators carry the live session."
                if live_mode == "appended"
                else "Today's live price is overlaid on the archived bar (its close "
                "was not published yet), so indicators carry the live session."
                if live_mode == "overlay"
                else f"Market closed (NEPSE status as of {status_as_of or 'unknown'}): "
                "the chart shows the last archived session only."
                if market_open is False
                else "Market status unreadable, so no live bar is trusted; the chart "
                "shows archived sessions only."
                if live_quote is not None
                else "No live quote for this symbol right now; indicators are computed "
                "on archived sessions only."
            ),
        },
        "range": {
            "requested": range_requested,
            "available": range_available,
            "complete": complete,
            "first_shown": first_shown,
            "sessions_shown": len(window["dates"]),
            "days_available": days_available,
            "days_requested": days_requested,
            "reason": (
                None
                if complete
                else f"Archive starts {daily_dates[0]}, inside the {range_requested} window, so this "
                f"period is only covered from {first_shown}."
            ),
            "options": [
                {
                    "value": key,
                    "available": True,
                    "complete": daily_dates[0] < _want_date(latest, key),
                    "first_shown": next(
                        (d for d in daily_dates if d >= _want_date(latest, key)), daily_dates[0]
                    ),
                }
                for key in RANGE_ORDER
            ],
        },
        "price_mode": {
            "requested": "adjusted" if wants_adjusted else "as_traded",
            "applied": "as_traded",
            "differs_from_requested": wants_adjusted,
            "reason": (
                None
                if not wants_adjusted
                else "NEPSE publishes no split or bonus ex-dates, so an adjusted "
                "series cannot be built. Prices are shown as traded and this "
                "basis is a no-op rather than a silent fabrication."
            ),
        },
        "timeframe": {
            "requested": tf,
            "applied": applied_tf,
            "auto": tf == "auto",
            "auto_rule": AUTO_TF_BY_RANGE if tf == "auto" else None,
            "spec_status": "unverified",
            "week_start": week_start,
            "bar_label_mode": bar_label_mode,
            "note": (
                "Daily bars."
                if applied_tf == "D"
                else (
                    "NEPSE trading week Monday-Friday (week_start=monday); each bar is labelled with "
                    "the week's first session (period_start), open/high/low/close/volume aggregate the "
                    "week's dailies. Default week_start=monday and bar_label_mode=period_start are "
                    "inferred from NEPSE AHL 3M labels (Mon 6 Jul, 20 Jul, 3 Aug, 17 Aug, 14 Sep, 28 Sep); "
                    "spec_status: unverified."
                )
                if applied_tf == "W"
                else "Calendar months; each bar is labelled with the month's first "
                "session (period_start) and aggregates that month's dailies."
            ),
        },
        "warm_up": warm_up,
        "panel": {
            "day": day_block,
            "week_52": {
                "high": max(highs_52) if highs_52 else None,
                "low": min(lows_52) if lows_52 else None,
                "sessions": len(highs_52),
                "reason": (
                    None
                    if highs_52
                    else "Fewer than a year of bars is archived, so a true 52-week "
                    "range is unavailable."
                ),
            },
            "recent_5_days": [
                {"date": d, "close": c}
                for d, c in list(zip(dates, closes))[-5:]
            ],
            "performance": [
                {
                    "label": label,
                    "pct": _change_over(days),
                    "available": _change_over(days) is not None,
                }
                for label, days in PERFORMANCE_GRID
            ],
        },
        "notes": {
            "warm_up": (
                "A null indicator is undefined for that bar - insufficient "
                "history or a day with no volume. It is not zero."
            ),
            "scale_modes": (
                "Log and percentage scaling are view options applied by the chart "
                "library; the underlying series is unchanged."
            ),
        },
    }
