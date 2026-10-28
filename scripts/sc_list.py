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


UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "sc-upload")
LIST_PAGE = os.environ.get(
    "SC_LIST_PAGE",
    "https://www.sc.com.my/development/icm/shariah-compliant-securities/list-of-shariah-compliant-securities",
)
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")
DEBUG = []


def log(msg):
    print(msg)
    DEBUG.append(str(msg))


def kind_of(body, ctype=""):
    if body[:4] == b"%PDF" or "pdf" in ctype:
        return "pdf"
    if body[:2] == b"PK" or "spreadsheet" in ctype or "excel" in ctype:
        return "xlsx"
    return None


def from_upload():
    """Sandaran manual: fail PDF/XLSX terbaharu dalam data/sc-upload/."""
    if not os.path.isdir(UPLOAD_DIR):
        return None
    files = [os.path.join(UPLOAD_DIR, f) for f in os.listdir(UPLOAD_DIR) if f.lower().endswith((".pdf", ".xlsx"))]
    if not files:
        return None
    f = max(files, key=lambda p: (os.path.getmtime(p), p))
    body = open(f, "rb").read()
    k = kind_of(body)
    log(f"Fail muat naik manual: {os.path.basename(f)} ({k}, {len(body)} bait)")
    return (k, body, "upload:" + os.path.basename(f)) if k else None


def from_requests(url):
    r = requests.get(url, headers={"User-Agent": BROWSER_UA, "Accept": "*/*"}, timeout=90, allow_redirects=True)
    ctype = r.headers.get("content-type", "").lower()
    log(f"GET {url} → {r.status_code} {ctype} {len(r.content)} bait (akhir: {r.url})")
    if r.ok:
        k = kind_of(r.content, ctype)
        if k:
            return k, r.content, r.url
    return None


def pick_link(links):
    """Pilih dokumen senarai terkini dari pautan jadual SC."""
    def score(l):
        t = (l.get("text") or "").lower()
        s = 0
        if "shariah" in t or "syariah" in t:
            s += 5
        if "list" in t or "senarai" in t:
            s += 3
        if "compliant" in t or "patuh" in t:
            s += 3
        if re.search(r"ipo|seeking listing|listing on", t):
            s -= 6
        if "download pdf" in t:
            s += 2
        if re.search(r"organisation structure|derivatives|act 20\d\d|annual report", t):
            s -= 8
        m = re.search(rf"(\d{{1,2}})\s+({MONTHS})\s+(20\d\d)", l.get("text") or "", re.I)
        d = ""
        if m:
            mon = [x.lower() for x in MONTHS.split("|")].index(m.group(2).lower()) + 1
            d = f"{m.group(3)}-{mon:02d}-{int(m.group(1)):02d}"
        return (s, d)
    cands = [l for l in links if re.search(r"download\.ashx|\.pdf|\.xlsx|documentms", l["href"], re.I)]
    cands.sort(key=score, reverse=True)
    return cands


def from_browser(url):
    """Buka halaman SC dengan Chromium, tunggu jadual dimuatkan, muat turun dokumen terkini."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("Playwright tiada — langkau pelayar.")
        return None
    with sync_playwright() as pw:
        b = pw.chromium.launch(args=["--no-sandbox"])
        ctx = b.new_context(user_agent=BROWSER_UA, locale="en-MY", accept_downloads=True)
        pg = ctx.new_page()
        pg.goto(url, wait_until="domcontentloaded", timeout=90000)
        try:
            pg.wait_for_load_state("networkidle", timeout=45000)
        except Exception:
            pass
        for _ in range(20):  # tunggu baris jadual muncul
            n = pg.evaluate("document.querySelectorAll('table a[href], tbody a[href]').length")
            if n:
                break
            pg.wait_for_timeout(1500)
        links = pg.evaluate("""()=>[...document.querySelectorAll('a[href]')]
            .filter(a=>!a.closest('header,footer,nav,.header,.footer,.navbar,.menu,.mega-menu'))
            .map(a=>{let el=a,t='';for(let i=0;i<5&&el;i++){t=(el.innerText||'').replace(/\\s+/g,' ').trim();
              if(t.length>=30&&t.replace(/download pdf/ig,'').trim().length>=20)break;el=el.parentElement;}
              return {href:a.href,text:t.slice(0,300)};})""")
        log(f"Pelayar: {pg.url} · tajuk '{pg.title()}' · {len(links)} pautan")
        cands = pick_link(links)
        for l in cands[:8]:
            log(f"  calon: {l['text'][:120]} → {l['href']}")
        if not cands:
            DEBUG.append("---- TEKS HALAMAN ----\n" + pg.evaluate("document.body.innerText")[:6000])
        best, seen = None, set()
        for l in cands[:10]:
            if l["href"] in seen:
                continue
            seen.add(l["href"])
            try:
                r = ctx.request.get(l["href"], timeout=90000)
                body = r.body()
                k = kind_of(body, (r.headers.get("content-type") or "").lower())
                if not (r.ok and k):
                    log(f"  muat turun {l['href']} → {r.status} {k} — langkau")
                    continue
                names, text = parse_pdf(body) if k == "pdf" else parse_xlsx(body)
                is_list = bool(re.search(r"shariah[- ]compliant securities", text[:4000], re.I))
                d = find_date(text) if is_list else ""
                log(f"  semak {l['href']} → {len(body)} bait, {len(set(names))} nama, senarai SC: {is_list}, tarikh {d or '-'}")
                if is_list and len(set(names)) >= MIN_NAMES and (not best or d > best[3]):
                    best = (k, body, l["href"], d)
            except Exception as e:
                log(f"  gagal {l['href']}: {e}")
        if best:
            b.close()
            return best[:3]
        b.close()
    return None


def fetch_document():
    for name, fn in (("permalink", lambda: from_requests(PERMALINK)),
                     ("pelayar: halaman senarai", lambda: from_browser(LIST_PAGE)),
                     ("pelayar: permalink", lambda: from_browser(PERMALINK))):
        try:
            log(f"Cuba sumber: {name}")
            res = fn()
            if res:
                return res
        except Exception as e:
            log(f"  ralat {name}: {type(e).__name__}: {e}")
    return None


def write_debug(extra=""):
    open("sc-debug.txt", "w").write("\n".join(DEBUG) + ("\n\n" + extra if extra else ""))


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
    res = from_upload()
    if res:
        h = hashlib.sha256(res[1]).hexdigest()
        if h in (state.get("sourceHash"), state.get("uploadHash")) and state.get("lists"):
            log("Fail muat naik manual sama seperti sebelum ini — semak laman SC pula.")
            res = None
    if not res:
        res = fetch_document()
    if not res:
        write_debug()
        raise SystemExit("GAGAL: dokumen senarai SC tidak dapat dimuat turun. Senarai lama TIDAK diubah. "
                         "Lihat sc-debug.txt, atau letak PDF SC dalam data/sc-upload/.")
    kind, body, final_url = res
    h = hashlib.sha256(body).hexdigest()
    if state.get("sourceHash") == h and state.get("lists"):
        print("Senarai SC tidak berubah — tiada kemas kini.")
        return
    names, text = parse_pdf(body) if kind == "pdf" else parse_xlsx(body)
    names = list(dict.fromkeys(names))
    log(f"Dokumen: {kind} dari {final_url} · {len(names)} nama dikesan")
    if len(names) < MIN_NAMES:
        write_debug("---- TEKS DOKUMEN ----\n" + text[:20000])
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
        "uploadHash": h if final_url.startswith("upload:") else state.get("uploadHash"),
        "lists": lists[-2:],
        "unmatched": unmatched,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(state, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"✓ Senarai SC {d}: {len(names)} nama, {len(codes)} dipadankan dengan kod, {len(unmatched)} belum dipadankan")


if __name__ == "__main__":
    main()
