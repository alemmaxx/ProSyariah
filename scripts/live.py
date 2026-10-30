"""Robot 9: harga terkini (lewat ±15 minit) untuk SEMUA kaunter, dalam waktu pasaran.

Output: data/live.json  {"t": "YYYY-MM-DD HH:MM" (MYT), "d": "YYYY-MM-DD", "p": {kod: [harga, %ubah, tinggi, rendah]}}
%ubah dikira berbanding harga tutup hari dagangan sebelumnya (dari data harian app).
App guna fail ini untuk paparan "harga terkini" sahaja; isyarat & Robot tetap guna harga tutup harian.
"""
import json
import math
import os
import time
from datetime import datetime, timedelta, timezone

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "data", "live.json")
MYT = timezone(timedelta(hours=8))


def ok(x):
    return x is not None and not (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))


def main():
    import requests
    import yfinance as yf

    # senarai kaunter & harga tutup semalam dari data harian yang sudah diterbitkan
    M = None
    for url in ["https://alemmaxx.github.io/ProSyariah/data/market.json", "https://prosyariah.web.app/data/market.json"]:
        try:
            r = requests.get(url, params={"t": int(time.time())}, timeout=60)
            if r.ok:
                M = r.json()
                break
        except Exception as e:
            print("  gagal", url, e)
    if not M:
        raise SystemExit("market.json tidak dapat dibaca")
    st = M["stocks"]
    codes = [c for c, v in st.items() if v.get("c") is not None]
    now = datetime.now(MYT)
    out, last_ts = {}, ""
    for i in range(0, len(codes), 150):
        chunk = codes[i:i + 150]
        tick = [c + ".KL" for c in chunk]
        df = None
        for attempt in range(3):
            try:
                df = yf.download(tick, period="5d", interval="15m", group_by="ticker", auto_adjust=False, threads=True, progress=False)
                break
            except Exception as e:
                print("  cuba semula:", e)
                time.sleep(8)
        if df is None:
            continue
        for c, t in zip(chunk, tick):
            try:
                sub = (df[t] if len(tick) > 1 else df).dropna(subset=["Close"])
            except Exception:
                continue
            if sub.empty:
                continue
            idx = sub.index.tz_convert("Asia/Kuala_Lumpur") if sub.index.tz is not None else sub.index
            day = idx[-1].strftime("%Y-%m-%d")
            if day <= st[c].get("d", ""):
                continue  # tiada dagangan baharu selepas harga tutup terakhir
            today = sub[[x.strftime("%Y-%m-%d") == day for x in idx]]
            px = float(today["Close"].iloc[-1])
            prev = st[c].get("c")
            hi, lo = float(today["High"].max()), float(today["Low"].min())
            if not (ok(px) and prev):
                continue
            out[c] = [round(px, 4), round((px / prev - 1) * 100, 2), round(hi, 4) if ok(hi) else None, round(lo, 4) if ok(lo) else None]
            ts = idx[-1].strftime("%Y-%m-%d %H:%M")
            last_ts = max(last_ts, ts)
        print(f"  {min(i + 150, len(codes))}/{len(codes)}")
        time.sleep(1)
    res = {"t": last_ts or now.strftime("%Y-%m-%d %H:%M"), "d": (last_ts or now.strftime("%Y-%m-%d"))[:10],
           "gen": now.strftime("%Y-%m-%d %H:%M"), "p": out}
    json.dump(res, open(OUT, "w"), separators=(",", ":"))
    print(f"✓ Harga terkini: {len(out)} kaunter, setakat {res['t']} MYT")


if __name__ == "__main__":
    main()
