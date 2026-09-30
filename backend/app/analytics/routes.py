"""Analytics routes: indicators over archived bars.

Every field in a response is a `Measured`, so the frontend never has to guess
whether `null` means "not enough history", "not published" or "fetch failed".
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.analytics.indicators import (
    Bar,
    accumulation_distribution_line,
    atr,
    awesome_oscillator,
    bollinger_on_valid,
    cci,
    chaikin_money_flow,
    chaikin_oscillator,
    chaikin_volatility,
    demark_pivots,
    donchian,
    ease_of_movement,
    ema_on_valid,
    fibonacci_extension,
    fibonacci_fan,
    fibonacci_retracement,
    force_index,
    historical_volatility,
    keltner,
    klinger_oscillator,
    macd_on_valid,
    money_flow_index,
    momentum,
    obv,
    pivot_points,
    camarilla_pivots,
    stochastic,
    stdev_series,
    supertrend,
    tsi,
    ultimate_oscillator,
    volume_price_trend,
    volume_oscillator,
    roc,
    rsi_on_valid,
    rvi,
    sma_on_valid,
    stoch_rsi,
    vwap,
    vwap_series,
    volume_sma_ratio,
    vwma,
    williams_r,
)
from app.archive.service import ArchiveService
from app.auth.deps import DbSession
from app.core.provenance import Measured
from app.db.session import SessionLocal
from app.nepse.registry import get_adapter
from app.nepse.service import validate_symbol

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# Shares the one process-wide NEPSE adapter with the archive, reference and
# legacy routers, so indicator routes cannot open a separate upstream session.
_archive = ArchiveService(get_adapter())


def _bars_from_rows(rows: list[Any]) -> list[Bar]:
    """Map `DailyBar` ORM rows to indicator inputs."""
    return [
        Bar(
            date=r.business_date,
            open=r.open,
            high=r.high,
            low=r.low,
            close=r.close,
            volume=float(r.volume) if r.volume is not None else None,
        )
        for r in rows
    ]


def _zip_dates(dates: list[str], series: list[Optional[float]]) -> list[dict]:
    return [{"date": d, "value": v} for d, v in zip(dates, series)]


@router.get("/indicators/{symbol}", summary="All indicators for one symbol")
async def indicators(
    symbol: str,
    session: DbSession,
    start: Optional[str] = Query(None, description="ISO date; defaults to everything archived"),
    end: Optional[str] = Query(None),
    limit: int = Query(500, ge=10, le=2000),
) -> dict[str, Any]:
    """Compute the indicator suite over the symbol's archived bars.

    Warm-up windows are `null` (not zero) because the indicator genuinely
    cannot be computed yet: RSI first appears on the 15th close, a 20-period
    Chaikin flow on the 20th bar, and so on.
    """
    sym = validate_symbol(symbol)
    rows = _archive.get_bars(session, sym, start=start, end=end, limit=limit)
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No archived bars for {sym}. The archive may not have been "
                f"backfilled yet - try POST /api/archive/backfill."
            ),
        )

    bars = _bars_from_rows(rows)
    dates = [b.date for b in bars]
    closes: list[Optional[float]] = [b.close for b in bars]
    rsi_14 = rsi_on_valid(closes, 14)
    macd_line, macd_signal, macd_hist = macd_on_valid(closes)
    bb_mid, bb_up, bb_lo, bb_bw, bb_pctb = bollinger_on_valid(closes, 20, 2.0)
    sma_20 = sma_on_valid(closes, 20)
    ema_20 = ema_on_valid(closes, 20)
    ad_line = accumulation_distribution_line(bars)
    obv_series = obv(bars)
    cmf_20 = chaikin_money_flow(bars, 20)
    mfi_14 = money_flow_index(bars, 14)
    atr_14 = atr(bars, 14)
    vw = vwap_series(bars)
    vol_ratio = volume_sma_ratio(bars, 20)

    # -- Trading Indicators notes: the wider suite --------------------------
    stoch_k, stoch_d = stochastic(bars, 14, 3)
    stochrsi = stoch_rsi(closes, 14, 14)
    cci_20 = cci(bars, 20)
    willr_14 = williams_r(bars, 14)
    mom_10 = momentum(closes, 10)
    uo = ultimate_oscillator(bars, 7, 14, 28)
    ao = awesome_oscillator(bars, 5, 34)
    tsi_line = tsi(closes, 25, 13)
    rvi_line, rvi_signal = rvi(bars)
    sd_20 = stdev_series(closes, 20)
    kc_mid, kc_up, kc_lo = keltner(bars, 20, 2.0, 10)
    dc_up, dc_lo, dc_mid = donchian(bars, 20)
    hv_20 = historical_volatility(closes, 20, 252)
    cv = chaikin_volatility(bars, 10, 10)
    vpt_line = volume_price_trend(bars)
    emv_14 = ease_of_movement(bars, 14)
    fi_13 = force_index(bars, 13)
    vo = volume_oscillator(bars, 5, 20)
    kvo = klinger_oscillator(bars, 34, 55)
    cho = chaikin_oscillator(bars, 3, 10)
    vwma_20 = vwma(closes, [b.volume for b in bars], 20)
    piv = pivot_points(bars)
    cam = camarilla_pivots(bars)
    fbr = fibonacci_retracement(bars)
    fex = fibonacci_extension(bars)
    ffa = fibonacci_fan(bars)
    sup = supertrend(bars, 10, 3.0)

    return {
        "symbol": sym,
        "as_of": dates[-1],
        "sessions": len(dates),
        "first": dates[0],
        "price": {
            "dates": dates,
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": closes,
            "volume": [b.volume for b in bars],
        },
        "indicators": {
            "sma_20": _zip_dates(dates, sma_20),
            "ema_20": _zip_dates(dates, ema_20),
            "rsi_14": _zip_dates(dates, rsi_14),
            "macd": _zip_dates(dates, macd_line),
            "macd_signal": _zip_dates(dates, macd_signal),
            "macd_histogram": _zip_dates(dates, macd_hist),
            "bb_upper": _zip_dates(dates, bb_up),
            "bb_middle": _zip_dates(dates, bb_mid),
            "bb_lower": _zip_dates(dates, bb_lo),
            "bb_bandwidth_pct": _zip_dates(dates, bb_bw),
            "bb_percent_b": _zip_dates(dates, bb_pctb),
            "accumulation_distribution": _zip_dates(dates, ad_line),
            "obv": _zip_dates(dates, obv_series),
            "chaikin_money_flow_20": _zip_dates(dates, cmf_20),
            "money_flow_index_14": _zip_dates(dates, mfi_14),
            "atr_14": _zip_dates(dates, atr_14),
            "vwap": _zip_dates(dates, vw),
            "volume_vs_20d_pct": _zip_dates(dates, vol_ratio),
            "roc_1": _zip_dates(dates, roc(closes, 1)),
            # Momentum (notes)
            "stoch_k": _zip_dates(dates, stoch_k),
            "stoch_d": _zip_dates(dates, stoch_d),
            "stoch_rsi": _zip_dates(dates, stochrsi),
            "cci_20": _zip_dates(dates, cci_20),
            "williams_r_14": _zip_dates(dates, willr_14),
            "momentum_10": _zip_dates(dates, mom_10),
            "ultimate_osc": _zip_dates(dates, uo),
            "awesome_osc": _zip_dates(dates, ao),
            "tsi": _zip_dates(dates, tsi_line),
            "rvi": _zip_dates(dates, rvi_line),
            "rvi_signal": _zip_dates(dates, rvi_signal),
            # Volatility (notes)
            "stdev_20": _zip_dates(dates, sd_20),
            "keltner_upper": _zip_dates(dates, kc_up),
            "keltner_middle": _zip_dates(dates, kc_mid),
            "keltner_lower": _zip_dates(dates, kc_lo),
            "donchian_upper": _zip_dates(dates, dc_up),
            "donchian_middle": _zip_dates(dates, dc_mid),
            "donchian_lower": _zip_dates(dates, dc_lo),
            "historical_vol_20": _zip_dates(dates, hv_20),
            "chaikin_volatility": _zip_dates(dates, cv),
            # Volume (notes)
            "vpt": _zip_dates(dates, vpt_line),
            "emv_14": _zip_dates(dates, emv_14),
            "force_index_13": _zip_dates(dates, fi_13),
            "volume_osc": _zip_dates(dates, vo),
            "klinger": _zip_dates(dates, kvo),
            "chaikin_osc": _zip_dates(dates, cho),
            "vwma_20": _zip_dates(dates, vwma_20),
            "supertrend": _zip_dates(dates, sup),
            # Pivots / Fibonacci (notes)
            "pivot_pp": _zip_dates(dates, piv["pp"]),
            "pivot_r1": _zip_dates(dates, piv["r1"]),
            "pivot_r2": _zip_dates(dates, piv["r2"]),
            "pivot_s1": _zip_dates(dates, piv["s1"]),
            "pivot_s2": _zip_dates(dates, piv["s2"]),
            "cam_pp": _zip_dates(dates, cam["pp"]),
            "cam_r3": _zip_dates(dates, cam["r3"]),
            "cam_r4": _zip_dates(dates, cam["r4"]),
            "cam_s3": _zip_dates(dates, cam["s3"]),
            "cam_s4": _zip_dates(dates, cam["s4"]),
            "fib_618": _zip_dates(dates, fbr["fib_618"]),
            "fibe_1618": _zip_dates(dates, fex["fibe_1618"]),
            "fibf_500": _zip_dates(dates, ffa["fibf_500"]),
        },
        "notes": {
            "unavailable": (
                "A null value means the indicator is undefined for that bar - "
                "insufficient history, or a day with no volume. It is not zero."
            ),
            "adjusted_prices": (
                "Prices are raw. NEPSE publishes no split/bonus-adjusted series, "
                "and an adjusted close cannot be built reliably without ex-dates."
            ),
            "broker_flow": (
                "Per-broker Accumulation & Distribution is not available: NEPSE's "
                "floorsheet leaves broker fields null and ignores its own broker filter."
            ),
            "order_flow": (
                "CVD here is the daily close-to-close proxy (see its definition), and "
                "Open Interest is not implemented: it counts outstanding derivative "
                "contracts, which NEPSE's equity feed does not publish. Returning a "
                "fabricated series would be worse than an honest absence."
            ),
        },
    }


@router.get("/summary/{symbol}", summary="Latest indicator readings with provenance")
async def summary(symbol: str, session: DbSession) -> dict[str, Any]:
    """Latest value of each indicator, each as a self-explaining `Measured`."""
    sym = validate_symbol(symbol)
    rows = _archive.get_bars(session, sym, limit=400)
    if not rows:
        raise HTTPException(
            status_code=404, detail=f"No archived bars for {sym} yet."
        )
    bars = _bars_from_rows(rows)
    closes = [b.close for b in bars]
    as_of = bars[-1].date

    def _last(series: list[Optional[float]]) -> Measured[float]:
        value = series[-1] if series else None
        if value is None:
            return Measured.missing(
                source="derived",
                as_of=as_of,
                note="Not enough archived history for this indicator yet.",
            )
        return Measured.of(value, source="derived", as_of=as_of)

    macd_line, macd_signal, macd_hist = macd_on_valid(closes)
    bb_mid, bb_up, bb_lo, _bw, pctb = bollinger_on_valid(closes, 20, 2.0)

    return {
        "symbol": sym,
        "as_of": as_of,
        "close": Measured.of(closes[-1], source="nepse:today-price", as_of=as_of),
        "rsi_14": _last(rsi_on_valid(closes, 14)),
        "macd": _last(macd_line),
        "macd_signal": _last(macd_signal),
        "macd_histogram": _last(macd_hist),
        "sma_20": _last(sma_on_valid(closes, 20)),
        "ema_20": _last(ema_on_valid(closes, 20)),
        "bb_upper": _last(bb_up),
        "bb_middle": _last(bb_mid),
        "bb_lower": _last(bb_lo),
        "bb_percent_b": _last(pctb),
        "accumulation_distribution": _last(accumulation_distribution_line(bars)),
        "obv": _last(obv(bars)),
        "chaikin_money_flow_20": _last(chaikin_money_flow(bars, 20)),
        "money_flow_index_14": _last(money_flow_index(bars, 14)),
        "atr_14": _last(atr(bars, 14)),
        "session_vwap": Measured.of(vwap([bars[-1]]), source="derived", as_of=as_of),
        "volume_vs_20d_pct": _last(volume_sma_ratio(bars, 20)),
    }


class CompareRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=1, max_length=4)
    start: Optional[str] = None
    end: Optional[str] = None
    normalize: bool = Field(
        True, description="Rebase each series to 100 at the first common date"
    )


@router.post("/compare", summary="Compare 2-4 symbols on a rebased scale")
async def compare(payload: CompareRequest, session: DbSession) -> dict[str, Any]:
    """Compare symbols over a shared date axis.

    With `normalize=true` each series is rebased to 100 at the first date it
    has data, so relative performance is comparable regardless of price level.
    """
    symbols = [validate_symbol(s) for s in payload.symbols]
    series: dict[str, list[Optional[float]]] = {}
    all_dates: set[str] = set()
    for sym in symbols:
        rows = _archive.get_bars(session, sym, start=payload.start, end=payload.end)
        closes = [r.close for r in rows]
        if not closes or all(c is None for c in closes):
            continue
        if payload.normalize:
            base = next((c for c in closes if c), None)
            closes = [None if c is None or not base else (c / base) * 100.0 for c in closes]
        series[sym] = closes
        all_dates.update(r.business_date for r in rows)

    dates = sorted(all_dates)
    if not dates:
        raise HTTPException(
            status_code=404, detail="None of the requested symbols have archived bars yet."
        )
    return {
        "dates": dates,
        "normalize": payload.normalize,
        "base": 100 if payload.normalize else None,
        "series": {sym: values for sym, values in series.items()},
        "missing": [s for s in symbols if s not in series],
    }
