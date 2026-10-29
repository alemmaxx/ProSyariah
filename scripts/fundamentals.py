"""Robot 5: maklumat asas syarikat (P/E, dividen, margin untung, ROE, hutang, nilai pasaran).

Disimpan dalam data/fund.json (repo) dan disalin ke <out>/fund.json.
Setiap larian mengemas kini ~150 saham patuh syariah yang paling lama tidak dikemas kini,
jadi semua saham dikemas kini setiap beberapa hari. Sumber: Yahoo Finance (indikatif).
"""
import argparse
import json
import math
import os
import time
from datetime import datetime, timezone

ROOT = os.path.join(os.path.dirname(__file__), "..")
STORE = os.path.join(ROOT, "data", "fund.json")
PER_RUN = 150


def num(x, mul=1.0, nd=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return round(x * mul, nd)


def main():
    import yfinance as yf

    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "_site", "data"))
    a = ap.parse_args()
    M = json.load(open(os.path.join(a.out, "market.json")))
    stocks = M["stocks"]
    store = json.load(open(STORE)) if os.path.exists(STORE) else {"items": {}}
    items = store.get("items", {})
    comp = [c for c, v in stocks.items() if v.get("s") == "ok" and v.get("c")]
    # saham dengan isyarat aktif dahulu, kemudian yang paling lama tidak dikemas kini
    act = {c for c in comp if any((o.get("ago") or 0) <= 2 for o in stocks[c].get("op", []))}
    order = sorted(comp, key=lambda c: (0 if c in act and items.get(c, {}).get("at", "") < M["meta"]["asof"] else 1, items.get(c, {}).get("at", "")))
    todo = order[:PER_RUN]
    ok = 0
    for c in todo:
        try:
            info = yf.Ticker(c + ".KL").info or {}
        except Exception as e:
            print("  gagal", c, e)
            time.sleep(1)
            continue
        f = {
            "pe": num(info.get("trailingPE"), nd=1),
            "pb": num(info.get("priceToBook"), nd=2),
            "dy": num(info.get("trailingAnnualDividendYield"), 100, 2),
            "pm": num(info.get("profitMargins"), 100, 1),
            "roe": num(info.get("returnOnEquity"), 100, 1),
            "de": num(info.get("debtToEquity"), nd=1),
            "rg": num(info.get("revenueGrowth"), 100, 1),
            "eg": num(info.get("earningsGrowth"), 100, 1),
            "mc": num(info.get("marketCap"), nd=0),
            "sec": info.get("sector") or None,
            "at": M["meta"]["asof"],
        }
        if any(v is not None for k, v in f.items() if k not in ("at", "sec")):
            items[c] = {k: v for k, v in f.items() if v is not None}
            ok += 1
        else:
            items.setdefault(c, {})["at"] = M["meta"]["asof"]
        time.sleep(0.6)
    out = {"asof": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "items": items}
    json.dump(out, open(STORE, "w"), ensure_ascii=False, separators=(",", ":"))
    json.dump(out, open(os.path.join(a.out, "fund.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    print(f"✓ Maklumat asas: {ok}/{len(todo)} dikemas kini, {len(items)} saham dalam simpanan")


if __name__ == "__main__":
    main()
