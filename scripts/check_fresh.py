"""Semak data harga terkini. Gagalkan job (supaya pemilik dapat emel GitHub) jika data lewat."""
import json
import os
from datetime import datetime, timedelta, timezone

ROOT = os.path.join(os.path.dirname(__file__), "..")


def main():
    meta = json.load(open(os.path.join(ROOT, "data", "market-meta.json")))
    try:
        hol = set(json.load(open(os.path.join(ROOT, "data", "holidays.json"))).get("days", []))
    except Exception:
        hol = set()
    is_td = lambda d: d.weekday() < 5 and d.isoformat() not in hol
    now = datetime.now(timezone(timedelta(hours=8)))
    d = now.date()
    # Hari dagangan sebelum hari ini mesti sudah ada (larian 6.30 ptg boleh lewat; larian 9.15 pagi menampung)
    d -= timedelta(days=1)
    while not is_td(d):
        d -= timedelta(days=1)
    asof = meta.get("asof", "")
    if asof < d.isoformat():
        print(f"::error::Data harga lewat: data terakhir {asof}, sepatutnya {d}. Robot akan cuba semula pada larian seterusnya.")
        raise SystemExit(1)
    print(f"✓ Data harga terkini ({asof})")


if __name__ == "__main__":
    main()
