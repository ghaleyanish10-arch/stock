"""Verify the archive-grade accessors against live NEPSE.

Checks the three things the backfill depends on:
  1. a good date returns rows;
  2. a holiday returns 0 rows *without* raising;
  3. an out-of-window date RAISES (so it is never mistaken for a holiday).
"""

import asyncio
import json
import sys

sys.path.insert(0, ".")

from app.nepse.client import NepseClientAdapter  # noqa: E402
from app.nepse.exceptions import NepseServiceError  # noqa: E402

OUT = r"C:\Users\LENOVO\AppData\Local\Temp\opencode\verify_archive_accessors.json"


async def main() -> None:
    c = NepseClientAdapter()
    await c.start()
    report: dict = {}

    # 1. known-good historical session
    env = c.get_today_price_page("2025-12-01")
    content = env.get("content", []) if isinstance(env, dict) else []
    report["2025-12-01"] = {
        "ok": True,
        "rows": len(content),
        "totalPages": env.get("totalPages") if isinstance(env, dict) else None,
        "sample_keys": sorted(content[0].keys()) if content else [],
        "sample": content[0] if content else None,
    }

    # 2. known holiday (Dashain, verified non-session in probe 4)
    try:
        env2 = c.get_today_price_page("2025-10-21")
        c2 = env2.get("content", []) if isinstance(env2, dict) else []
        report["2025-10-21"] = {"ok": True, "rows": len(c2), "is_empty": len(c2) == 0}
    except NepseServiceError as exc:
        report["2025-10-21"] = {"ok": False, "raised": type(exc).__name__, "msg": str(exc)}

    # 3. outside NEPSE's window -> must RAISE, not return empty
    try:
        env3 = c.get_today_price_page("2025-08-24")
        c3 = env3.get("content", []) if isinstance(env3, dict) else []
        report["2025-08-24"] = {
            "ok": True,
            "rows": len(c3),
            "WARNING": "returned empty instead of raising - archive would treat as holiday",
        }
    except NepseServiceError as exc:
        report["2025-08-24"] = {"ok": False, "raised": type(exc).__name__, "msg": str(exc)[:200]}

    # 4. holiday list
    try:
        hol = c.get_holidays(2025)
        report["holidays_2025"] = {"ok": True, "count": len(hol), "sample": hol[:3]}
    except Exception as exc:
        report["holidays_2025"] = {"ok": False, "err": str(exc)[:200]}

    # 5. per-security price history depth
    try:
        p0 = c.get_security_price_history(131, page=0)
        p2 = c.get_security_price_history(131, page=2)
        p3 = c.get_security_price_history(131, page=3)
        report["sec_price_131"] = {
            "ok": True,
            "page0": len(p0),
            "page0_first": p0[0] if p0 else None,
            "page0_last": p0[-1] if p0 else None,
            "page2": len(p2),
            "page3": len(p3),
        }
    except Exception as exc:
        report["sec_price_131"] = {"ok": False, "err": str(exc)[:200]}

    # 6. secondary archive source
    try:
        d = c.get_security_daily_trades("2025-12-01")
        dc = d.get("content", []) if isinstance(d, dict) else []
        report["daily_trades_2025-12-01"] = {
            "ok": True,
            "rows": len(dc),
            "sample_keys": sorted(dc[0].keys()) if dc else [],
        }
    except Exception as exc:
        report["daily_trades_2025-12-01"] = {"ok": False, "err": str(exc)[:200]}

    await c.close()
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(json.dumps(report, indent=2, default=str)[:4000])


asyncio.run(main())
