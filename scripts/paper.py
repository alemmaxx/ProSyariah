"""Robot Auto: akaun latihan maya untuk "5 isyarat teknikal terkuat".

Tiada wang sebenar. Setiap kali satu isyarat masuk 5 terkuat, robot "melabur" nilai maya tetap
(STAKE, lalai RM20) dan keluar bila harga sampai paras atas (MENANG), paras bawah (KALAH),
atau selepas had masa (TAMAT). Paling banyak 5 kedudukan terbuka serentak, satu bagi setiap saham.

1) UJIAN SEJARAH (walk-forward, ~12 bulan): ulang setiap hari dagangan lalu. Pada setiap hari,
   kebarangkalian & pulangan purata dikira HANYA daripada dagangan yang sudah selesai sebelum hari itu,
   supaya tiada maklumat masa depan digunakan.
2) UJIAN LANGSUNG: bermula dari tarikh robot pertama kali berjalan; disimpan dalam data/paper-live.json.
Kos dagangan pergi-balik (backtest.FEE) ditolak daripada setiap pulangan.
"""
import json
import os
from bisect import bisect_left
from collections import defaultdict
from datetime import date, timedelta

import backtest as BT
import track

ROOT = os.path.join(os.path.dirname(__file__), "..")
LIVE = os.path.join(ROOT, "data", "paper-live.json")
STAKE = float(os.environ.get("PAPER_STAKE", "20"))
MAX_OPEN = 5
HIST_DAYS = 365


def _summary(trades):
    n = len(trades)
    if not n:
        return {"n": 0}
    w = sum(1 for t in trades if t["res"] == "W")
    l = sum(1 for t in trades if t["res"] == "L")
    pnl = sum(t["ret"] for t in trades) * STAKE / 100
    return {"n": n, "w": w, "l": l, "to": n - w - l, "win": round(w / n * 100, 1),
            "pnl": round(pnl, 2), "avg": round(sum(t["ret"] for t in trades) / n, 2),
            "days": round(sum(t["days"] for t in trades) / n, 1),
            "best": max(trades, key=lambda t: t["ret"])["ret"], "worst": min(trades, key=lambda t: t["ret"])["ret"]}


def _curve(trades):
    """Untung/rugi terkumpul ikut tarikh keluar."""
    out, cum = [], 0.0
    for t in sorted(trades, key=lambda t: t["exit"]):
        cum += t["ret"] * STAKE / 100
        if out and out[-1][0] == t["exit"]:
            out[-1][1] = round(cum, 2)
        else:
            out.append([t["exit"], round(cum, 2)])
    return out


def historical(runs, px, compliant, min_score=0):
    """Simulasi walk-forward 5 terkuat sepanjang HIST_DAYS lalu."""
    events = []
    for code, R in runs.items():
        if code not in compliant:
            continue
        dates = [r[0] for r in px[code]]
        for k, trs in R["trades"].items():
            for tr in trs:
                t = tr["t"]
                if t + tr["days"] >= len(dates):
                    continue
                score = tr.get("sc", 0)
                events.append({"code": code, "k": k, "sd": dates[t], "ed": dates[t + tr["days"]],
                               "res": tr["res"], "ret": tr["ret"] * 100, "days": tr["days"],
                               "tp": tr["tp"], "sp": tr["sp"], "sc": score})
    if not events:
        return None
    # indeks untuk kira statistik "setakat semalam"
    by_key, by_k = defaultdict(list), defaultdict(list)
    for e in events:
        by_key[(e["code"], e["k"])].append(e)
        by_k[e["k"]].append(e)
    def prep(lst):
        lst = sorted(lst, key=lambda e: e["ed"])
        eds, cw, cr = [], [0], [0.0]
        for e in lst:
            eds.append(e["ed"]); cw.append(cw[-1] + (e["res"] == "W")); cr.append(cr[-1] + e["ret"])
        return eds, cw, cr
    IK = {key: prep(v) for key, v in by_key.items()}
    IG = {k: prep(v) for k, v in by_k.items()}

    def stats_before(idx, d):
        eds, cw, cr = idx
        n = bisect_left(eds, d)
        return n, cw[n], cr[n]

    end = max(e["sd"] for e in events)
    start = (date.fromisoformat(end) - timedelta(days=HIST_DAYS)).isoformat()
    cands = defaultdict(list)
    for e in events:
        if e["sd"] < start or e["sc"] < min_score:
            continue
        n, w, rsum = stats_before(IK[(e["code"], e["k"])], e["sd"])
        gn, gw, _ = stats_before(IG[e["k"]], e["sd"])
        if n == 0 or rsum / n <= 0:      # sama seperti app: hanya isyarat dengan pulangan purata sejarah positif
            continue
        prior = gw / gn if gn else 0.35
        p = (w + BT.PRIOR_K * prior) / (n + BT.PRIOR_K)
        be = (e["sp"] + BT.FEE) / (e["tp"] + e["sp"])
        if p - be <= 0:
            continue
        cands[e["sd"]].append({**e, "p": round(p * 100), "edge": p - be})
    open_pos, done = [], []
    for d in sorted(cands):
        open_pos = [x for x in open_pos if x["ed"] > d]
        held = {x["code"] for x in open_pos}
        for c in sorted(cands[d], key=lambda x: -x["edge"]):
            if len(open_pos) >= MAX_OPEN:
                break
            if c["code"] in held:
                continue
            open_pos.append(c); held.add(c["code"])
            done.append({"c": c["code"], "k": c["k"], "d": c["sd"], "exit": c["ed"], "p": c["p"],
                         "res": c["res"], "ret": round(c["ret"], 2), "days": c["days"]})
    done = [t for t in done if t["exit"] <= end]
    return {"start": start, "end": end, "summary": _summary(done), "curve": _curve(done),
            "recent": sorted(done, key=lambda t: t["exit"], reverse=True)[:60],
            "bySetup": {k: _summary([t for t in done if t["k"] == k]) for k in BT.SETUPS}}


def live(prices, stocks, asof):
    st = json.load(open(LIVE)) if os.path.exists(LIVE) else {"started": asof, "open": [], "closed": []}
    still, newly = [], []
    for pos in st["open"]:
        rows = prices.get(pos["c"])
        res = track.resolve(dict(pos), rows) if rows else None
        if res:
            res["ret"] = round((res["exit"] / res["entry"] - 1 - BT.FEE) * 100, 2)
            newly.append(res)
        else:
            still.append(pos)
    held = {p["c"] for p in still}
    cands = []
    for code, v in stocks.items():
        if v.get("s") != "ok" or code in held:
            continue
        for op in v.get("op", []):
            if op.get("ago") != 0 or not op.get("ev") or op["ev"] <= 0:
                continue
            tp, sp = op["tg"] / op["en"] - 1, 1 - op["sl"] / op["en"]
            edge = op["p"] / 100 - (sp + BT.FEE) / (tp + sp)
            if edge > 0:
                cands.append((edge, code, v, op))
    for edge, code, v, op in sorted(cands, key=lambda x: -x[0]):
        if len(still) >= MAX_OPEN:
            break
        if code in held:
            continue
        still.append({"c": code, "n": v["n"], "k": op["k"], "d": v["d"], "p": op["p"], "en": op["en"],
                      "tg": op["tg"], "sl": op["sl"], "md": op.get("md")})
        held.add(code)
    closed = st["closed"] + newly
    st = {"started": st.get("started", asof), "open": still, "closed": closed}
    json.dump(st, open(LIVE, "w"), ensure_ascii=False, separators=(",", ":"))
    return {"started": st["started"], "summary": _summary(closed), "curve": _curve(closed),
            "open": still, "recent": sorted(closed, key=lambda t: t["end"], reverse=True)[:60]}


def build(runs, px, stocks, asof, out_dir):
    compliant = {c for c, v in stocks.items() if v.get("s") == "ok"}
    hist = historical(runs, px, compliant)
    hist3 = historical(runs, px, compliant, min_score=3)
    lv = live(px, stocks, asof)
    out = {"asof": asof, "stake": STAKE, "maxOpen": MAX_OPEN, "fee": BT.FEE, "hist": hist, "hist3": hist3, "live": lv,
           "names": {c: stocks[c]["n"] for c in {t["c"] for t in (hist["recent"] if hist else [])} | {p["c"] for p in lv["open"]} if c in stocks}}
    json.dump(out, open(os.path.join(out_dir, "paper.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    # ringkasan kecil dalam repo (untuk semakan tanpa membuka laman)
    json.dump({"asof": asof, "stake": STAKE, "hist": {k: hist[k] for k in ("start", "end", "summary", "bySetup")} if hist else None,
               "histScore3": {k: hist3[k] for k in ("summary", "bySetup")} if hist3 else None,
               "live": lv["summary"], "liveOpen": len(lv["open"])},
              open(os.path.join(ROOT, "data", "paper-summary.json"), "w"), ensure_ascii=False, indent=1)
    h = hist["summary"] if hist else {"n": 0}
    print(f"✓ Robot Auto: sejarah {h.get('n', 0)} dagangan maya, ketepatan {h.get('win', '-')}%, "
          f"untung/rugi RM{h.get('pnl', 0)} (RM{STAKE:.0f} setiap isyarat); langsung {len(lv['open'])} terbuka")
