"""Fungsi kongsi: normalisasi nama & indicator (sama logik dengan app index.html)."""
import re
from datetime import date, timedelta


def norm_name(n):
    s = str(n or "").upper()
    s = s.replace("&", " AND ")
    s = re.sub(r"\(M\)|\(MALAYSIA\)", " ", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\bBERHAD\b|\bBHD\b", " ", s)
    s = re.sub(r"\bHLDGS?\b", "HOLDINGS", s)
    s = re.sub(r"\bINTL\b", "INTERNATIONAL", s)
    s = re.sub(r"\bCORP\b", "CORPORATION", s)
    return re.sub(r"\s+", " ", s).strip()


def last_friday(y, m):
    d = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
    while d.weekday() != 4:
        d -= timedelta(days=1)
    return d


# ---------------- indicator (pariti dengan JS) ----------------
def ema(v, n):
    o = [None] * len(v)
    if len(v) < n:
        return o
    e = sum(v[:n]) / n
    o[n - 1] = e
    k = 2 / (n + 1)
    for i in range(n, len(v)):
        e = v[i] * k + e * (1 - k)
        o[i] = e
    return o


def ema_sparse(v, n):
    idx = [i for i, x in enumerate(v) if x is not None]
    e = ema([v[i] for i in idx], n)
    o = [None] * len(v)
    for j, i in enumerate(idx):
        o[i] = e[j]
    return o


def rsi(c, n=14):
    o = [None] * len(c)
    if len(c) <= n:
        return o
    g = l = 0.0
    for i in range(1, n + 1):
        d = c[i] - c[i - 1]
        if d >= 0:
            g += d
        else:
            l -= d
    g /= n
    l /= n
    o[n] = 100 if l == 0 else 100 - 100 / (1 + g / l)
    for i in range(n + 1, len(c)):
        d = c[i] - c[i - 1]
        g = (g * (n - 1) + max(d, 0)) / n
        l = (l * (n - 1) + max(-d, 0)) / n
        o[i] = 100 if l == 0 else 100 - 100 / (1 + g / l)
    return o


def analyze(c, v):
    """Pulangkan ringkasan skor teknikal untuk siri harga tutup harian c & volum v."""
    L = len(c) - 1
    if L < 1:
        return None
    e20, e50, e200, r = ema(c, 20), ema(c, 50), ema(c, 200), rsi(c, 14)
    e12, e26 = ema(c, 12), ema(c, 26)
    mac = [e12[i] - e26[i] if e12[i] is not None and e26[i] is not None else None for i in range(len(c))]
    sig = ema_sparse(mac, 9)
    avg_v = sum(v[L - 20:L]) / 20 if L >= 20 else None
    vr = v[L] / avg_v if avg_v else None
    checks = []
    if e200[L] is not None:
        checks.append(c[L] > e200[L])
    elif e50[L] is not None:
        checks.append(c[L] > e50[L])
    else:
        checks.append(None)
    checks.append(e20[L] > e50[L] if e20[L] is not None and e50[L] is not None else None)
    checks.append(mac[L] > sig[L] if mac[L] is not None and sig[L] is not None else None)
    if r[L] is not None:
        x = r[L]
        checks.append(True if x < 30 else False if x > 70 else x >= 50)
    else:
        checks.append(None)
    checks.append(vr > 1.2 and c[L] > c[L - 1] if vr is not None else None)
    cross = ""
    for i in range(max(1, L - 4), L + 1):
        if None not in (e50[i], e200[i], e50[i - 1], e200[i - 1]):
            if e50[i - 1] <= e200[i - 1] and e50[i] > e200[i]:
                cross = "g"
            if e50[i - 1] >= e200[i - 1] and e50[i] < e200[i]:
                cross = "d"
    return {
        "sc": sum(1 for x in checks if x is True),
        "va": sum(1 for x in checks if x is not None),
        "r": round(r[L], 1) if r[L] is not None else None,
        "e2": (c[L] > e200[L]) if e200[L] is not None else None,
        "m": (mac[L] > sig[L]) if mac[L] is not None and sig[L] is not None else None,
        "x": cross,
    }
