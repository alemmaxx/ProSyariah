"""Robot 7: kalendar cuti Bursa Malaysia secara automatik (tahun lepas, tahun ini & tahun depan).

Sumber: pustaka exchange_calendars (kalendar XKLS — Bursa Malaysia), yang dikemas kini bila Bursa
mengumumkan cuti. Setiap larian robot memasang versi terkini, jadi senarai 2027 akan masuk sendiri.
Output: data/holidays.json (repo) dan <out>/holidays.json (app).
"""
import argparse
import json
import os
from datetime import date, timedelta

ROOT = os.path.join(os.path.dirname(__file__), "..")
STORE = os.path.join(ROOT, "data", "holidays.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "_site", "data"))
    a = ap.parse_args()
    old = json.load(open(STORE)) if os.path.exists(STORE) else {"days": []}
    days = set(old.get("days", []))
    y = date.today().year
    try:
        import exchange_calendars as xc
        cal = xc.get_calendar("XKLS", start=f"{y - 1}-01-01", end=f"{y + 1}-12-31")
        sessions = {d.strftime("%Y-%m-%d") for d in cal.sessions}
        d, end = date(y - 1, 1, 1), date(y + 1, 12, 31)
        last_session = max(sessions)
        while d <= end:
            iso = d.isoformat()
            if d.weekday() < 5 and iso not in sessions and iso <= last_session:
                days.add(iso)
            d += timedelta(days=1)
        print(f"✓ Cuti Bursa: {len(days)} hari (sehingga {last_session})")
    except Exception as e:
        print("! exchange_calendars gagal, senarai lama dikekalkan:", e)
    out = {"asof": date.today().isoformat(), "days": sorted(days)}
    json.dump(out, open(STORE, "w"), indent=0)
    os.makedirs(a.out, exist_ok=True)
    json.dump(out, open(os.path.join(a.out, "holidays.json"), "w"), separators=(",", ":"))


if __name__ == "__main__":
    main()
