"""Robot 10: saluran Telegram ProSyariah.

Hantar ke saluran Telegram (bot mesti admin saluran):
  --kind evening : ringkasan Isyarat Kuat / Champion selepas data petang
  --kind news    : Berita Berpotensi hari ini (saham baharu sahaja)
  --kind monthly : laporan ketepatan bulan lepas (sekali sebulan)
  --kind test    : mesej ujian
Perlu secret TELEGRAM_BOT_TOKEN. Saluran: Firestore config/admin.tgChat (tab Admin) atau env TELEGRAM_CHAT.
Elak hantar berulang: data/tg-sent.json.
"""
import argparse
import html
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(__file__))
import push  # noqa: E402  (strong_list, news_list, monthly_report, add_td, fmt)

ROOT = os.path.join(os.path.dirname(__file__), "..")
SENT = os.path.join(ROOT, "data", "tg-sent.json")
APP = "https://prosyariah.web.app/"
NOTE = "ℹ️ <i>Bacaan indicator, bukan cadangan beli atau jual.</i>"
MYT = timezone(timedelta(hours=8))


def chat_id():
    c = (os.environ.get("TELEGRAM_CHAT") or "").strip()
    key = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if key and os.path.exists(key):
        try:
            from google.oauth2 import service_account
            from google.auth.transport.requests import AuthorizedSession
            pid = json.load(open(key))["project_id"]
            cred = service_account.Credentials.from_service_account_file(key, scopes=["https://www.googleapis.com/auth/datastore"])
            r = AuthorizedSession(cred).get(f"https://firestore.googleapis.com/v1/projects/{pid}/databases/(default)/documents/config/admin", timeout=20)
            if r.ok:
                v = r.json().get("fields", {}).get("tgChat", {}).get("stringValue")
                if v:
                    c = v.strip()
        except Exception as e:
            print("  ! baca tetapan saluran gagal:", e)
    if c and not c.startswith("@") and not c.lstrip("-").isdigit():
        c = "@" + c.lstrip("@").replace("https://t.me/", "").replace("t.me/", "")
    return c


def send(token, chat, text):
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=30)
    ok = r.ok and r.json().get("ok")
    if not ok:
        print("  ! Telegram:", r.status_code, r.text[:300])
    return bool(ok)


def pct(a, b):
    return f"{(a / b - 1) * 100:+.1f}%"


def evening(M):
    L = push.strong_list(M)
    asof = M["meta"]["asof"]
    start = push.add_td(asof, 1)
    if not L:
        return f"evening:{asof}", (f"📊 <b>ProSyariah · {push.fmt(asof, False)}</b>\n\nTiada Isyarat Kuat baharu hari ini. "
                                   f"Robot akan semak semula selepas pasaran tutup esok.\n\n{NOTE}\n🔗 {APP}")
    lines = []
    for x in L[:10]:
        o, c = x["o"], x["c"]
        tg, sl = c * o["tg"] / o["en"], c * o["sl"] / o["en"]
        lines.append(f"{'🏆' if x['champ'] else '🟢'} <b>{html.escape(x['name'])}</b> ({x['code']}) · {c:.3f}\n"
                     f"    🎯 {tg:.3f} ({pct(tg, c)}) · 🛑 {sl:.3f} ({pct(sl, c)}) · ~{round(o.get('md') or 0)} hari")
    more = f"\n…dan {len(L) - 10} lagi dalam app." if len(L) > 10 else ""
    champ = sum(1 for x in L if x["champ"])
    head = (f"📊 <b>Isyarat ProSyariah · {push.fmt(asof, False)}</b>\n"
            f"{len(L)} Isyarat Kuat{f' · {champ} Champion' if champ else ''} · untuk dagangan bermula {push.fmt(start, False)}\n")
    return f"evening:{asof}", head + "\n" + "\n".join(lines) + more + f"\n\n🎯 sasaran · 🛑 cut loss · hari = tempoh biasa\n{NOTE}\n🔗 {APP}"


def news(M, out_dir, sent):
    L = [x for x in push.news_list(M, out_dir) if f"news:{x['code']}:{x['d']}" not in sent]
    if not L:
        return None, None, []
    try:
        N = json.load(open(os.path.join(out_dir, "news.json")))["items"]
    except Exception:
        N = {}
    lines = []
    for x in L[:8]:
        art = next((a for a in N.get(x["code"], []) if a.get("x") == "+" and a.get("d") == x["d"]), None)
        t = f"\n    <a href=\"{html.escape(art['u'])}\">{html.escape(art['t'][:110])}</a>" if art and art.get("u") else ""
        price = f" · {x['c']:.3f}" if x.get("c") else ""
        lines.append(f"📰 <b>{html.escape(x['name'])}</b> ({x['code']}){price}{t}")
    keys = [f"news:{x['code']}:{x['d']}" for x in L[:8]]
    msg = (f"📰 <b>Berita Berpotensi · {push.fmt(L[0]['d'], False)}</b>\nBerita positif hari ini untuk saham patuh syariah:\n\n"
           + "\n\n".join(lines) + f"\n\n{NOTE}\n🔗 {APP}")
    return keys[0], msg, keys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "_site", "data"))
    ap.add_argument("--kind", choices=["evening", "news", "monthly", "test"], required=True)
    a = ap.parse_args()
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Telegram dilangkau: tiada TELEGRAM_BOT_TOKEN")
        return
    chat = chat_id()
    if not chat:
        print("Telegram dilangkau: saluran belum ditetapkan (tab Admin → Telegram)")
        return
    sent = json.load(open(SENT)) if os.path.exists(SENT) else {}
    now = datetime.now(MYT).strftime("%Y-%m-%d %H:%M")
    todo = []
    if a.kind == "test":
        todo = [("test:" + now, f"✅ <b>ProSyariah</b>\nSaluran Telegram berjaya disambung ({now} MYT).\n🔗 {APP}", [])]
    else:
        M = json.load(open(os.path.join(a.out, "market.json")))
        if a.kind == "evening":
            k, m = evening(M)
            todo.append((k, m, []))
            for k2, title, body in push.monthly_report(M, False):
                todo.append(("tg" + k2, f"{title}\n\n{body}\n\n{NOTE}\n🔗 {APP}", []))
        elif a.kind == "monthly":
            for k2, title, body in push.monthly_report(M, False):
                todo.append(("tg" + k2, f"{title}\n\n{body}\n\n{NOTE}\n🔗 {APP}", []))
        elif a.kind == "news":
            k, m, keys = news(M, a.out, sent)
            if k:
                todo.append((k, m, keys))
    n = 0
    for k, msg, extra in todo:
        if k in sent and not k.startswith("test:"):
            continue
        if send(token, chat, msg):
            n += 1
            for kk in [k] + extra:
                sent[kk] = now
    keep = dict(sorted(sent.items(), key=lambda x: x[1])[-500:])
    json.dump(keep, open(SENT, "w"), indent=0)
    print(f"✓ Telegram ({a.kind}): {n} mesej dihantar ke {chat}")


if __name__ == "__main__":
    main()
