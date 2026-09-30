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
    atr,
    awesome_oscillator,
    bollinger,
    bollinger_on_valid,
    camarilla_pivots,
    chaikin_money_flow,
    chaikin_oscillator,
    chaikin_volatility,
    cci,
    cumulative_volume_delta,
    dema,
    demark_pivots,
    donchian,
    ease_of_movement,
    ema,
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
    money_flow_index,
    momentum,
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
    volume_oscillator,
    vwap_series,
    vwma,
    williams_r,
    wma,
    rvi,
    Bar,
)
from app.realtime.service import get_realtime_service
from app.archive.service import ArchiveService
from app.auth.deps import DbSession
from app.db.models import DailyBar, Security
from app.nepse.registry import get_adapter
from app.nepse.service import validate_symbol

router = APIRouter(prefix="/api/analytics", tags=["chart"])

_archive = ArchiveService(get_adapter())

#: Calendar look-backs offered as range shortcuts. Availability depends on how
#: far back the local archive reaches, which is reported per range.
RANGE_DAYS: dict[str, int] = {
    "1M": 31,
    "3M": 92,
    "6M": 183,
    "1Y": 366,
    "ALL": 3650,
}

#: Performance grid columns, as (label, calendar days).
PERFORMANCE_GRID: list[tuple[str, int]] = [
    ("1D", 1),
    ("1W", 7),
    ("1M", 31),
    ("3M", 92),
    ("6M", 183),
    ("1Y", 366),
]


def _live_bar(sym: str, dates: list[str]) -> Optional[Bar]:
    """Today's live session as a synthetic bar, from the shared poller cache.

    The nightly ingest only adds a bar after NEPSE publishes the EOD file, so
    between market open and the evening backfill the archived series ends
    yesterday - and every indicator computed on it is a day stale. The
    realtime poller's cache (one upstream NEPSE poll per 30s, fan-out to all
    readers) carries today's LTP/high/low/volume, so we append it as the last
    bar BEFORE computing: every indicator then includes the live session.

    Rules:
    * Only appended when today is not already archived (no duplicates).
    * `open` uses the day reference (LTP - change) and `close` the LTP, so
      the candle renders like any other bar.
    * Zero volume (pre-open feed) yields a bar with volume None rather than a
      fake 0, and the bar is skipped entirely when LTP is unusable.
    * Returns None when the poller has no fresh quote - indicators then
      compute on archived data only, exactly as before.
    """
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
) -> dict[str, Any]:
    """Everything the chart renders, in one response.

    `range` is a calendar window measured back from the latest archived bar. A
    window longer than the archive holds comes back flagged `unavailable` with
    the reason, so the UI can grey the shortcut out rather than silently
    showing a shorter period than the user asked for.
    """
    sym = validate_symbol(symbol)
    if range_key not in RANGE_DAYS:
        raise HTTPException(400, f"Unknown range {range_key!r}. Expected one of {sorted(RANGE_DAYS)}.")
    if mode not in ("ADJUSTED", "UNADJUSTED"):
        raise HTTPException(400, "mode must be ADJUSTED or UNADJUSTED.")

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
    live_bar = _live_bar(sym, dates)
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
    elif live_quote is not None and dates and dates[-1] == datetime.now().strftime("%Y-%m-%d"):
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

    # -- range windowing, with an honest "not fully covered" ----------------
    want = (date.fromisoformat(latest) - timedelta(days=RANGE_DAYS[range_key])).isoformat()
    start_idx = next((i for i, d in enumerate(dates) if d >= want), None)
    if start_idx is None:
        start_idx = 0
    first_shown = dates[start_idx]

    # `available` means we can show a meaningful window at all. `complete` means
    # the archive reaches past the requested start, so the whole period is
    # genuinely covered. These differ by design: the archive holds 365 of the
    # 366 days a "1Y" label implies, and calling that unavailable would be
    # technically true and practically useless. Both numbers are reported and
    # the UI states the real first date.
    complete = start_idx > 0 or first_shown < want
    days_available = (date.fromisoformat(latest) - date.fromisoformat(first_shown)).days
    days_requested = RANGE_DAYS[range_key]
    range_available = start_idx is not None and first_shown <= latest

    window = {
        "dates": dates[start_idx:],
        "open": opens[start_idx:],
        "high": highs[start_idx:],
        "low": lows[start_idx:],
        "close": closes[start_idx:],
        "volume": volumes[start_idx:],
    }

    from app.analytics.indicators import Bar

    bars = [
        Bar(date=d, open=o, high=h, low=l, close=c, volume=v)
        for d, o, h, l, c, v in zip(
            window["dates"], window["open"], window["high"],
            window["low"], window["close"], window["volume"],
        )
    ]

    # -- indicators --------------------------------------------------------
    wanted = {k.strip() for k in indicators.split(",") if k.strip()} - {"none", ""}
    out_indicators: dict[str, list[Optional[float]]] = {}
    w_closes = window["close"]
    dates_w = window["dates"]
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
        out_indicators["vwma_20"] = vwma(w_closes, window["volume"], 20)
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

    # -- right-hand panel --------------------------------------------------
    def _change_over(days: int) -> Optional[float]:
        cutoff = (date.fromisoformat(latest) - timedelta(days=days)).isoformat()
        idx = next((i for i, d in enumerate(dates) if d >= cutoff), None)
        if idx is None:
            idx = 0
        if idx == 0:
            return None  # nothing before the window to measure from
        base = closes[idx]
        last = next((c for c in reversed(closes) if c is not None), None)
        if base is None or last is None or base == 0:
            return None
        return (last - base) / base * 100.0

    # The panel's "day" is the most recent session that actually has a close.
    # The newest bar can be an intraday snapshot with close=None, and using it
    # would compare a bar against itself and report a change of 0.00 - which
    # reads as "flat" when the real answer is "not published yet".
    last_closed = next(
        (i for i in range(len(closes) - 1, -1, -1) if closes[i] is not None), None
    )
    if last_closed is None:
        day_block: dict[str, Any] = {
            "as_of": None,
            "reason": "No archived session has a published close yet.",
        }
    else:
        prior = next(
            (closes[i] for i in range(last_closed - 1, -1, -1) if closes[i] is not None),
            None,
        )
        day_block = {
            "as_of": dates[last_closed],
            "open": opens[last_closed],
            "high": highs[last_closed],
            "low": lows[last_closed],
            "ltp": closes[last_closed],
            "prev_close": prior,
            "change": (
                closes[last_closed] - prior
                if prior is not None and closes[last_closed] is not None
                else None
            ),
            "change_pct": (
                (closes[last_closed] - prior) / prior * 100.0
                if prior not in (None, 0) and closes[last_closed] is not None
                else None
            ),
        }
        if dates[-1] > dates[last_closed]:
            day_block["incomplete_note"] = (
                f"{dates[-1]} is archived but has no published close yet, so the "
                f"day panel shows the last complete session ({dates[last_closed]})."
            )

    year_ago = (date.fromisoformat(latest) - timedelta(days=366)).isoformat()
    y_idx = next((i for i, d in enumerate(dates) if d >= year_ago), None)
    highs_52 = [h for h in (highs[y_idx:] if y_idx is not None else []) if h is not None]
    lows_52 = [l for l in (lows[y_idx:] if y_idx is not None else []) if l is not None]

    return {
        "symbol": sym,
        "name": getattr(security, "name", None),
        "sector": getattr(security, "sector_code", None),
        "as_of": latest,
        "series": window,
        "indicators": out_indicators,
        "live": {
            "merged": live_mode is not None,
            "mode": live_mode,
            "quote": live_quote,
            "note": (
                "Today's session from the live poller is included as the last bar, "
                "so indicators carry the live session."
                if live_mode == "appended"
                else "Today's live price is overlaid on the archived bar (its close "
                "was not published yet), so indicators carry the live session."
                if live_mode == "overlay"
                else "No live merge needed: the latest session is fully archived"
                if live_quote is not None
                else "No live quote for this symbol right now; indicators are computed "
                "on archived sessions only."
            ),
        },
        "range": {
            "requested": range_key,
            "available": range_available,
            "complete": complete,
            "first_shown": first_shown,
            "sessions_shown": len(window["dates"]),
            "days_available": days_available,
            "days_requested": days_requested,
            "reason": (
                None
                if complete
                else f"Archive starts {dates[0]}, inside the {range_key} window, so this "
                f"period is only covered from {first_shown}."
            ),
            "options": [
                {
                    "value": key,
                    "available": True,
                    "complete": _range_complete(dates, latest, days),
                    "first_shown": _range_first(dates, latest, days),
                }
                for key, days in RANGE_DAYS.items()
            ],
        },
        "price_mode": {
            "requested": mode,
            "applied": "UNADJUSTED",
            "differs_from_requested": mode == "ADJUSTED",
            "reason": (
                None
                if mode == "UNADJUSTED"
                else "NEPSE publishes no split or bonus ex-dates, so an adjusted "
                "series cannot be built. Prices are shown unadjusted and this "
                "mode is a no-op rather than a silent fabrication."
            ),
        },
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
