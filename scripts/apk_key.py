"""Kunci tandatangan APK ProSyariah.

Kunci dicipta SEKALI sahaja dan disimpan dalam Firestore secrets/apk (peraturan Firestore
menolak semua akses dari app/pelayar; hanya akaun servis GitHub boleh baca).
Kunci yang sama mesti digunakan setiap kali supaya pengguna boleh kemas kini APK tanpa nyahpasang.

Output:
  <out>/prosyariah.jks, <out>/pw   (untuk gradle)
  .well-known/assetlinks.json      (bukti domain prosyariah.web.app milik app ini → skrin penuh tanpa bar alamat)
"""
import base64
import json
import os
import secrets
import subprocess
import sys

from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession

ROOT = os.path.join(os.path.dirname(__file__), "..")
PKG = "com.prokuiz.prosyariah"


def main(out):
    key = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    pid = json.load(open(key))["project_id"]
    cred = service_account.Credentials.from_service_account_file(key, scopes=["https://www.googleapis.com/auth/datastore"])
    http = AuthorizedSession(cred)
    url = f"https://firestore.googleapis.com/v1/projects/{pid}/databases/(default)/documents/secrets/apk"
    os.makedirs(out, exist_ok=True)
    ks, pwf = os.path.join(out, "prosyariah.jks"), os.path.join(out, "pw")
    r = http.get(url, timeout=30)
    if r.status_code == 200:
        f = r.json()["fields"]
        open(ks, "wb").write(base64.b64decode(f["ks"]["stringValue"]))
        pw = f["pw"]["stringValue"]
        print("✓ Kunci APK sedia ada digunakan")
    elif r.status_code == 404:
        pw = secrets.token_urlsafe(18)
        subprocess.run(["keytool", "-genkeypair", "-keystore", ks, "-alias", "prosyariah", "-keyalg", "RSA", "-keysize", "2048",
                        "-validity", "10000", "-storepass", pw, "-keypass", pw, "-dname", "CN=ProSyariah, C=MY"], check=True)
        body = {"fields": {"ks": {"stringValue": base64.b64encode(open(ks, "rb").read()).decode()}, "pw": {"stringValue": pw}}}
        w = http.patch(url, json=body, timeout=30)
        w.raise_for_status()
        print("✓ Kunci APK baharu dicipta & disimpan")
    else:
        sys.exit(f"Gagal baca kunci APK: {r.status_code} {r.text[:200]}")
    open(pwf, "w").write(pw)
    txt = subprocess.run(["keytool", "-list", "-v", "-keystore", ks, "-alias", "prosyariah", "-storepass", pw],
                         capture_output=True, text=True, check=True).stdout
    fp = next(l.split("SHA256:")[1].strip() for l in txt.splitlines() if "SHA256:" in l)
    os.makedirs(os.path.join(ROOT, ".well-known"), exist_ok=True)
    al = [{"relation": ["delegate_permission/common.handle_all_urls"],
           "target": {"namespace": "android_app", "package_name": PKG, "sha256_cert_fingerprints": [fp]}}]
    json.dump(al, open(os.path.join(ROOT, ".well-known", "assetlinks.json"), "w"), indent=1)
    print("  cap jari:", fp)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/apkkey")
