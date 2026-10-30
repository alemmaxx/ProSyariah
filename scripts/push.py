"""Robot 6: notifikasi push Robot Manual untuk semua pengguna yang log masuk.

Baca dokumen users/* dalam Firestore (data Robot Manual setiap pengguna), semak harga terkini,
dan hantar notifikasi melalui Firebase Cloud Messaging bila:
  sampai sasaran / kena cut loss / 40 hari tamat / hampir cut loss / tutup esok / tempoh biasa tamat.
Id amaran yang sudah dihantar disimpan dalam medan "sent" supaya tidak berulang.
Perlu GOOGLE_APPLICATION_CREDENTIALS (akaun servis Firebase).
"""
import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone

H, FEE = 40, 0.003


def fee_side(v, etf=False, free_comm=False):
    """Yuran moomoo MY + Bursa untuk SATU transaksi (beli ATAU jual) bernilai v RM.
    Komisen 0.03% (percuma 180 hari pengguna baharu), platform RM3, yuran penjelasan 0.03% (maks RM1,000),
    duti setem RM1 setiap RM1,000 atau sebahagian (maks RM200), SST 8% atas komisen+platform+penjelasan
    untuk ETF/REIT sahaja (saham biasa dikecualikan)."""
    import math
    comm = 0.0 if free_comm else math.ceil(v * 0.0003 * 100) / 100
    clear = min(round(v * 0.0003, 2), 1000.0)
    stamp = min(float(math.ceil(v / 1000.0)), 200.0)
    sst = round(0.08 * (comm + 3.0 + clear), 2) if etf else 0.0
    return round(comm + 3.0 + clear + stamp + sst, 2)


def pos_pnl(p, x):
    """Untung/rugi RM. Posisi mod moomoo (ada qty): nilai jual − yuran jual − kos (termasuk yuran beli)."""
    if p.get("qty"):
        return p["qty"] * x - fee_side(p["qty"] * x, p.get("etf"), p.get("fc")) - p["stake"]
    return (x / p["en"] - 1 - FEE) * p["stake"]


HOL = set()
try:
    HOL = set(json.load(open(os.path.join(os.path.dirname(__file__), "..", "data", "holidays.json")))["days"])
except Exception:
    pass


def add_td(d, n):
    """Tambah hari dagangan Bursa (langkau hujung minggu & cuti umum)."""
    x = date.fromisoformat(d)
    k = 0
    while k < n:
        x += timedelta(days=1)
        if x.weekday() < 5 and x.isoformat() not in HOL:
            k += 1
    return x.isoformat()


def fmt(d, en):
    x = date.fromisoformat(d)
    bm = ["Jan", "Feb", "Mac", "Apr", "Mei", "Jun", "Jul", "Ogo", "Sep", "Okt", "Nov", "Dis"]
    eg = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{x.day} {(eg if en else bm)[x.month - 1]} {x.year}"


def rm(v):
    return ("+" if v >= 0 else "−") + f"RM {abs(v):.2f}"


def alerts_for(p, M, out_dir, en):
    """Pulangkan senarai (id, tajuk, teks) untuk satu posisi terbuka."""
    v = M["stocks"].get(p["code"])
    if not v or v.get("c") is None:
        return []
    nm = p.get("name") or v.get("n") or p["code"]
    now, asof, base = v["c"], M["meta"]["asof"], f"man:{p['id']}:"
    Hp = int(p.get("hz") or H)  # Robot Auto: tutup bila tempoh isyarat tamat
    pnl = lambda x: pos_pnl(p, x)
    # semak paras atas/bawah dengan harga tinggi/rendah harian sejak masuk
    try:
        s = json.load(open(os.path.join(out_dir, "s", f"{p['code']}.json")))
        bars = [(d, s["h"][i], s["l"][i], s["c"][i]) for i, d in enumerate(s["d"])
                if (d >= p["d"] if p.get("inc") else d > p["d"])]
    except Exception:
        bars = []
    for i, (d, hi, lo, c) in enumerate(bars[:Hp]):
        if lo is not None and lo <= p["sl"]:
            return [(base + "L", f"{nm}: " + ("hit cut loss, force close" if en else "kena cut loss, force close"),
                     ("Price fell to " if en else "Harga jatuh ke ") + f"{p['sl']:.3f} · {rm(pnl(p['sl']))}")]
        if hi is not None and hi >= p["tg"]:
            return [(base + "W", f"{nm}: " + ("reached upper level, time to close (sell)" if en else "sampai paras atas, masa tutup (jual)"),
                     ("Price reached " if en else "Harga capai ") + f"{p['tg']:.3f} · {rm(pnl(p['tg']))}")]
    if len(bars) >= Hp:
        return [(base + "T", f"{nm}: " + ("closing date reached" if en else "tarikh tutup sudah sampai"), rm(pnl(bars[Hp - 1][3])))]
    out = []
    if now > p["sl"] and (now / p["sl"] - 1) * 100 <= 2:
        out.append((base + "N:" + asof, f"{nm}: " + ("close to cut loss" if en else "hampir cut loss"),
                    ("Price now " if en else "Harga kini ") + f"{now:.3f}, cut loss {p['sl']:.3f}"))
    if add_td(p["d"], Hp - 1) <= asof:
        out.append((base + "E", f"{nm}: " + ("closes tomorrow (latest closing date)" if en else "tutup esok (tarikh tutup paling lewat)"),
                    ("Closes on " if en else "Ditutup pada ") + fmt(add_td(p["d"], Hp), en) + f" · {rm(pnl(now))}"))
    elif not p.get("hz") and p.get("md") and add_td(p["d"], p["md"]) <= asof:
        out.append((base + "D", f"{nm}: " + ("typical period has ended" if en else "tempoh biasa sudah tamat"),
                    (f"Profit/loss now {rm(pnl(now))}. Consider closing." if en else f"Untung/rugi kini {rm(pnl(now))}. Pertimbang untuk tutup.")))
    return out


def strong_list(M, only=None):
    """Isyarat Kuat (gred A) yang bermula pada hari data terkini — sama seperti app."""
    out = []
    for c, v in M["stocks"].items():
        if v.get("s") != "ok" or not v.get("op") or v.get("liq") == 0 or (only is not None and c not in only):
            continue
        best = None
        for o in v["op"]:
            if (o.get("ago") or 0) != 0 or not o.get("ev") or o["ev"] <= 0 or not o.get("en"):
                continue
            tp, sp = o["tg"] / o["en"] - 1, 1 - o["sl"] / o["en"]
            edge = o["p"] / 100 - (sp + FEE) / (tp + sp)
            if edge >= 0.10 and (o.get("n") is None or o["n"] >= 8) and (best is None or edge > best[0]):
                best = (edge, o)
        if best:
            out.append({"code": c, "name": (v.get("n") or c).replace(" Berhad", "").replace(" Bhd", ""), "edge": best[0], "o": best[1],
                        "c": v.get("c"), "champ": bool(v.get("va") and v.get("sc", 0) / v["va"] >= 0.75)})
    return sorted(out, key=lambda x: -x["edge"])


def new_signals(M, en, only=None):
    L = strong_list(M, only)
    strong = [(x["edge"], x["name"]) for x in L]
    champ = [(x["edge"], x["name"]) for x in L if x["champ"]]
    out, asof = [], M["meta"]["asof"]
    names = lambda L: ", ".join(n for _, n in sorted(L, reverse=True)[:4]) + (f" +{len(L) - 4}" if len(L) > 4 else "")
    if champ:
        out.append((f"champ:{asof}", (f"🏆 {len(champ)} new Champion signal(s)" if en else f"🏆 {len(champ)} isyarat Champion baharu"), names(champ)))
    if strong:
        out.append((f"sig:{asof}", (f"🟢 {len(strong)} new Strong signal(s)" if en else f"🟢 {len(strong)} Isyarat Kuat baharu"), names(strong)))
    return out


def news_list(M, out_dir):
    """Saham patuh syariah dengan berita positif hari ini (waktu Malaysia)."""
    from datetime import datetime, timezone
    try:
        N = json.load(open(os.path.join(out_dir, "news.json")))["items"]
    except Exception:
        return []
    cut = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
    out = []
    for c, arr in N.items():
        v = M["stocks"].get(c, {})
        if v.get("s") != "ok" or v.get("liq") == 0:
            continue
        g = [x for x in arr if x.get("x") == "+" and x.get("d", "") == cut]
        if g:
            out.append({"code": c, "name": (v.get("n") or c).replace(" Berhad", "").replace(" Bhd", ""), "d": g[0]["d"], "c": v.get("c")})
    return sorted(out, key=lambda x: x["d"], reverse=True)


def atr_of(code, out_dir):
    try:
        return json.load(open(os.path.join(out_dir, "s", f"{code}.json"))).get("atr")
    except Exception:
        try:
            import requests
            r = requests.get(f"https://prosyariah.web.app/data/s/{code}.json", timeout=15)
            return r.json().get("atr") if r.ok else None
        except Exception:
            return None


def merged_positions(data, auto):
    """Senarai Robot Manual + Robot Auto (ikut id; versi yang sudah ditutup diutamakan), tolak yang dipadam."""
    m = {}
    for p in list(data.get("manual", [])) + list(auto):
        o = m.get(p["id"])
        if o is None or (p.get("closed") and not o.get("closed")):
            m[p["id"]] = p
    dele = set(data.get("manDel", []))
    return [p for p in m.values() if p["id"] not in dele]


def eval_pos(p, out_dir):
    """Keputusan posisi ikut harga harian (sama seperti app): ('W'|'L'|'T', harga keluar) atau None jika masih terbuka."""
    if p.get("closed"):
        return p["closed"].get("res"), p["closed"].get("exit")
    try:
        s = json.load(open(os.path.join(out_dir, "s", f"{p['code']}.json")))
        bars = [(s["h"][i], s["l"][i], s["c"][i]) for i, d in enumerate(s["d"]) if (d >= p["d"] if p.get("inc") else d > p["d"])]
    except Exception:
        return None
    Hp = int(p.get("hz") or H)
    for hi, lo, c in bars[:Hp]:
        if lo is not None and lo <= p["sl"]:
            return "L", p["sl"]
        if hi is not None and hi >= p["tg"]:
            return "W", p["tg"]
    if len(bars) >= Hp:
        return "T", bars[Hp - 1][2]
    return None


def capital_free(f, data, auto, out_dir):
    """Baki modal Robot Auto: modal + untung/rugi selesai − nilai posisi terbuka (posisi sejak modal ditetapkan)."""
    num = lambda k: float(f.get(k, {}).get("doubleValue") or f.get(k, {}).get("integerValue") or 0)
    cap, cap_at = num("autoCap"), num("autoCapAt")
    if cap <= 0:
        return None
    def ts(x):
        try:
            return datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp() * 1000
        except Exception:
            return 0
    free = equity = cap
    for p in merged_positions(data, auto):
        if p.get("src") != "A" or ts(p.get("at")) < cap_at:
            continue
        r = eval_pos(p, out_dir)
        stake = float(p.get("stake") or 0)
        if r:
            pl = pos_pnl(p, float(r[1]))
            free += pl
            equity += pl
        else:
            free -= stake
    return free, equity


def auto_adds(f, data, auto, M, out_dir, en, news_only=False):
    """Robot Auto: cipta posisi maya baharu untuk isyarat/berita yang dipilih pengguna."""
    b = lambda k, d=False: f.get(k, {}).get("booleanValue", d)
    if not b("autoOn"):
        return [], []
    try:
        stake = float(f.get("autoStake", {}).get("doubleValue") or f.get("autoStake", {}).get("integerValue") or 20)
    except Exception:
        stake = 20.0
    try:
        tpp = float(f.get("autoTp", {}).get("doubleValue") or f.get("autoTp", {}).get("integerValue") or 5)
    except Exception:
        tpp = 5.0
    tpp = min(max(tpp, 1.0), 50.0)
    asof = M["meta"]["asof"]
    cf = capital_free(f, data, auto, out_dir)   # None = tiada had modal
    free, equity = cf if cf else (None, None)
    fm, fc = b("autoFm"), b("autoFree")   # mod yuran moomoo sebenar (lot 100 unit), komisen percuma
    ETFS = {"0821EA", "0824EA", "0825EA", "0827EA", "0828EA", "0838EA", "0839EA", "5116", "5106", "5235SS", "5269"}

    def lot(code, c, amt):
        """Mod moomoo: beli dalam lot 100 unit; pulangkan (qty, kos termasuk yuran beli) atau None jika tak cukup 1 lot."""
        nonlocal free
        etf = code in ETFS
        lots = int(amt // (c * 100))
        while lots > 0 and lots * 100 * c + fee_side(lots * 100 * c, etf, fc) > amt:
            lots -= 1
        if lots <= 0:
            if free is not None:
                free += amt   # pulangkan bahagian modal; cuba saham lain
            return None
        qty = lots * 100
        cost = round(qty * c + fee_side(qty * c, etf, fc), 2)
        if free is not None:
            free += amt - cost
        return qty, cost, etf
    SLOTS = 5  # modal dibahagi 5: setiap posisi ≈ 20% daripada modal semasa (modal + untung/rugi selesai)

    def size():
        """Saiz posisi seterusnya. None = modal tidak cukup."""
        nonlocal free
        if free is None:
            return stake
        per = round(equity / SLOTS, 2)
        amt = per if free >= per else (round(free, 2) if free >= per * 0.5 else None)
        if amt is not None:
            free -= amt
        return amt
    have = {p["code"] for p in merged_positions(data, auto) if not p.get("closed")}
    seen = {p["id"] for p in auto} | set(data.get("manDel", []))
    from datetime import datetime, timezone
    now = datetime.now(timezone(timedelta(hours=8)))
    entry_sig = add_td(asof, 1)
    today = now.date().isoformat()
    entry_news = today if (now.weekday() < 5 and today not in HOL and asof < today) else add_td(max(asof, today), 1) if asof >= today else add_td(asof, 1)
    new = []
    if not news_only and (b("autoSig") or b("autoChamp")):
        for x in strong_list(M):
            if x["code"] in have or not x["c"] or (not b("autoSig") and not x["champ"]) or f"auto-{x['code']}-{asof}" in seen:
                continue
            amt = size()
            if amt is None:
                break  # modal tidak cukup — tunggu posisi lain ditutup
            o, c = x["o"], x["c"]
            ex = {}
            if fm:
                L = lot(x["code"], c, amt)
                if not L:
                    continue
                ex = {"qty": L[0], "etf": L[2], "fc": fc, "fm": 1}
                amt = L[1]
            new.append({"id": f"auto-{x['code']}-{asof}", "src": "A", "why": "champ" if x["champ"] else "sig", "inc": 1, "code": x["code"], "name": x["name"],
                        "d": entry_sig, "en": round(c, 4), "stake": amt, "tg": round(c * (1 + tpp / 100), 4), "sl": round(c * o["sl"] / o["en"], 4),
                        "tp": tpp, "md": round(o["md"]) if o.get("md") else None, "hz": max(1, round(o["md"])) if o.get("md") else None,
                        "at": now.isoformat(), **ex})
            have.add(x["code"])
    if b("autoNews"):
        for x in news_list(M, out_dir):
            if x["code"] in have or not x["c"] or f"auto-{x['code']}-n{x['d']}" in seen:
                continue
            amt = size()
            if amt is None:
                break
            c, a = x["c"], atr_of(x["code"], out_dir)
            ex = {}
            if fm:
                L = lot(x["code"], c, amt)
                if not L:
                    continue
                ex = {"qty": L[0], "etf": L[2], "fc": fc, "fm": 1}
                amt = L[1]
            tp = tpp / 100
            sp = min(max(1.25 * a / c, 0.02), 0.15) if a else 0.04
            new.append({"id": f"auto-{x['code']}-n{x['d']}", "src": "A", "why": "news", "inc": 1, "code": x["code"], "name": x["name"],
                        "d": entry_news, "en": round(c, 4), "stake": amt, "tg": round(c * (1 + tp), 4), "sl": round(c * (1 - sp), 4),
                        "tp": tpp, "md": None, "at": now.isoformat(), **ex})
            have.add(x["code"])
    alerts = []
    if new:
        nm = ", ".join(p["name"] for p in new[:4]) + (f" +{len(new) - 4}" if len(new) > 4 else "")
        alerts.append((f"autoin:{new[0]['id']}", ("🤖 Auto Robot entered " if en else "🤖 Robot Auto masuk ") + str(len(new)) + (" stock(s)" if en else " saham"),
                       nm + (". Open the Robot tab." if en else ". Buka tab Robot.")))
    return new, alerts


def pot_news(M, out_dir, en):
    """Berita Berpotensi: saham patuh syariah dengan berita bernada positif sejak semalam."""
    try:
        N = json.load(open(os.path.join(out_dir, "news.json")))["items"]
    except Exception:
        return []
    from datetime import datetime, timezone
    cut = datetime.now(timezone(timedelta(hours=8))).date().isoformat()   # berita hari ini (waktu Malaysia) sahaja
    hits = []
    for c, arr in N.items():
        v = M["stocks"].get(c, {})
        if v.get("s") != "ok":
            continue
        g = [x for x in arr if x.get("x") == "+" and x.get("d", "") == cut]
        if g:
            hits.append((g[0]["d"], (v.get("n") or c).replace(" Berhad", "").replace(" Bhd", "")))
    if not hits:
        return []
    hits.sort(reverse=True)
    names = ", ".join(n for _, n in hits[:3]) + (f" +{len(hits) - 3}" if len(hits) > 3 else "")
    title = f"📰 {len(hits)} stock(s) with positive news" if en else f"📰 {len(hits)} saham dengan berita positif"
    return [(f"news:{hits[0][0]}", title, names)]


def price_alerts(data, M, en):
    """Amaran harga (sasaran pengguna) dan pegangan turun melebihi had % — sekali bagi setiap amaran."""
    out, st = [], M["stocks"]
    for p in data.get("pxa") or []:
        v = st.get(str(p.get("code")), {})
        c, tgt = v.get("c"), p.get("price")
        if c is None or not tgt:
            continue
        up = p.get("op") == ">="
        if (c >= tgt) if up else (c <= tgt):
            nm = (v.get("n") or p.get("code")).replace(" Berhad", "").replace(" Bhd", "")
            if en:
                out.append((f"pxa:{p.get('id')}", f"🎯 {nm} {'rose to' if up else 'fell to'} {c:.3f}",
                            f"Your price alert ({'≥' if up else '≤'} {tgt:.3f}) was reached."))
            else:
                out.append((f"pxa:{p.get('id')}", f"🎯 {nm} {'naik ke' if up else 'turun ke'} {c:.3f}",
                            f"Amaran harga anda ({'≥' if up else '≤'} {tgt:.3f}) sudah sampai."))
    lim = abs(float(data.get("lossPct") or 10))
    for h in ((data.get("pf") or {}).get("holdings") or []):
        v = st.get(str(h.get("code")), {})
        c, cost = v.get("c"), h.get("cost")
        try:
            pct = (c / float(cost) - 1) * 100
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if pct <= -lim:
            nm = (v.get("n") or h.get("code")).replace(" Berhad", "").replace(" Bhd", "")
            wk = M["meta"]["asof"][:8]  # sekali sebulan paling kerap
            if en:
                out.append((f"loss:{h.get('id')}:{wk}", f"📉 {nm} down {abs(pct):.1f}% from cost",
                            f"Price {c:.3f} vs cost {float(cost):.3f}. Your alert limit: {lim:g}%."))
            else:
                out.append((f"loss:{h.get('id')}:{wk}", f"📉 {nm} turun {abs(pct):.1f}% dari kos",
                            f"Harga {c:.3f} berbanding kos {float(cost):.3f}. Had amaran anda: {lim:g}%."))
    return out


MON_BM = ["Januari", "Februari", "Mac", "April", "Mei", "Jun", "Julai", "Ogos", "September", "Oktober", "November", "Disember"]
MON_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def monthly_report(M, en):
    """Laporan ketepatan isyarat sebenar bulan lepas (sekali sebulan)."""
    try:
        log = json.load(open(os.path.join(os.path.dirname(__file__), "..", "data", "signals.json")))
    except Exception:
        return []
    asof = M["meta"]["asof"]
    y, m = int(asof[:4]), int(asof[5:7])
    py, pm = (y, m - 1) if m > 1 else (y - 1, 12)
    key = f"{py:04d}-{pm:02d}"
    cl = [t for t in log.get("closed", []) if t.get("ret") is not None]
    mon = [t for t in cl if str(t.get("end", "")).startswith(key)]
    if not mon:
        return []
    st = lambda L: (len(L), round(sum(1 for t in L if t.get("res") == "W") / len(L) * 100), sum(t["ret"] for t in L) / len(L))
    n, w, a = st(mon)
    N, W, A = st(cl)
    sg = lambda v: ("+" if v > 0 else "") + f"{v:.2f}%"
    if en:
        return [(f"month:{key}", f"📊 {MON_EN[pm - 1]} signal report",
                 f"{n} signals closed · {w}% reached the target · average {sg(a)} each. Since start: {N} signals, {W}%, {sg(A)}.")]
    return [(f"month:{key}", f"📊 Laporan isyarat {MON_BM[pm - 1]}",
             f"{n} isyarat selesai · {w}% sampai sasaran · purata {sg(a)} setiap satu. Sejak mula: {N} isyarat, {W}%, {sg(A)}.")]


def weekly(data, M, en):
    """Ringkasan mingguan: dihantar sekali setiap minggu, pada larian petang Jumaat (atau Sabtu jika terlepas)."""
    from datetime import datetime, timezone
    now = datetime.now(timezone(timedelta(hours=8)))
    if not ((now.weekday() == 4 and now.hour >= 17) or now.weekday() == 5):
        return None
    man = data.get("manual", [])
    if not man:
        return None
    y, w, _ = now.isocalendar()
    mon = (now.date() - timedelta(days=now.weekday())).isoformat()
    op = [p for p in man if not p.get("closed")]
    cl = [p for p in man if p.get("closed") and p["closed"].get("end", "") >= mon]
    pnl = pos_pnl
    o_pl = sum(pnl(p, M["stocks"][p["code"]]["c"]) for p in op if M["stocks"].get(p["code"], {}).get("c"))
    c_pl = sum(pnl(p, p["closed"]["exit"]) for p in cl)
    win = sum(1 for p in cl if p["closed"].get("res") == "W")
    if en:
        title = "ProSyariah · Weekly summary"
        body = f"Open: {len(op)} ({rm(o_pl)}). Closed this week: {len(cl)}" + (f", {win} won ({rm(c_pl)})" if cl else "") + "."
    else:
        title = "ProSyariah · Ringkasan minggu ini"
        body = f"Sedang diuji: {len(op)} ({rm(o_pl)}). Ditutup minggu ini: {len(cl)}" + (f", {win} menang ({rm(c_pl)})" if cl else "") + "."
    return (f"week:{y}-{w:02d}", title, body)


def main():
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession

    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="_site/data")
    ap.add_argument("--only-news", action="store_true", help="larian berita sahaja (setiap 2 jam)")
    a = ap.parse_args()
    key = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    pid = json.load(open(key))["project_id"]
    cred = service_account.Credentials.from_service_account_file(
        key, scopes=["https://www.googleapis.com/auth/datastore", "https://www.googleapis.com/auth/firebase.messaging"])
    http = AuthorizedSession(cred)
    M = json.load(open(os.path.join(a.out, "market.json")))
    base = f"https://firestore.googleapis.com/v1/projects/{pid}/databases/(default)/documents"
    docs, tok = [], None
    while True:
        r = http.get(f"{base}/users", params={"pageSize": 300, **({"pageToken": tok} if tok else {})})
        if r.status_code == 404:
            print("Tiada pangkalan data Firestore / koleksi users lagi.")
            return
        if not r.ok:
            print("Firestore", r.status_code, r.text[:600])
            return
        j = r.json()
        docs += j.get("documents", [])
        tok = j.get("nextPageToken")
        if not tok:
            break
    users = sent_n = auto_n = 0
    from datetime import datetime, timezone
    hour = datetime.now(timezone(timedelta(hours=8))).hour
    for d in docs:
        f = d.get("fields", {})
        tokens = [x.get("stringValue") for x in f.get("tokens", {}).get("arrayValue", {}).get("values", []) if x.get("stringValue")]
        try:
            data = json.loads(f.get("data", {}).get("stringValue") or "{}")
            sent = json.loads(f.get("sent", {}).get("stringValue") or "{}")
            auto = json.loads(f.get("auto", {}).get("stringValue") or "[]")
        except Exception:
            continue
        en = (f.get("lang", {}).get("stringValue") or "bm") == "en"
        b = lambda k, dflt=True: f.get(k, {}).get("booleanValue", dflt)
        new, dead, items = [], set(), []
        # 1) Robot Auto — berjalan untuk semua akaun yang hidupkannya (dengan atau tanpa notifikasi)
        added, aal = auto_adds(f, data, auto, M, a.out, en, news_only=a.only_news)
        if added:
            auto = (auto + added)[-200:]
            auto_n += len(added)
            http.patch(f"https://firestore.googleapis.com/v1/{d['name']}", params=[("updateMask.fieldPaths", "auto")],
                       json={"fields": {"auto": {"stringValue": json.dumps(auto)}}})
        # 2) Notifikasi — hanya untuk phone berdaftar, ikut pilihan masa
        if not tokens or (b("pushAm", False) and hour >= 12):
            continue
        users += 1
        items += aal
        if a.only_news:
            if b("news"):
                items += pot_news(M, a.out, en)
        else:
            for p in merged_positions(data, auto):
                if not p.get("closed"):
                    items += alerts_for(p, M, a.out, en)
            if b("sig"):
                items += new_signals(M, en, set(data.get("watch", [])) if b("sigWatch", False) else None)
            if b("news"):
                items += pot_news(M, a.out, en)
            if b("px", False):
                items += price_alerts(data, M, en)
            if b("sig"):
                items += monthly_report(M, en)
            wk = weekly(data, M, en)
            if wk:
                items.append(wk)
        for aid, title, body in items:
            if aid in sent:
                continue
            link = "https://prosyariah.web.app/#robot" if aid.startswith(("man:", "week:", "autoin:")) else "https://prosyariah.web.app/"
            for t in tokens:
                msg = {"message": {"token": t, "data": {"title": title, "body": body, "tag": aid},
                                   "webpush": {"headers": {"Urgency": "high"}, "fcm_options": {"link": link}}}}
                rr = http.post(f"https://fcm.googleapis.com/v1/projects/{pid}/messages:send", json=msg)
                if rr.status_code in (404, 400) and ("UNREGISTERED" in rr.text or "INVALID_ARGUMENT" in rr.text):
                    dead.add(t)
                elif rr.ok:
                    sent_n += 1
            sent[aid] = M["meta"]["asof"]
            new.append(aid)
        if new or dead:
            keep = sorted(sent.items(), key=lambda x: x[1])[-300:]
            fields = {"sent": {"stringValue": json.dumps(dict(keep))}}
            mask = ["sent"]
            if dead:
                fields["tokens"] = {"arrayValue": {"values": [{"stringValue": t} for t in tokens if t not in dead]}}
                mask.append("tokens")
            http.patch(f"https://firestore.googleapis.com/v1/{d['name']}", params=[("updateMask.fieldPaths", m) for m in mask],
                       json={"fields": fields})
    print(f"✓ Notifikasi push: {len(docs)} akaun dalam Firestore, {users} dengan phone berdaftar, {sent_n} notifikasi dihantar, Robot Auto {auto_n} posisi baharu")


if __name__ == "__main__":
    main()
