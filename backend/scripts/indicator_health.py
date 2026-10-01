"""Indicator health sweep: every registered token, three symbols, one table.

Dev script (committed): requests every token the frontend registry offers for
the user's symbol plus one liquid and one thin symbol, and writes
docs/indicator-health.md with, per token and symbol:

* HTTP status of the combined-token request (falls back to per-token requests
  to isolate a token that breaks the whole response),
* how many payload series the token produced and how many points are non-null,
* the first valid index (warm-up length),
* flags: all-null / all-zero / constant / NaN,
* whether the frontend registry's expected series keys match the response,
* the backend `disabled` reason when a token legitimately cannot produce data.

Run with the backend already serving (default http://127.0.0.1:8000):

    python scripts/indicator_health.py [--base URL] [--symbols ANLB,NHPC,BNT]

Exit code is non-zero when any token is broken (non-200, all-null without a
disabled reason, or a registry mismatch), so CI can call it too.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND_REGISTRY = ROOT / "frontend" / "src" / "indicators.ts"
BACKEND_CHART = ROOT / "backend" / "app" / "analytics" / "chart.py"
OUTPUT = ROOT / "docs" / "indicator-health.md"

#: Second symbol passed as compare= so the correlation/ratio/spread/compare
#: family gets real data instead of its "needs a comparison symbol" reason.
COMPARE_PARTNERS = {
    "ANLB": "NHPC",
    "NHPC": "AKJCL",
    "BNT": "RBCL",
}


def load_frontend_registry() -> tuple[list[str], dict[str, list[str]]]:
    """Parse the token union and each def's expected series keys."""
    text = FRONTEND_REGISTRY.read_text(encoding="utf-8")
    union = re.search(r"export type IndicatorToken =(.*?);", text, re.S)
    if not union:
        raise SystemExit("cannot find IndicatorToken union in indicators.ts")
    tokens = re.findall(r'"([a-z0-9_]+)"', union.group(1))
    defs: dict[str, list[str]] = {}
    for m in re.finditer(r"\{\s*key:\s*\"([a-z0-9_]+)\".*?series:\s*\[([^\]]*)\]", text, re.S):
        defs[m.group(1)] = re.findall(r'"([a-z0-9_]+)"', m.group(2))
    return tokens, defs


def backend_tokens() -> set[str]:
    """Token names with an `if "<token>" in wanted` handler in chart.py."""
    text = BACKEND_CHART.read_text(encoding="utf-8")
    return set(re.findall(r'if\s+"([a-z0-9_]+)"\s+in\s+wanted', text))


def fetch_json(base: str, path: str, timeout: float) -> tuple[int, object | None]:
    url = base.rstrip("/") + path
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
        return time.perf_counter() - t0, json.loads(
            body, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(f"NaN/Infinity: {c}"))
        )
    except urllib.error.HTTPError as e:
        return time.perf_counter() - t0, {"_http_status": e.code}
    except Exception as e:  # noqa: BLE001 - report anything, never crash the sweep
        return time.perf_counter() - t0, {"_error": str(e)}


def analyse_token(
    token: str,
    expected_keys: list[str],
    payload: dict,
) -> dict:
    """Judge one token against one response payload."""
    out: dict = {"token": token, "ok": True, "notes": []}
    ind = payload.get("indicators", {})
    disabled = payload.get("disabled", {})
    n_dates = len(payload.get("series", {}).get("dates", []))

    got_keys = [k for k in expected_keys if k in ind]
    if not got_keys:
        reason = disabled.get(token)
        if reason:
            # Healthy by design: the backend explains why there is no data
            # (needs a compare symbol, not applicable for NEPSE, ...). The UI
            # surfaces this in the legend; not a broken token.
            out["status"] = "not_applicable"
            out["notes"].append(reason)
            return out
        out["ok"] = False
        out["notes"].append("no series in response and no disabled reason")
        out["status"] = "missing"
        return out

    total_nonnull = 0
    first_valid = n_dates
    flags = set()
    for k in got_keys:
        series = ind[k]
        if len(series) != n_dates:
            out["ok"] = False
            out["notes"].append(f"{k}: length {len(series)} != dates {n_dates}")
        nonnull = [i for i, v in enumerate(series) if v is not None]
        total_nonnull += len(nonnull)
        if nonnull:
            first_valid = min(first_valid, nonnull[0])
        vals = [v for v in series if v is not None]
        if not vals:
            flags.add("all-null")
        elif all(v == 0 for v in vals):
            flags.add("all-zero")
        elif len(set(vals)) == 1:
            flags.add("constant")
    missing_keys = [k for k in expected_keys if k not in ind]
    if missing_keys:
        # Partial emission (e.g. a family that only emits on some branches).
        out["notes"].append(f"series absent: {','.join(missing_keys)}")
        out["ok"] = False
    out.update(
        status="ok",
        series=len(got_keys),
        nonnull=total_nonnull,
        first_valid=None if first_valid == n_dates else first_valid,
        flags=sorted(flags),
    )
    if "all-null" in flags:
        out["ok"] = False
        out["notes"].append("all values null")
    if not out["ok"]:
        out["status"] = "flagged"
    return out


def sweep_symbol(base: str, symbol: str, tokens: list[str], defs: dict[str, list[str]], timeout: float):
    partner = COMPARE_PARTNERS.get(symbol)
    path = (
        f"/api/analytics/chart/{symbol}?range=ALL&indicators={','.join(tokens)}"
        + (f"&compare={partner}" if partner else "")
    )
    elapsed, payload = fetch_json(base, path, timeout)
    status = payload.get("_http_status", 200) if isinstance(payload, dict) else 200
    rows = []
    if status != 200 or not isinstance(payload, dict) or "indicators" not in payload:
        # Isolate the culprit(s) with per-token requests.
        detail = (payload or {}).get("_error") or (payload or {}).get("detail") or "non-200"
        rows.append({"symbol": symbol, "token": "<ALL>", "status": f"HTTP {status}: {detail}", "ok": False,
                     "notes": ["combined request failed"], "series": 0, "nonnull": 0,
                     "first_valid": None, "flags": ["combined-failure"], "elapsed": elapsed})
        for t in tokens:
            iso = f"/api/analytics/chart/{symbol}?range=ALL&indicators={t}"
            if partner:
                iso += f"&compare={partner}"
            e1, p1 = fetch_json(base, iso, timeout)
            s1 = p1.get("_http_status", 200) if isinstance(p1, dict) else 200
            if s1 != 200 or not isinstance(p1, dict) or "indicators" not in p1:
                rows.append({"symbol": symbol, "token": t, "status": f"HTTP {s1}", "ok": False,
                             "notes": [str((p1 or {}).get("detail") or (p1 or {}).get("_error") or "")],
                             "series": 0, "nonnull": 0, "first_valid": None,
                             "flags": ["http-error"], "elapsed": e1})
                continue
            r = analyse_token(t, defs.get(t, []), p1)
            r.update(symbol=symbol, elapsed=e1)
            rows.append(r)
        return rows, elapsed

    for t in tokens:
        r = analyse_token(t, defs.get(t, []), payload)
        r.update(symbol=symbol, elapsed=None)
        rows.append(r)
    return rows, elapsed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--symbols", default="ANLB,NHPC,BNT")
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()

    tokens, defs = load_frontend_registry()
    be = backend_tokens()
    print(f"frontend registry: {len(tokens)} tokens; backend handlers found: {len(be)}")

    all_rows: list[dict] = []
    for symbol in [s.strip().upper() for s in args.symbols.split(",") if s.strip()]:
        rows, elapsed = sweep_symbol(args.base, symbol, tokens, defs, args.timeout)
        print(f"{symbol}: {len(rows)} tokens in {elapsed:.2f}s, "
              f"{sum(1 for r in rows if not r['ok'])} not ok")
        all_rows.extend(rows)

    # Registry cross-check: frontend token without a backend handler is a
    # silent dead button (this is exactly how `mfi` broke).
    mismatches = [t for t in tokens if t not in be]
    unhandled_frontend = [r for r in all_rows if r["token"] in mismatches and not r["ok"]]

    broken = [r for r in all_rows if not r["ok"]]

    # -- markdown ------------------------------------------------------------
    lines = [
        "# Indicator health",
        "",
        f"Generated by `backend/scripts/indicator_health.py` — every token in the frontend",
        f"registry ({len(tokens)} tokens) requested for {', '.join(args.symbols.split(','))} "
        f"(user's symbol, one liquid, one thin), range=ALL, "
        f"compare partner where applicable. Re-run the script to refresh.",
        "",
        "A blank/absent value is warm-up (undefined), never zero. `disabled` rows carry the",
        "backend's provenance reason and are healthy by design.",
        "",
    ]
    for symbol in [s.strip().upper() for s in args.symbols.split(",") if s.strip()]:
        lines += [
            f"## {symbol}",
            "",
            "| token | status | series | non-null | first valid idx | flags | notes |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for r in [x for x in all_rows if x["symbol"] == symbol]:
            notes = "; ".join(r.get("notes", []))
            lines.append(
                f"| {r['token']} | {r['status']} | {r.get('series', '')} "
                f"| {r.get('nonnull', '')} | {r.get('first_valid', '') if r.get('first_valid') is not None else ''} "
                f"| {','.join(r.get('flags', []))} | {notes} |"
            )
        lines.append("")
    if mismatches:
        lines += [
            "## Registry mismatches",
            "",
            "Frontend tokens with no `if \"<token>\" in wanted` handler in chart.py",
            "(a click on these used to do nothing):",
            "",
            *[f"- `{t}`" for t in mismatches],
            "",
        ]
    lines += [
        "## Verdict",
        "",
        f"- tokens swept: {len(tokens)} x {len(args.symbols.split(','))} symbols",
        f"- broken rows (no data without a reason): {len(broken)}",
        f"- frontend tokens missing a backend handler: {len(mismatches)}",
        "",
    ]
    if broken:
        lines += ["Broken rows:", ""]
        lines += [f"- `{r['symbol']}/{r['token']}`: {'; '.join(r.get('notes', [])) or r['status']}" for r in broken]
        lines.append("")

    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUTPUT}")
    if broken or unhandled_frontend:
        print(f"NOT OK: {len(broken)} broken rows, {len(unhandled_frontend)} registry mismatches")
        return 1
    print("all tokens healthy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
