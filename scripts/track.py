"""Rekod prestasi isyarat secara langsung (forward test).

Setiap hari, setiap "Peluang beli" baharu (patuh syariah, pulangan purata sejarah positif)
direkod dalam data/signals.json. Hari-hari berikutnya robot semak harga sebenar:
  beli = harga buka hari dagangan selepas isyarat
  MENANG jika harga tinggi capai sasaran, KALAH jika harga rendah capai had rugi
  (kedua-dua pada hari sama = KALAH), TAMAT MASA selepas 40 hari dagangan.
Ringkasan diterbitkan ke track.json untuk app.
"""
import json
import os
from datetime import date, timedelta

import backtest as BT

ROOT = os.path.join(os.path.dirname(__file__), "..")
LOG = os.path.join(ROOT, "data", "signals.json")


def load():
    if os.path.exists(LOG):
        return json.load(open(LOG))
    return {"open": [], "closed": []}


def resolve(sig, rows):
    """rows = senarai [tarikh, o, h, l, c, v] menaik. Pulangkan sig dikemas kini (atau None jika masih terbuka)."""
    after = [r for r in rows if r[0] > sig["d"]]
    if not after:
        return None
    entry = float(after[0][1] or after[0][4])
    sig["entry"] = round(entry, 4)
    for i, r in enumerate(after[: BT.H]):
        lo, hi = float(r[3] or r[4]), float(r[2] or r[4])
        if lo <= sig["sl"]:
            return {**sig, "res": "L", "days": i + 1, "exit": sig["sl"], "end": r[0]}
        if hi >= sig["tg"]:
            return {**sig, "res": "W", "days": i + 1, "exit": sig["tg"], "end": r[0]}
    if len(after) >= BT.H:
        r = after[BT.H - 1]
        return {**sig, "res": "T", "days": BT.H, "exit": float(r[4]), "end": r[0]}
    return None


def ret(s):
    return round((s["exit"] / s["entry"] - 1 - BT.FEE) * 100, 2)


def summarise(closed, since=None):
    xs = [s for s in closed if not since or s["end"] >= since]
    n = len(xs)
    if not n:
        return {"n": 0}
    w = sum(1 for s in xs if s["res"] == "W")
    l = sum(1 for s in xs if s["res"] == "L")
    rets = [s["ret"] for s in xs]
    exp = round(sum(s["p"] for s in xs) / n)
    return {"n": n, "w": w, "l": l, "to": n - w - l, "win": round(w / n * 100), "exp": exp,
            "avg": round(sum(rets) / n, 2), "tot": round(sum(rets), 1),
            "days": round(sum(s["days"] for s in xs) / n, 1)}


def update(prices, stocks, today_str, out_dir):
    st = load()
    keep_open, newly = [], []
    for sig in st["open"]:
        rows = prices.get(sig["c"])
        res = resolve(dict(sig), rows) if rows else None
        if res:
            res["ret"] = ret(res)
            newly.append(res)
        else:
            keep_open.append(sig)
    have = {(s["c"], s["k"], s["d"]) for s in keep_open + st["closed"] + newly}
    added = 0
    for code, v in stocks.items():
        if v.get("s") != "ok" or not v.get("op"):
            continue
        for op in v["op"]:
            if op.get("ago") != 0 or not op.get("ev") or op["ev"] <= 0:
                continue
            key = (code, op["k"], v["d"])
            if key in have:
                continue
            keep_open.append({"c": code, "n": v["n"], "k": op["k"], "d": v["d"], "p": op["p"],
                              "en": op["en"], "tg": op["tg"], "sl": op["sl"], "md": op.get("md"),
                              "ns": op.get("n"), "ws": op.get("w"), "ev": op.get("ev")})
            added += 1
    closed = sorted(st["closed"] + newly, key=lambda s: s["end"])
    cutoff = (date.fromisoformat(today_str) - timedelta(days=730)).isoformat()
    closed = [s for s in closed if s["end"] >= cutoff]
    json.dump({"open": keep_open, "closed": closed}, open(LOG, "w"), ensure_ascii=False, separators=(",", ":"))

    t = date.fromisoformat(today_str)
    by_setup = {k: summarise([s for s in closed if s["k"] == k]) for k in BT.SETUPS}
    # Kalibrasi: adakah "60%" benar-benar menang ~60%?
    bands = []
    for lo, hi in [(0, 45), (45, 55), (55, 65), (65, 101)]:
        xs = [s for s in closed if lo <= s["p"] < hi]
        if xs:
            bands.append({"band": f"{lo}-{min(hi, 100)}", "n": len(xs), "exp": round(sum(s["p"] for s in xs) / len(xs)),
                          "act": round(sum(1 for s in xs if s["res"] == "W") / len(xs) * 100)})
    track = {
        "asof": today_str,
        "all": summarise(closed),
        "d30": summarise(closed, (t - timedelta(days=30)).isoformat()),
        "d90": summarise(closed, (t - timedelta(days=90)).isoformat()),
        "setups": by_setup,
        "calib": bands,
        "open": len(keep_open),
        "openList": sorted(keep_open, key=lambda s: s["d"], reverse=True)[:30],
        "recent": list(reversed(closed[-40:])),
        "started": min([s["d"] for s in keep_open + closed], default=today_str),
    }
    json.dump(track, open(os.path.join(out_dir, "track.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    print(f"✓ Rekod prestasi: +{added} isyarat baharu, {len(newly)} selesai, {len(keep_open)} masih terbuka, {len(closed)} selesai keseluruhan")
