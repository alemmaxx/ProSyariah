"""Enjin backtest ProSyariah.

Untuk setiap saham, cari setiap kali sesuatu "persediaan beli" berlaku dalam sejarah, kemudian
simulasi dagangan: beli pada harga buka hari esoknya, jual bila
  (a) capai SASARAN  = harga beli + 2 x ATR14   -> MENANG
  (b) jatuh ke HAD RUGI = harga beli - 1.25 x ATR14 -> KALAH
  (c) tiada (a)/(b) dalam 40 hari dagangan        -> TAMAT MASA (jual pada harga tutup)
Jika (a) dan (b) berlaku pada hari yang sama, dikira KALAH (andaian konservatif).
Kos dagangan pergi-balik 0.3% ditolak daripada setiap pulangan.
"""
from statistics import median

from common import ema, ema_sparse, rsi

H = 40            # had masa (hari dagangan)
TGT_ATR = 2.0     # sasaran = 2 x ATR
STP_ATR = 1.25    # had rugi = 1.25 x ATR
FEE = 0.003       # kos broker + duti setem + yuran (anggaran pergi-balik)
COOLDOWN = 10     # jarak minimum antara 2 isyarat persediaan yang sama
PRIOR_K = 10      # kekuatan "prior" pasaran untuk saham bersampel kecil

SETUPS = {
    "pb": "Koreksi dalam trend menaik",   # harga > EMA200 dan RSI turun bawah 35
    "gc": "Golden cross",                 # EMA50 lintas atas EMA200
    "mc": "Momentum MACD",                # MACD lintas atas isyarat, harga > EMA50 & EMA200
    "os": "Lantunan lebih jualan",        # RSI turun bawah 30 (tanpa tapisan trend — lebih berisiko)
}


def atr(h, l, c, n=14):
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    o = [None] * len(c)
    if len(c) < n:
        return o
    a = sum(tr[:n]) / n
    o[n - 1] = a
    for i in range(n, len(c)):
        a = (a * (n - 1) + tr[i]) / n
        o[i] = a
    return o


def triggers(t, c, e50, e200, r, mac, sig):
    out = []
    ok = lambda *xs: all(x is not None for x in xs)
    if ok(e200[t], r[t], r[t - 1]) and c[t] > e200[t] and r[t] < 35 <= r[t - 1]:
        out.append("pb")
    if ok(e50[t], e200[t], e50[t - 1], e200[t - 1]) and e50[t - 1] <= e200[t - 1] and e50[t] > e200[t]:
        out.append("gc")
    if ok(mac[t], sig[t], mac[t - 1], sig[t - 1], e50[t], e200[t]) and mac[t - 1] <= sig[t - 1] and mac[t] > sig[t] \
            and c[t] > e50[t] and c[t] > e200[t]:
        out.append("mc")
    if ok(r[t], r[t - 1]) and r[t] < 30 <= r[t - 1]:
        out.append("os")
    return out


def levels(price, a):
    tp = min(max(TGT_ATR * a / price, 0.03), 0.25)
    sp = min(max(STP_ATR * a / price, 0.02), 0.15)
    return tp, sp


def simulate(t, o, h, l, c, a):
    n = len(c)
    if t + 1 >= n:
        return None
    e = o[t + 1] if o[t + 1] else c[t]
    tp, sp = levels(c[t], a)
    tgt, stp = e * (1 + tp), e * (1 - sp)
    for j in range(t + 1, min(n, t + 1 + H)):
        if l[j] <= stp:
            return {"res": "L", "days": j - t, "ret": -sp - FEE, "t": t, "tp": tp, "sp": sp}
        if h[j] >= tgt:
            return {"res": "W", "days": j - t, "ret": tp - FEE, "t": t, "tp": tp, "sp": sp}
    if t + H < n:
        return {"res": "T", "days": H, "ret": c[t + H] / e - 1 - FEE, "t": t, "tp": tp, "sp": sp}
    return None  # dagangan belum selesai — tidak dikira


def run(o, h, l, c, v):
    n = len(c)
    e50, e200, r = ema(c, 50), ema(c, 200), rsi(c, 14)
    e12, e26 = ema(c, 12), ema(c, 26)
    mac = [e12[i] - e26[i] if e12[i] is not None and e26[i] is not None else None for i in range(n)]
    sig = ema_sparse(mac, 9)
    A = atr(h, l, c)
    trades = {k: [] for k in SETUPS}
    last_t = {k: -999 for k in SETUPS}
    active = []
    for t in range(1, n):
        if A[t] is None:
            continue
        for k in triggers(t, c, e50, e200, r, mac, sig):
            if t - last_t[k] < COOLDOWN:
                continue
            last_t[k] = t
            if t >= n - 3:  # isyarat aktif (3 hari dagangan terakhir)
                tp, sp = levels(c[-1], A[-1])
                active.append({"k": k, "t": n - 1 - t, "tp": tp, "sp": sp})
            sim = simulate(t, o, h, l, c, A[t])
            if sim:
                trades[k].append(sim)
    return {"trades": trades, "active": active, "atr": A[-1], "close": c[-1]}


def stats(tr):
    n = len(tr)
    w = [x for x in tr if x["res"] == "W"]
    ls = [x for x in tr if x["res"] == "L"]
    to = [x for x in tr if x["res"] == "T"]
    wd = sorted(x["days"] for x in w)
    q = lambda p: wd[min(len(wd) - 1, int(p * len(wd)))] if wd else None
    return {
        "n": n, "w": len(w), "l": len(ls), "to": len(to),
        "md": median(wd) if wd else None, "d25": q(0.25), "d75": q(0.75),
        "ev": round(sum(x["ret"] for x in tr) / n * 100, 2) if n else None,
    }


def confidence(n):
    return "tinggi" if n >= 20 else "sederhana" if n >= 8 else "rendah"


def prob(st, prior):
    """Kebarangkalian menang dengan 'shrinkage' ke kadar pasaran bagi sampel kecil."""
    return (st["w"] + PRIOR_K * prior) / (st["n"] + PRIOR_K)
