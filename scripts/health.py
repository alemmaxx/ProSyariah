"""Robot 8: pemantau kesihatan sistem (setiap 30 minit).

Semak: data harga terkini, larian robot data/berita, laman app (laju & boleh dibuka),
pangkalan data akaun, dan notifikasi. Tulis:
  - data/status.json            → ringkas & awam (app tunjuk jalur amaran umum kepada pengguna)
  - Firestore config/admin_status → butiran penuh (tab Admin sahaja)
  - Firestore config/admin_stats  → bilangan pengguna (tab Admin sahaja)
Hantar emel kepada alamat dalam config/admin.alertEmail bila masalah bermula / pulih,
dan emel ujian bila diminta dari tab Admin. Emel perlu secret SMTP_USER & SMTP_PASS
(contoh: Gmail + App Password). Tanpa secret, semakan tetap berjalan; emel dilangkau.
"""
import json
import os
import smtplib
import time
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

import requests

ROOT = os.path.join(os.path.dirname(__file__), "..")
STATUS = os.path.join(ROOT, "data", "status.json")
REPO = os.environ.get("GITHUB_REPOSITORY", "alemmaxx/ProSyariah")
SITE = "https://prosyariah.web.app/"
PAGES = "https://alemmaxx.github.io/ProSyariah/"
MYT = timezone(timedelta(hours=8))
SLOW_S = 8.0


def now_myt():
    return datetime.now(MYT)


def expected_asof(hol):
    """Hari dagangan terakhir yang datanya sepatutnya sudah ada (beri masa hingga 9 malam)."""
    n = now_myt()
    is_td = lambda d: d.weekday() < 5 and d.isoformat() not in hol
    d = n.date()
    if not (is_td(d) and (n.hour, n.minute) >= (21, 0)):
        d -= timedelta(days=1)
        while not is_td(d):
            d -= timedelta(days=1)
    return d.isoformat()


def check_data(issues):
    try:
        hol = set(json.load(open(os.path.join(ROOT, "data", "holidays.json"))).get("days", []))
    except Exception:
        hol = set()
    try:
        asof = json.load(open(os.path.join(ROOT, "data", "market-meta.json"))).get("asof", "")
    except Exception:
        asof = ""
    exp = expected_asof(hol)
    if asof < exp:
        lag, d = 0, datetime.fromisoformat(exp).date()
        while asof and d.isoformat() > asof and lag < 30:
            if d.weekday() < 5 and d.isoformat() not in hol:
                lag += 1
            d -= timedelta(days=1)
        issues.append({"k": "data", "pub": True, "lv": "down" if lag >= 2 or not asof else "warn",
                       "msg": f"Data harga lewat {lag} hari dagangan: terakhir {asof or '-'}, sepatutnya {exp}."})
    return asof


def check_runs(issues, tok):
    if not tok:
        return
    h = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}
    for wf, key, label in [("main.yml", "run_main", "Robot data harian"), ("news.yml", "run_news", "Robot berita")]:
        try:
            r = requests.get(f"https://api.github.com/repos/{REPO}/actions/workflows/{wf}/runs",
                             params={"per_page": 5, "status": "completed"}, headers=h, timeout=20)
            runs = [x for x in r.json().get("workflow_runs", []) if x.get("event") != "push"] or r.json().get("workflow_runs", [])
        except Exception as e:
            issues.append({"k": key + "_api", "pub": False, "lv": "warn", "msg": f"{label}: status larian tidak dapat dibaca ({e})."})
            continue
        if runs and runs[0].get("conclusion") not in ("success", "skipped", "cancelled"):
            issues.append({"k": key, "pub": False, "lv": "warn",
                           "msg": f"{label} gagal pada {runs[0].get('created_at', '')[:16]}Z ({runs[0].get('html_url')})."})


def check_site(issues):
    for url, key, label in [(SITE, "site_fb", "Laman app (prosyariah.web.app)"), (PAGES + "data/holidays.json", "site_pages", "Data app (GitHub Pages)")]:
        r, dt, err = None, 0.0, None
        for attempt in range(2):  # cuba dua kali supaya gangguan sekejap tidak dikira masalah
            t0 = time.time()
            try:
                r = requests.get(url, params={"t": int(t0)}, timeout=25)
                dt, err = time.time() - t0, None
                if r.ok and dt <= SLOW_S:
                    break
            except Exception as e:
                err = e
            time.sleep(10)
        try:
            if err:
                raise err
            if not r.ok:
                issues.append({"k": key, "pub": True, "lv": "down", "msg": f"{label}: HTTP {r.status_code}."})
            elif dt > SLOW_S:
                issues.append({"k": key + "_slow", "pub": True, "lv": "warn", "msg": f"{label}: perlahan ({dt:.1f}s)."})
        except Exception as e:
            issues.append({"k": key, "pub": True, "lv": "down", "msg": f"{label}: tidak dapat dibuka ({type(e).__name__})."})


def fs_session():
    key = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not key or not os.path.exists(key):
        return None, None
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
    pid = json.load(open(key))["project_id"]
    cred = service_account.Credentials.from_service_account_file(
        key, scopes=["https://www.googleapis.com/auth/datastore"])
    return AuthorizedSession(cred), f"https://firestore.googleapis.com/v1/projects/{pid}/databases/(default)/documents"


def fs_get(http, base, path):
    r = http.get(f"{base}/{path}", timeout=20)
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    out = {}
    for k, v in r.json().get("fields", {}).items():
        out[k] = next(iter(v.values()), None)
    return out


def fs_set(http, base, path, data):
    def val(v):
        if isinstance(v, bool):
            return {"booleanValue": v}
        if isinstance(v, int):
            return {"integerValue": str(v)}
        if isinstance(v, float):
            return {"doubleValue": v}
        return {"stringValue": str(v)}
    params = [("updateMask.fieldPaths", k) for k in data]
    http.patch(f"{base}/{path}", params=params, json={"fields": {k: val(v) for k, v in data.items()}}, timeout=20)


def user_stats(http, base):
    n = tok = auto = 0
    page = None
    while True:
        r = http.get(f"{base}/users", params={"pageSize": 300, "mask.fieldPaths": ["autoOn", "tokens"], **({"pageToken": page} if page else {})}, timeout=30)
        if not r.ok:
            break
        j = r.json()
        for d in j.get("documents", []):
            f = d.get("fields", {})
            n += 1
            tok += 1 if f.get("tokens", {}).get("arrayValue", {}).get("values") else 0
            auto += 1 if f.get("autoOn", {}).get("booleanValue") else 0
        page = j.get("nextPageToken")
        if not page:
            break
    return {"users": n, "withPhone": tok, "autoOn": auto}


def check_push_log(issues):
    try:
        t = open(os.path.join(ROOT, "data", "firebase-debug.txt")).read()
    except Exception:
        return
    if "push: dilangkau" in t or "Traceback" in t:
        issues.append({"k": "push", "pub": False, "lv": "warn", "msg": "Notifikasi telefon: larian terakhir gagal (lihat data/firebase-debug.txt)."})


def send_mail(to, subject, body):
    user, pw = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS")
    if not (user and pw and to):
        print("  emel dilangkau (tiada SMTP_USER/SMTP_PASS atau alamat emel)")
        return False
    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = subject, f"ProSyariah Monitor <{user}>", to
    try:
        with smtplib.SMTP_SSL(host, 465, timeout=30) as s:
            s.login(user, pw)
            s.sendmail(user, [x.strip() for x in to.split(",") if x.strip()], msg.as_string())
        print("  ✓ emel dihantar ke", to)
        return True
    except Exception as e:
        print("  ! emel gagal:", type(e).__name__, e)
        return False


def main():
    issues = []
    asof = check_data(issues)
    check_runs(issues, os.environ.get("GITHUB_TOKEN"))
    check_site(issues)
    check_push_log(issues)
    http, base = None, None
    admin = {}
    try:
        http, base = fs_session()
        if http:
            admin = fs_get(http, base, "config/admin")
    except Exception as e:
        issues.append({"k": "db", "pub": True, "lv": "down", "msg": f"Pangkalan data akaun (Firestore) tidak dapat dicapai ({type(e).__name__})."})
        http = None

    old = json.load(open(STATUS)) if os.path.exists(STATUS) else {}
    pub = [i for i in issues if i["pub"]]
    level = "down" if any(i["lv"] == "down" for i in pub) else ("warn" if pub else "ok")
    stamp = now_myt().isoformat(timespec="minutes")
    keys = sorted(i["k"] for i in issues)
    since = old.get("since") if old.get("level") == level and level != "ok" else (stamp if level != "ok" else None)
    new_status = {"level": level, "since": since}
    if {k: old.get(k) for k in new_status} != new_status:
        json.dump(new_status, open(STATUS, "w"), indent=1)
        print("status.json dikemas kini:", new_status)
    print(f"Tahap: {level} · isu: {keys or 'tiada'} · data {asof}")
    for i in issues:
        print("  -", i["k"], "|", i["msg"])

    # ---- emel ----
    to = (admin.get("alertEmail") or os.environ.get("ALERT_EMAIL") or "").strip()
    st_prev = {}
    if http:
        try:
            st_prev = fs_get(http, base, "config/admin_status")
        except Exception:
            st_prev = {}
    prev = set(json.loads(st_prev.get("keys") or "[]"))
    cur = set(keys)
    mailed = None
    if cur - prev:
        body = "Masalah baharu dikesan oleh pemantau ProSyariah:\n\n" + "\n".join(f"• {i['msg']}" for i in issues if i["k"] in cur - prev)
        body += "\n\nSemua isu semasa:\n" + "\n".join(f"• {i['msg']}" for i in issues)
        body += f"\n\nPengguna nampak jalur amaran: {'YA' if level != 'ok' else 'tidak'}.\nMasa: {stamp} (MYT)\nTab Admin: {SITE}"
        mailed = send_mail(to, f"⚠️ ProSyariah: {len(cur - prev)} masalah baharu", body)
    elif prev and not cur:
        mailed = send_mail(to, "✅ ProSyariah: sistem pulih", f"Semua semakan kembali normal pada {stamp} (MYT).")
    test_req = int(admin.get("testReq") or 0)
    test_done = int(st_prev.get("testDone") or 0)
    if test_req and test_req > test_done:
        ok = send_mail(to, "🔔 ProSyariah: emel ujian", f"Emel ujian dari tab Admin. Pemantau sistem berjalan setiap 30 minit.\nTahap sekarang: {level}\nMasa: {stamp} (MYT)")
        test_done = test_req if ok else test_done
        if http:
            fs_set(http, base, "config/admin_status", {"testDone": test_req, "testOk": bool(ok)})

    if http:
        try:
            fs_set(http, base, "config/admin_status", {
                "level": level, "at": stamp, "keys": json.dumps(keys),
                "issues": json.dumps(issues, ensure_ascii=False), "asof": asof,
                "mailer": bool(os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASS")),
                **({"lastMail": stamp, "lastMailOk": bool(mailed)} if mailed is not None else {})})
            fs_set(http, base, "config/admin_stats", {**user_stats(http, base), "at": stamp})
        except Exception as e:
            print("! tulis Firestore gagal:", e)


if __name__ == "__main__":
    main()
