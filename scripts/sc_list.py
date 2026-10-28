"""Robot 1: muat turun Senarai Sekuriti Patuh Syariah SC dan simpan sebagai data/sc-list.json.

- Guna pautan tetap (permalink) "view list" dari laman SC.
- Hanya tulis fail jika dokumen berubah (hash) DAN bacaan nampak munasabah.
- Simpan 2 senarai terakhir (sebelum & terkini) supaya app boleh kesan saham ditambah/digugurkan.
"""
import hashlib
import io
import json
import os
import re
import sys
from datetime import date
from urllib.parse import urljoin

import requests

sys.path.insert(0, os.path.dirname(__file__))
from common import last_friday, norm_name  # noqa: E402

PERMALINK = os.environ.get(
    "SC_LIST_URL",
    "https://www.sc.com.my/permalink.aspx?id=A978BB30-65DB-4B26-97D5-DB4E14173A7D",
)
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "sc-list.json")
SYMBOLS = os.path.join(os.path.dirname(__file__), "..", "data", "klse-symbols.json")
MIN_NAMES = int(os.environ.get("SC_MIN_NAMES", "300"))
UA = {"User-Agent": "Mozilla/5.0 (ProSyariah data bot; github actions)"}
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"

NAME_END = r"(?:Berhad|Bhd\.?|BERHAD|BHD\.?|Real Estate Investment Trust|REIT|ETF|Trust|Fund|Limited|Ltd\.?|Corporation|Plc)"
SKIP = re.compile(
    r"^(list of|senarai|the shariah|shariah advisory|securities commission|page \d|no\.?$|name of|disclaimer|"
    r"this document|main market|ace market|leap market|total|note|\d+$)",
    re.I,
)


def fetch(url, depth=0):
    r = requests.get(url, headers=UA, timeout=90, allow_redirects=True)
    r.raise_for_status()
    ctype = r.headers.get("content-type", "").lower()
    body = r.content
    if body[:4] == b"%PDF" or "pdf" in ctype:
        return "pdf", body, r.url
    if body[:2] == b"PK" or "spreadsheet" in ctype or "excel" in ctype:
        return "xlsx", body, r.url
    # Halaman HTML: cari pautan PDF/Excel di dalamnya
    if depth < 2:
        html = r.text
        links = re.findall(r'href=["\']([^"\']+)["\']', html, re.I)
        pref = [l for l in links if re.search(r"\.(pdf|xlsx?)(\?|$)", l, re.I)]
        pref += [l for l in links if "permalink" in l.lower() and l not in pref]
        for l in pref:
            if re.search(r"shariah|syariah|list", l, re.I) or l.lower().endswith((".pdf", ".xlsx")):
                return fetch(urljoin(r.url, l), depth + 1)
    raise RuntimeError(f"Format dokumen SC tidak dikenali ({ctype}) di {r.url}")


def split_names(line):
    """Satu baris PDF mungkin ada 2–3 lajur nama. Pecahkan ikut jarak & penamat 'Bhd/Berhad'."""
    out = []
    for chunk in re.split(r"\s{2,}|\t", line):
        chunk = re.sub(r"^\d{1,4}[.)]?\s+", "", chunk.strip())
        if not chunk:
            continue
        parts = re.findall(rf".+?\b{NAME_END}(?=\s|$)", chunk)
        rest = re.sub(rf".+?\b{NAME_END}(?=\s|$)", "", chunk).strip() if parts else chunk
        out += [re.sub(r"^\d{1,4}[.)]?\s+", "", p.strip()) for p in parts]
        if rest and rest != chunk:
            out.append(rest)
        elif not parts:
            out.append(chunk)
    return [o for o in out if o]


def looks_like_name(s):
    if len(s) < 4 or SKIP.match(s):
        return False
    if not re.search(r"[A-Za-z]{2}", s):
        return False
    if re.search(rf"\b{NAME_END}$", s):
        return True
    return False


def parse_text(text):
    names = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for n in split_names(line):
            n = re.sub(r"\s+", " ", n).strip(" ,;")
            if looks_like_name(n):
                names.append(n)
    return names


def parse_pdf(body):
    import pdfplumber

    texts = []
    with pdfplumber.open(io.BytesIO(body)) as pdf:
        for p in pdf.pages:
            texts.append(p.extract_text(layout=True) or "")
    text = "\n".join(texts)
    return parse_text(text), text


def parse_xlsx(body):
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(body), read_only=True, data_only=True)
    lines = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
            if cells:
                lines.append("   ".join(cells))
    text = "\n".join(lines)
    return parse_text(text), text


def find_date(text):
    m = re.search(rf"(?:as at|as of|pada|sehingga)\s+(\d{{1,2}})\s+({MONTHS})\s+(20\d\d)", text, re.I)
    if not m:
        m = re.search(rf"(\d{{1,2}})\s+({MONTHS})\s+(20\d\d)", text, re.I)
    if m:
        mon = [x.lower() for x in MONTHS.split("|")].index(m.group(2).lower()) + 1
        return date(int(m.group(3)), mon, int(m.group(1))).isoformat()
    t = date.today()
    cands = [last_friday(y, m) for y in (t.year - 1, t.year) for m in (5, 11)]
    return max(d for d in cands if d <= t).isoformat()


def match_codes(names):
    """Padankan nama SC dengan kod Bursa guna senarai simbol (jika ada)."""
    if not os.path.exists(SYMBOLS):
        return {}, names
    syms = json.load(open(SYMBOLS))
    idx = {}
    for s in syms:
        idx.setdefault(norm_name(s["name"]), s["code"])
    codes, unmatched = {}, []
    for n in names:
        c = idx.get(norm_name(n))
        if c:
            codes[c] = n
        else:
            unmatched.append(n)
    return codes, unmatched


def main():
    state = json.load(open(OUT)) if os.path.exists(OUT) else {"lists": []}
    kind, body, final_url = fetch(PERMALINK)
    h = hashlib.sha256(body).hexdigest()
    if state.get("sourceHash") == h and state.get("lists"):
        print("Senarai SC tidak berubah — tiada kemas kini.")
        return
    names, text = parse_pdf(body) if kind == "pdf" else parse_xlsx(body)
    names = list(dict.fromkeys(names))
    print(f"Dokumen: {kind} dari {final_url} · {len(names)} nama dikesan")
    if len(names) < MIN_NAMES:
        open("sc-debug.txt", "w").write(text)
        raise SystemExit(
            f"GAGAL: hanya {len(names)} nama dikesan (< {MIN_NAMES}). Susun atur dokumen SC mungkin berubah. "
            "Senarai lama TIDAK diubah. Semak sc-debug.txt dalam artifact workflow."
        )
    d = find_date(text)
    codes, unmatched = match_codes(names)
    new = {"date": d, "names": names, "codes": codes, "count": len(names)}
    lists = [x for x in state.get("lists", []) if x["date"] != d]
    lists.append(new)
    lists.sort(key=lambda x: x["date"])
    state = {
        "updated": date.today().isoformat(),
        "source": final_url,
        "sourceHash": h,
        "lists": lists[-2:],
        "unmatched": unmatched,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(state, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"✓ Senarai SC {d}: {len(names)} nama, {len(codes)} dipadankan dengan kod, {len(unmatched)} belum dipadankan")


if __name__ == "__main__":
    main()
