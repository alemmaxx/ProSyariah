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
from datetime import date, timedelta

H, FEE = 40, 0.003


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
    pnl = lambda x: (x / p["en"] - 1 - FEE) * p["stake"]
    # semak paras atas/bawah dengan harga tinggi/rendah harian sejak masuk
    try:
        s = json.load(open(os.path.join(out_dir, "s", f"{p['code']}.json")))
        bars = [(d, s["h"][i], s["l"][i], s["c"][i]) for i, d in enumerate(s["d"])
                if (d >= p["d"] if p.get("inc") else d > p["d"])]
    except Exception:
        bars = []
    for i, (d, hi, lo, c) in enumerate(bars[:H]):
        if lo is not None and lo <= p["sl"]:
            return [(base + "L", f"{nm}: " + ("hit cut loss, force close" if en else "kena cut loss, force close"),
                     ("Price fell to " if en else "Harga jatuh ke ") + f"{p['sl']:.3f} · {rm(pnl(p['sl']))}")]
        if hi is not None and hi >= p["tg"]:
            return [(base + "W", f"{nm}: " + ("reached upper level, time to close (sell)" if en else "sampai paras atas, masa tutup (jual)"),
                     ("Price reached " if en else "Harga capai ") + f"{p['tg']:.3f} · {rm(pnl(p['tg']))}")]
    if len(bars) >= H:
        return [(base + "T", f"{nm}: " + ("closing date reached" if en else "tarikh tutup sudah sampai"), rm(pnl(bars[H - 1][3])))]
    out = []
    if now > p["sl"] and (now / p["sl"] - 1) * 100 <= 2:
        out.append((base + "N:" + asof, f"{nm}: " + ("close to cut loss" if en else "hampir cut loss"),
                    ("Price now " if en else "Harga kini ") + f"{now:.3f}, cut loss {p['sl']:.3f}"))
    if add_td(p["d"], H - 1) <= asof:
        out.append((base + "E", f"{nm}: " + ("closes tomorrow (latest closing date)" if en else "tutup esok (tarikh tutup paling lewat)"),
                    ("Closes on " if en else "Ditutup pada ") + fmt(add_td(p["d"], H), en) + f" · {rm(pnl(now))}"))
    elif p.get("md") and add_td(p["d"], p["md"]) <= asof:
        out.append((base + "D", f"{nm}: " + ("typical period has ended" if en else "tempoh biasa sudah tamat"),
                    (f"Profit/loss now {rm(pnl(now))}. Consider closing." if en else f"Untung/rugi kini {rm(pnl(now))}. Pertimbang untuk tutup.")))
    return out


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
    pnl = lambda p, x: (x / p["en"] - 1 - FEE) * p["stake"]
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
    users = sent_n = 0
    for d in docs:
        f = d.get("fields", {})
        tokens = [x.get("stringValue") for x in f.get("tokens", {}).get("arrayValue", {}).get("values", []) if x.get("stringValue")]
        if not tokens or not f.get("notify", {}).get("booleanValue"):
            continue
        try:
            data = json.loads(f.get("data", {}).get("stringValue") or "{}")
            sent = json.loads(f.get("sent", {}).get("stringValue") or "{}")
        except Exception:
            continue
        en = (f.get("lang", {}).get("stringValue") or "bm") == "en"
        users += 1
        new, dead = [], set()
        items = []
        for p in data.get("manual", []):
            if not p.get("closed"):
                items += alerts_for(p, M, a.out, en)
        wk = weekly(data, M, en)
        if wk:
            items.append(wk)
        for aid, title, body in items:
            if True:
                if aid in sent:
                    continue
                for t in tokens:
                    msg = {"message": {"token": t, "data": {"title": title, "body": body, "tag": aid},
                                       "webpush": {"headers": {"Urgency": "high"}, "fcm_options": {"link": "https://prosyariah.web.app/#robot"}}}}
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
    print(f"✓ Notifikasi push: {len(docs)} akaun dalam Firestore, {users} dengan notifikasi aktif, {sent_n} notifikasi dihantar")


if __name__ == "__main__":
    main()
