"""Eksperimen: adakah Isyarat Kuat lebih baik bila pasaran (KLCI) sedang menaik?

Dipanggil oleh market.py seminggu sekali. Tidak mengubah isyarat app — hanya menulis
data/regime-experiment.json untuk dinilai dahulu.
Keadaan pasaran pada hari isyarat: menaik = KLCI > purata 50 hari > purata 200 hari,
menurun = KLCI < purata 50 < purata 200, selain itu mendatar.
"""
import json
import os
from datetime import date

import paper

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "data", "regime-experiment.json")


def due():
    if not os.path.exists(OUT):
        return True
    try:
        return (date.today() - date.fromisoformat(json.load(open(OUT)).get("asof", ""))).days >= 7
    except Exception:
        return True


def states(K):
    cl = [x[1] for x in K]
    out = {}
    for i in range(200, len(K)):
        c, m50, m200 = cl[i], sum(cl[i - 49:i + 1]) / 50, sum(cl[i - 199:i + 1]) / 200
        out[K[i][0]] = "naik" if c > m50 > m200 else ("turun" if c < m50 < m200 else "datar")
    return out


def run(runs, px, compliant, K, asof):
    st = states(K)
    if not st:
        return
    days = sorted(st)
    def at(d):
        prev = [x for x in days if x <= d]
        return st[prev[-1]] if prev else None
    res = {}
    for name, kw in {"semua": dict(max_open=0), "isyarat_kuat": dict(only_a=True, max_open=0)}.items():
        h = paper.historical(runs, px, compliant, **kw)
        if not h:
            continue
        by = {"naik": [], "datar": [], "turun": []}
        for t in h["all"]:
            s = at(t["d"])
            if s:
                by[s].append(t)
        res[name] = {k: paper._summary(v) for k, v in by.items()}
        print(f"  Rejim {name}: " + ", ".join(f"{k} {v.get('n')} dag. {v.get('avg')}%" for k, v in res[name].items()))
    json.dump({"asof": asof, "note": "avg = purata pulangan setiap dagangan (%) selepas kos", "results": res}, open(OUT, "w"), indent=1)
