"""Daftar app Android ProSyariah dalam Firebase (sekali) dan muat turun google-services.json.

Perlu untuk APK: log masuk Google asli & notifikasi push (FCM).
  python scripts/apk_firebase.py <folder kunci (sha1, sha256)> <laluan google-services.json>
"""
import base64
import json
import os
import sys
import time

from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession

PKG = "com.prokuiz.prosyariah"
API = "https://firebase.googleapis.com/v1beta1"


def main(kdir, dest):
    key = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    pid = json.load(open(key))["project_id"]
    cred = service_account.Credentials.from_service_account_file(key, scopes=["https://www.googleapis.com/auth/cloud-platform"])
    http = AuthorizedSession(cred)

    def ok(r, what):
        if not r.ok:
            sys.exit(f"✗ {what}: {r.status_code} {r.text[:400]}")
        return r.json()
    apps = ok(http.get(f"{API}/projects/{pid}/androidApps", timeout=30), "senarai app Android").get("apps", [])
    app = next((a for a in apps if a.get("packageName") == PKG), None)
    if not app:
        op = ok(http.post(f"{API}/projects/{pid}/androidApps", json={"packageName": PKG, "displayName": "ProSyariah APK"}, timeout=30), "cipta app Android")
        for _ in range(30):
            if op.get("done"):
                break
            time.sleep(3)
            op = ok(http.get(f"{API}/{op['name']}", timeout=30), "tunggu cipta app")
        app = op.get("response") or {}
        print("✓ App Android didaftarkan dalam Firebase:", app.get("appId"))
    else:
        print("✓ App Android sedia ada:", app.get("appId"))
    name = app["name"]
    have = {(c.get("shaHash", "").lower(), c.get("certType")) for c in ok(http.get(f"{API}/{name}/sha", timeout=30), "senarai SHA").get("certificates", [])}
    for f, typ in (("sha1", "SHA_1"), ("sha256", "SHA_256")):
        h = open(os.path.join(kdir, f)).read().strip().replace(":", "").lower()
        if (h, typ) not in have:
            ok(http.post(f"{API}/{name}/sha", json={"shaHash": h, "certType": typ}, timeout=30), f"tambah {typ}")
            print(f"✓ Cap jari {typ} ditambah")
    cfg = {}
    for _ in range(10):   # klien OAuth Android dicipta di belakang tabir; tunggu ia muncul dalam config
        cfg = json.loads(base64.b64decode(ok(http.get(f"{API}/{name}/config", timeout=30), "muat turun config")["configFileContents"]))
        cl = [o for c in cfg.get("client", []) for o in c.get("oauth_client", [])]
        if any(o.get("client_type") == 1 for o in cl) and any(o.get("client_type") == 3 for o in cl):
            break
        time.sleep(6)
    json.dump(cfg, open(dest, "w"), indent=2)
    cl = [o.get("client_type") for c in cfg.get("client", []) for o in c.get("oauth_client", [])]
    print("✓ google-services.json sedia · klien OAuth:", cl)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
