"""Robot 2: tarik harga semua saham Bursa, kira indicator, tulis fail data untuk app.

Output (dalam folder --out, cth. _site/data):
  market.json      ringkasan semua saham: status syariah, harga, sparkline, skor, RSI ...
  s/<kod>.json     sejarah harga ~2 tahun setiap saham (dibuka bila pengguna lihat carta)
  sc-list.json     salinan senarai SC

Penyedia harga:
  yfinance (lalai, percuma)  atau  EODHD (set PRICE_PROVIDER=eodhd + EODHD_API_KEY)
Senarai kod saham KLSE: EODHD exchange-symbol-list (perlu EODHD_API_KEY, 1 panggilan).
"""
import argparse
import json
import math
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(__file__))
from common import analyze, norm_name  # noqa: E402
import backtest as BT  # noqa: E402
import track  # noqa: E402
import paper  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
SC = os.path.join(ROOT, "data", "sc-list.json")
SYMBOLS = os.path.join(ROOT, "data", "klse-symbols.json")
KEY = os.environ.get("EODHD_API_KEY", "").strip()
PROVIDER = os.environ.get("PRICE_PROVIDER", "yfinance").lower()
MIN_PRICE = 0.20        # buang saham "penny" (spread besar)
MIN_VALUE = 100_000     # nilai dagangan purata 20 hari minimum (RM)
CODE_RE = re.compile(r"^\d{4,5}(EA)?$")  # saham, REIT, ETF; buang waran & lain-lain


def eod(path, **params):
    params.update(api_token=KEY, fmt="json")
    for attempt in range(3):
        r = requests.get(f"https://eodhd.com/api/{path}", params=params, timeout=60)
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()


def update_symbols():
    if not KEY:
        print("! EODHD_API_KEY tiada — guna senarai simbol sedia ada.")
        return
    data = eod("exchange-symbol-list/KLSE")
    syms = [{"code": str(x["Code"]), "name": x.get("Name") or "", "type": x.get("Type") or ""} for x in data]
    syms = [s for s in syms if CODE_RE.match(s["code"])]
    if len(syms) < 300:
        print(f"! Senarai simbol terlalu pendek ({len(syms)}) — tidak ditulis.")
        return
    syms.sort(key=lambda s: s["code"])
    json.dump(syms, open(SYMBOLS, "w"), ensure_ascii=False, indent=0)
    print(f"✓ {len(syms)} simbol KLSE")


def load_sc():
    if not os.path.exists(SC):
        return None, None
    st = json.load(open(SC))
    if not st.get("lists"):
        return st, None
    L = st["lists"][-1]
    return st, ({c for c in L.get("codes", {})}, {norm_name(n) for n in L["names"]})


# ETF & REIT Islam di Bursa: diluluskan berasingan (bukan dalam senarai saham patuh SC), jadi ditanda patuh di sini
ISLAMIC = {
    "0821EA": ("Eq8 Dow Jones Islamic Market Malaysia Titans 25 ETF", "etf"),
    "0824EA": ("Eq8 MSCI Malaysia Islamic Dividend ETF", "etf"),
    "0825EA": ("Eq8 MSCI SEA Islamic Dividend ETF", "etf"),
    "0827EA": ("Eq8 Dow Jones US Titans 50 ETF", "etf"),
    "0828EA": ("TradePlus Shariah Gold Tracker", "etf"),
    "0838EA": ("VP-DJ Shariah China A-Shares 100 ETF", "etf"),
    "0839EA": ("Eq8 FTSE Malaysia Enhanced Dividend Waqf ETF", "etf"),
    "5116": ("Al-'Aqar Healthcare REIT", "reit"),
    "5106": ("Axis REIT", "reit"),
    "5235SS": ("KLCC Property Holdings (KLCC REIT)", "reit"),
    "5269": ("Al-Salam REIT", "reit"),
}


def status(code, name, sc):
    if code in ISLAMIC:
        return "ok"
    if not sc:
        return "na"
    codes, names = sc
    return "ok" if code in codes or norm_name(name) in names else "no"


def prices_yf(codes):
    import yfinance as yf

    out = {}
    for i in range(0, len(codes), 150):
        chunk = codes[i : i + 150]
        tick = [c + ".KL" for c in chunk]
        for attempt in range(3):
            try:
                df = yf.download(tick, period="5y", interval="1d", group_by="ticker", auto_adjust=True,
                                 threads=True, progress=False)
                break
            except Exception as e:  # rangkaian / had kadar
                print("  cuba semula:", e)
                time.sleep(10)
        else:
            continue
        for c, t in zip(chunk, tick):
            try:
                sub = df[t] if len(tick) > 1 else df
                sub = sub.dropna(subset=["Close"])
            except Exception:
                continue
            if len(sub) < 5:
                continue
            out[c] = [
                [ix.strftime("%Y-%m-%d"), r.Open, r.High, r.Low, r.Close, 0 if math.isnan(r.Volume) else r.Volume]
                for ix, r in sub.iterrows()
            ]
        print(f"  harga {min(i + 150, len(codes))}/{len(codes)}")
        time.sleep(2)
    return out


def prices_eodhd(codes):
    out = {}
    frm = (date.today() - timedelta(days=1900)).isoformat()
    for i, c in enumerate(codes):
        try:
            data = eod(f"eod/{c}.KLSE", **{"from": frm})
            rows = [[b["date"], b["open"], b["high"], b["low"], b.get("adjusted_close") or b["close"], b["volume"]]
                    for b in data if b.get("close")]
            if len(rows) >= 5:
                out[c] = rows
        except Exception as e:
            print("  gagal", c, e)
        if i % 100 == 0:
            print(f"  harga {i}/{len(codes)}")
    return out


def r3(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "_site", "data"))
    ap.add_argument("--symbols-only", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="untuk ujian: had bilangan saham")
    a = ap.parse_args()

    update_symbols()
    if a.symbols_only:
        return
    if not os.path.exists(SYMBOLS):
        raise SystemExit("GAGAL: data/klse-symbols.json tiada. Tetapkan secret EODHD_API_KEY.")
    syms = json.load(open(SYMBOLS))
    if a.limit:
        syms = syms[: a.limit]
    st, sc = load_sc()
    if st and st.get("lists"):
        have = {s["code"] for s in syms}
        extra = [{"code": c, "name": n, "type": "SC"} for c, n in st["lists"][-1].get("codes", {}).items()
                 if c not in have and CODE_RE.match(c)]
        syms = syms + extra  # cth. saham pasaran LEAP: tiada harga, tetapi status syariah tetap dipaparkan
    have = {s["code"] for s in syms}
    syms = syms + [{"code": c, "name": n, "type": k.upper()} for c, (n, k) in ISLAMIC.items() if c not in have]
    codes = [s["code"] for s in syms if s.get("type") != "SC"]
    print(f"Tarik harga {len(codes)} kaunter guna {PROVIDER} …")
    px = prices_eodhd(codes) if PROVIDER == "eodhd" and KEY else prices_yf(codes)
    # Abaikan bar hari ini jika robot berjalan sebelum pasaran Bursa tutup (harga separuh hari)
    myt = datetime.now(timezone(timedelta(hours=8)))
    if (myt.hour, myt.minute) < (17, 30):
        today_myt = myt.date().isoformat()
        px = {c: [r for r in rows if r[0] < today_myt] for c, rows in px.items()}
        px = {c: rows for c, rows in px.items() if len(rows) >= 5}
        print(f"Sebelum pasaran tutup ({myt:%H:%M} MYT) — bar {today_myt} diabaikan")
    if len(px) < max(5, len(codes) * 0.3):
        raise SystemExit(f"GAGAL: hanya {len(px)} kaunter ada harga. Data lama tidak diganti.")

    os.makedirs(os.path.join(a.out, "s"), exist_ok=True)

    # --- Backtest semua saham (laluan 1), kumpul statistik pasaran sebagai "prior" ---
    print("Backtest persediaan beli …")
    runs, glob = {}, {k: [] for k in BT.SETUPS}
    for c, rows in px.items():
        o = [float(r[1] or r[4]) for r in rows]; hh = [float(r[2] or r[4]) for r in rows]
        ll = [float(r[3] or r[4]) for r in rows]; cc = [float(r[4]) for r in rows]; vv = [float(r[5] or 0) for r in rows]
        if len(cc) < 260:
            continue
        R = BT.run(o, hh, ll, cc, vv)
        runs[c] = R
        for k, tr in R["trades"].items():
            glob[k] += tr
    gstats = {k: BT.stats(tr) for k, tr in glob.items()}
    prior = {k: (st["w"] / st["n"] if st["n"] else 0.35) for k, st in gstats.items()}

    stocks = {}
    for s in syms:
        c = s["code"]
        rows = px.get(c)
        st_ = status(c, s["name"], sc)
        item = {"n": ISLAMIC[c][0] if c in ISLAMIC else s["name"], "s": st_}
        if c in ISLAMIC:
            item["k"] = ISLAMIC[c][1]
        bt = None
        if rows:
            closes = [float(r[4]) for r in rows]
            vols = [float(r[5] or 0) for r in rows]
            A = analyze(closes, vols)
            vals = [float(r[4]) * float(r[5] or 0) for r in rows[-20:]]
            avg_val = sum(vals) / len(vals) if vals else 0
            liq = closes[-1] >= MIN_PRICE and avg_val >= MIN_VALUE
            item["liq"] = 1 if liq else 0
            item["tv"] = round(avg_val)
            item.update({
                "d": rows[-1][0], "c": r3(closes[-1]),
                "ch": r3((closes[-1] / closes[-2] - 1) * 100) if len(closes) > 1 and closes[-2] else None,
                "sp": [r3(x) for x in closes[-40:]],
                **(A or {}),
            })
            R = runs.get(c)
            if R:
                bt = {}
                for k, tr in R["trades"].items():
                    stt = BT.stats(tr)
                    stt["p"] = round(BT.prob(stt, prior[k]) * 100)
                    stt["cf"] = BT.confidence(stt["n"])
                    bt[k] = stt
                ops = []
                for act in R["active"]:
                    k = act["k"]; stt = bt[k]
                    if k in BT.DISABLED:
                        continue
                    last = closes[-1]
                    ops.append({
                        "k": k, "p": stt["p"], "n": stt["n"], "w": stt["w"], "cf": stt["cf"],
                        "md": stt["md"] if stt["md"] is not None else gstats[k]["md"],
                        "d25": stt["d25"] if stt["d25"] is not None else gstats[k]["d25"],
                        "d75": stt["d75"] if stt["d75"] is not None else gstats[k]["d75"],
                        "ev": stt["ev"], "ago": act["t"],
                        "en": r3(last), "tg": r3(last * (1 + act["tp"])), "sl": r3(last * (1 - act["sp"])),
                    })
                if ops and liq:
                    ops.sort(key=lambda x: -x["p"])
                    item["op"] = ops
            keep = rows[-1300:]  # ~5 tahun: untuk carta bulanan & tahunan
            out = {"d": [r[0] for r in keep], "o": [r3(r[1]) for r in keep], "h": [r3(r[2]) for r in keep],
                   "l": [r3(r[3]) for r in keep], "c": [r3(r[4]) for r in keep], "v": [int(r[5] or 0) for r in keep]}
            if bt:
                out["bt"] = bt
                out["atr"] = r3(R["atr"])
            json.dump(out, open(os.path.join(a.out, "s", f"{c}.json"), "w"), separators=(",", ":"))
        stocks[c] = item
    asof = max((v.get("d", "") for v in stocks.values()), default="")
    track.update(px, stocks, asof, a.out)
    paper.build(runs, px, stocks, asof, a.out)
    try:
        import exits
        if exits.due():
            exits.run(px, {c for c, v in stocks.items() if v.get("s") == "ok"}, asof)
    except Exception as e:
        print("! Eksperimen cara keluar gagal:", e)
    meta = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "asof": asof, "provider": PROVIDER if not (PROVIDER == "eodhd" and not KEY) else "yfinance",
        "count": len(stocks), "priced": len(px),
        "scDate": st["lists"][-1]["date"] if st and st.get("lists") else None,
        "bt": {"h": BT.H, "tgt": BT.TGT_ATR, "stp": BT.STP_ATR, "fee": BT.FEE},
        "setups": {k: {"name": BT.SETUPS[k], "n": g["n"], "p": round(prior[k] * 100), "md": g["md"],
                       "d25": g["d25"], "d75": g["d75"], "ev": g["ev"]} for k, g in gstats.items()},
    }
    json.dump({"meta": meta, "stocks": stocks}, open(os.path.join(a.out, "market.json"), "w"),
              ensure_ascii=False, separators=(",", ":"))
    if st:
        json.dump(st, open(os.path.join(a.out, "sc-list.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    ok = sum(1 for v in stocks.values() if v["s"] == "ok")
    print(f"✓ market.json: {len(stocks)} kaunter, {len(px)} berharga, {ok} patuh syariah, data setakat {asof}")


if __name__ == "__main__":
    main()
