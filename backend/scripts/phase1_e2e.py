"""End-to-end Phase 1 check against live NEPSE.

Runs the real pipeline - reference sync, backfill, indicators, as-of walk-back -
with no mocks, and writes the result to a JSON file for inspection.
"""

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, ".")

from sqlalchemy import delete, select  # noqa: E402

from app.archive.service import ArchiveService, DayState  # noqa: E402
from app.db.models import (  # noqa: E402
    BackfillRun,
    Broker,
    CorporateAction,
    DailyBar,
    FetchAttempt,
    Fund,
    Security,
    TradingDay,
    User,
    Watchlist,
)
from app.db.session import SessionLocal, engine, init_db  # noqa: E402
from app.nepse.client import NepseClientAdapter  # noqa: E402
from app.reference.service import ReferenceService  # noqa: E402

OUT = r"C:\Users\LENOVO\AppData\Local\Temp\opencode\phase1_e2e.json"


async def main() -> None:
    report: dict = {"steps": {}}

    # Fresh schema (the dev db predates the DailyBar composite-key fix).
    # create_all first, so the tables exist before we clear them.
    init_db()
    for model in (
        Watchlist, FetchAttempt, BackfillRun, DailyBar, TradingDay,
        CorporateAction, Fund, Broker, Security, User,
    ):
        with SessionLocal() as s:
            s.execute(delete(model))
            s.commit()
    report["steps"]["schema"] = "recreated"

    client = NepseClientAdapter()
    await client.start()
    ref = ReferenceService(client)
    archive = ArchiveService(client)

    with SessionLocal() as s:
        t0 = time.time()
        report["steps"]["reference_sync"] = {
            "securities": await ref.sync_securities(s),
            "sectors": await ref.sync_sectors(s),
            "brokers": await ref.sync_brokers(s),
        }
        # Per-symbol enrichment: sector, instrument type, listed shares.
        # C30MF is a real mutual fund (instrument type CDS); NABIL is equity;
        # ACLBSL is a laghubitta, which must NOT become a fund.
        report["steps"]["enrich"] = {}
        for sym in ("NABIL", "C30MF", "ACLBSL"):
            row = s.get(Security, sym)
            if row is not None and row.nepse_security_id is not None:
                report["steps"]["enrich"][sym] = await ref.enrich_security(s, sym)
        report["steps"]["funds"] = {
            "rows": ref.sync_funds_from_securities(s),
            "codes": [f.code for f in ref.list_funds(s)],
        }
        report["steps"]["reference_sync"]["seconds"] = round(time.time() - t0, 1)

        # A few real sessions around a holiday, to prove the three-way split.
        # `listed_shares` comes from the enrich step above, so an enriched
        # symbol gets a derived market cap and an unenriched one stays NULL.
        days = ["2026-09-24", "2026-09-23", "2026-09-22", "2026-09-21", "2026-09-20"]
        listed = archive._listed_shares_map(s)
        outcomes = []
        t0 = time.time()
        for d in days:
            oc = await archive.ingest_day(s, d, listed_shares=listed)
            outcomes.append({"date": d, "state": oc.state.value, "rows": oc.row_count,
                             "error": oc.error})
            await asyncio.sleep(0.4)
        report["steps"]["ingest"] = {
            "listed_shares_known": len(listed),
            "outcomes": outcomes,
            "seconds": round(time.time() - t0, 1),
        }

        report["steps"]["coverage"] = archive.coverage(s)

        # Dividend data for one symbol.
        nabil = s.get(Security, "NABIL")
        if nabil and nabil.nepse_security_id:
            report["steps"]["corporate_actions"] = {
                "symbol": "NABIL",
                "rows": await ref.sync_corporate_actions(
                    s, "NABIL", nabil.nepse_security_id
                ),
            }
            report["steps"]["dividends"] = [
                {
                    "fy": a.fiscal_year,
                    "cash": a.cash_dividend_pct,
                    "bonus": a.bonus_pct,
                    "cash_status": ref.dividend_measured(a, "cash").status.value,
                }
                for a in ref.corporate_actions(s, "NABIL")
            ]

        # Indicators over the bars we just stored.
        from app.analytics.indicators import (
            Bar, accumulation_distribution_line, chaikin_money_flow,
            money_flow_multiplier, obv, rsi,
        )

        rows = archive.get_bars(s, "NABIL", limit=100)
        if len(rows) >= 1:
            bars = [
                Bar(date=r.business_date, open=r.open, high=r.high, low=r.low,
                    close=r.close, volume=float(r.volume) if r.volume else None)
                for r in rows
            ]
            ad = accumulation_distribution_line(bars)
            cmf = chaikin_money_flow(bars, 5)
            report["steps"]["indicators"] = {
                "symbol": "NABIL",
                "bars": len(bars),
                "mfm_first": money_flow_multiplier(bars[0]),
                "mfm_none_count": sum(
                    1 for b in bars if money_flow_multiplier(b) is None
                ),
                "ad_line_last": ad[-1],
                "obv_last": obv(bars)[-1],
                "cmf5_last": cmf[-1],
                "rsi_needs_15": rsi([b.close for b in bars], 14)[-1] is None,
            }

        # Walk-back: ask for a date we have no data for.
        report["steps"]["resolve_as_of"] = {
            "asked_2026-09-25": archive.resolve_as_of(s, "2026-09-25"),
            "asked_2026-09-24": archive.resolve_as_of(s, "2026-09-24"),
            "asked_2026-12-31": archive.resolve_as_of(s, "2026-12-31"),
        }

        # Honest-absence checks.
        first_fund = s.scalar(select(Fund))
        if first_fund:
            measured = ref.fund_nav_measured(first_fund)
            report["steps"]["fund_nav"] = {
                "code": first_fund.code,
                "nav_value": measured.value,
                "nav_status": measured.status.value,
                "nav_label": measured.label,
                "nav_explain": measured.explain()[:160],
            }

        sample_broker = s.scalar(select(Broker))
        if sample_broker:
            report["steps"]["broker_sample"] = {
                "code": sample_broker.member_code,
                "name": sample_broker.member_name,
                "is_dealer": sample_broker.is_dealer,
                "province": sample_broker.province,
            }

        report["steps"]["sample_bar"] = None
        bar = s.scalar(select(DailyBar).limit(1))
        if bar:
            report["steps"]["sample_bar"] = {
                "date": bar.business_date, "symbol": bar.symbol,
                "o": bar.open, "h": bar.high, "l": bar.low, "c": bar.close,
                "vol": bar.volume, "turnover": bar.turnover, "mcap": bar.market_cap,
            }

    await client.close()
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(json.dumps(report, indent=2, default=str)[:6000])


asyncio.run(main())
