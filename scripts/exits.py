"""Eksperimen: uji beberapa cara keluar (sasaran / cut loss dalam ATR, had hari) atas 3 tahun yang sama.

Dipanggil oleh market.py sekali seminggu (atau bila fail tiada). Tidak mengubah isyarat app —
hanya menulis data/exit-experiments.json untuk dinilai sebelum sebarang perubahan.
"""
import json
import os
import time
from datetime import date

import backtest as BT
import paper

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "data", "exit-experiments.json")
COMBOS = [(1.5, 1.0, 40), (2.0, 1.25, 40), (2.0, 2.0, 40), (3.0, 1.5, 40), (3.0, 1.0, 40), (2.0, 1.25, 20), (4.0, 2.0, 60)]


def due():
    if not os.path.exists(OUT):
        return True
    try:
        d = json.load(open(OUT)).get("asof", "")
        return (date.today() - date.fromisoformat(d)).days >= 7
    except Exception:
        return True


def run(px, compliant, asof):
    t0 = time.time()
    base = (BT.TGT_ATR, BT.STP_ATR, BT.H)
    res = {}
    try:
        for tg, st, hh in COMBOS:
            BT.TGT_ATR, BT.STP_ATR, BT.H = tg, st, hh
            runs = {}
            for c, rows in px.items():
                if c not in compliant or len(rows) < 260:
                    continue
                o = [float(r[1] or r[4]) for r in rows]; h = [float(r[2] or r[4]) for r in rows]
                l = [float(r[3] or r[4]) for r in rows]; cc = [float(r[4]) for r in rows]; v = [float(r[5] or 0) for r in rows]
                runs[c] = BT.run(o, h, l, cc, v)
            key = f"sasaran {tg}xATR / cut loss {st}xATR / {hh} hari"
            out = {}
            for name, kw in {"semua": dict(max_open=0), "isyarat_kuat": dict(only_a=True, max_open=0)}.items():
                hres = paper.historical(runs, px, compliant, **kw)
                if hres:
                    by = {}
                    for t in hres["all"]:
                        by.setdefault(t["exit"][:4], []).append(t)
                    out[name] = {"summary": hres["summary"], "years": {y: paper._summary(v) for y, v in sorted(by.items())}}
            res[key] = out
            print(f"  {key}: " + ", ".join(f"{n} {o['summary'].get('n')} dag. {o['summary'].get('avg')}%" for n, o in out.items()))
    finally:
        BT.TGT_ATR, BT.STP_ATR, BT.H = base
    json.dump({"asof": asof, "current": f"sasaran {base[0]}xATR / cut loss {base[1]}xATR / {base[2]} hari", "results": res},
              open(OUT, "w"), indent=1)
    print(f"✓ Eksperimen cara keluar siap ({time.time() - t0:.0f}s)")
