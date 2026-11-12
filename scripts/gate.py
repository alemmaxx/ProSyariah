"""Pintu larian berjadual: jika data hari dagangan terkini sudah ada, larian ini tidak perlu.
Cetak 'go=1' atau 'go=0' (untuk GITHUB_OUTPUT)."""
import json
import os
from datetime import datetime, timedelta, timezone

ROOT = os.path.join(os.path.dirname(__file__), "..")


def expected_day(now):
    try:
        hol = set(json.load(open(os.path.join(ROOT, "data", "holidays.json"))).get("days", []))
    except Exception:
        hol = set()
    is_td = lambda d: d.weekday() < 5 and d.isoformat() not in hol
    d = now.date()
    if not (is_td(d) and (now.hour, now.minute) >= (18, 0)):
        d -= timedelta(days=1)
        while not is_td(d):
            d -= timedelta(days=1)
    return d.isoformat()


def main():
    now = datetime.now(timezone(timedelta(hours=8)))
    try:
        asof = json.load(open(os.path.join(ROOT, "data", "market-meta.json"))).get("asof", "")
    except Exception:
        asof = ""
    exp = expected_day(now)
    sat = now.weekday() == 5   # Sabtu: semak senarai SC
    go = sat or asof < exp
    print(f"MYT {now:%Y-%m-%d %H:%M} · data {asof} · perlu {exp} → {'jalan' if go else 'tidak perlu (data sudah terkini)'}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        open(out, "a").write(f"go={'1' if go else '0'}\n")


if __name__ == "__main__":
    main()
