"""STEP 0.2 evidence probe: which disputed NEPSE fields actually exist?

Runs each disputed field against the live API through the application's own
paced, auth-hardened adapter (never raw requests), and records for each probe:
HTTP/parse outcome, payload shape, row count, keys, and a sample row. The
result is written to `scripts/probe_results.json` so docs/data-sources.md can
cite it.

    ./.venv/Scripts/python.exe scripts/probe_data_sources.py

Probes cover: security detail (promoter/public split + listed shares),
corporate actions (cash/bonus/book closure/AGM), the legacy
application/dividend + application/agm endpoints, company news, market-wide
news and alerts, market depth, and the candidate "adjusted history" endpoints
that would make ADJUSTED candles possible.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.nepse.registry import get_adapter  # noqa: E402

RESULTS_PATH = Path(__file__).with_name("probe_results.json")


def shape_of(payload: Any, depth: int = 0) -> dict[str, Any]:
    """A compact structural summary safe to commit as evidence."""
    if isinstance(payload, dict):
        return {
            "type": "dict",
            "keys": sorted(map(str, payload.keys()))[:40],
        }
    if isinstance(payload, list):
        first = payload[0] if payload else None
        return {
            "type": "list",
            "count": len(payload),
            "first_row_keys": sorted(map(str, first.keys()))[:40]
            if isinstance(first, dict)
            else None,
            "first_row": _clip(first),
        }
    return {"type": type(payload).__name__, "repr": _clip(payload)}


def _clip(value: Any, limit: int = 600) -> Any:
    if isinstance(value, dict):
        return {k: _clip(v) for k, v in list(value.items())[:24]}
    if isinstance(value, list):
        return [_clip(v) for v in value[:2]]
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


async def probe(
    adapter: Any,
    results: dict[str, Any],
    name: str,
    operation: str,
    fn: Any,
) -> None:
    try:
        payload = await adapter.call(operation, fn)
        results[name] = {"ok": True, **shape_of(payload)}
    except Exception as exc:  # noqa: BLE001 - the failure IS the evidence
        results[name] = {
            "ok": False,
            "error_class": type(exc).__name__,
            "error": str(exc)[:300],
        }


async def main() -> None:
    adapter = get_adapter()
    await adapter.start()
    results: dict[str, Any] = {
        "probed_at_utc": datetime.now(timezone.utc).isoformat(),
        "note": "All probes ran through app.nepse (paced adapter), not raw requests.",
    }

    # Anchor symbol: NABIL, security id 131 (verified earlier phases).
    master = await adapter.call("probe:security-master", adapter.get_security_master)
    ids = {
        str(row.get("symbol")).upper(): row.get("id")
        for row in (master if isinstance(master, list) else [])
        if isinstance(row, dict) and row.get("symbol")
    }
    results["security_master"] = {
        "rows": len(master) if isinstance(master, list) else None,
        "nabil_id": ids.get("NABIL"),
    }
    sid = ids.get("NABIL") or 131

    await probe(
        adapter, results, "security_detail__promoter_public_split",
        f"probe:security-detail:{sid}", lambda: adapter.get_security_detail_enriched(sid),
    )
    await probe(
        adapter, results, "corporate_actions__dividend_bonus_bookclose_agm",
        f"probe:corporate-actions:{sid}", lambda: adapter.get_corporate_actions(sid),
    )
    await probe(
        adapter, results, "legacy_application_dividend",
        f"probe:application-dividend:{sid}", lambda: adapter.get_json(f"application/dividend/{sid}"),
    )
    await probe(
        adapter, results, "legacy_application_agm",
        f"probe:application-agm:{sid}", lambda: adapter.get_json(f"application/agm/{sid}"),
    )
    await probe(
        adapter, results, "company_news",
        f"probe:company-news:{sid}", lambda: adapter.get_json(f"application/company-news/{sid}"),
    )
    await probe(
        adapter, results, "market_news_and_alerts",
        "probe:news-and-alerts", lambda: adapter.get_json("news/media/news-and-alerts"),
    )
    await probe(
        adapter, results, "market_depth",
        f"probe:marketdepth:{sid}", lambda: adapter.get_json(f"nepse-data/marketdepth/{sid}"),
    )
    # Adjusted-history candidates. graphdata is the library's candle endpoint
    # (known to 500); the others are candidates for "day-wise price adjustment
    # history" that would let ADJUSTED candles be derived.
    await probe(
        adapter, results, "adjusted_history__graphdata",
        f"probe:graphdata:{sid}",
        lambda: adapter.get_json(
            f"market/graphdata/{sid}?start=2026-08-28&end=2026-09-28"
        ),
    )
    await probe(
        adapter, results, "adjusted_history__daywiseadjprice_symbol",
        "probe:daywiseadjprice:symbol",
        lambda: adapter.get_json("market/daywiseadjprice?symbol=NABIL&size=10"),
    )
    await probe(
        adapter, results, "adjusted_history__daywiseadjprice_id",
        f"probe:daywiseadjprice:id:{sid}",
        lambda: adapter.get_json(f"market/daywiseadjprice/{sid}?size=10"),
    )
    await probe(
        adapter, results, "adjusted_history__nepse_data_daywiseadjprice",
        "probe:nd-daywiseadjprice",
        lambda: adapter.get_json("nepse-data/daywiseadjprice?symbol=NABIL&size=10"),
    )

    RESULTS_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")
    for name, res in results.items():
        if name in ("probed_at_utc", "note") or "ok" not in res:
            continue
        if res.get("ok"):
            print(f"OK    {name}: {res['type']}"
                  + (f", {res['count']} rows" if res.get("count") is not None else ""))
        else:
            print(f"FAIL  {name}: {res['error_class']}: {res['error'][:120]}")


if __name__ == "__main__":
    asyncio.run(main())
