"""Robot 3: tarik tajuk berita terkini (Google News RSS) untuk saham yang ada isyarat aktif.

Output: <out>/news.json dan data/news.json (disimpan dalam repo supaya berita lama dikekalkan).
Hanya tajuk, sumber, tarikh dan pautan disimpan — pengguna membaca berita penuh di laman asal.
Penanda nada (+ / − / ·) dikira dengan kata kunci ringkas, bukan analisa sentimen penuh.
"""
import argparse
import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests

ROOT = os.path.join(os.path.dirname(__file__), "..")
STORE = os.path.join(ROOT, "data", "news.json")
MAX_STOCKS = 80
KEEP_DAYS = 30
PER_STOCK = 6

POS = ["profit rise", "profit jump", "higher profit", "net profit up", "record", "contract", "secures", "wins", "bags",
       "award", "dividend", "bonus issue", "surge", "jumps", "soars", "rally", "upgrade", "acquire", "expansion", "order book",
       "rise", "rises", "gain", "gains", "boost", "growth", "beats", "strong", "untung meningkat", "kontrak", "anugerah", "dividen", "melonjak", "naik", "peroleh"]
NEG = ["loss", "losses", "falls", "fall", "plunge", "slump", "drop", "probe", "investigat", "lawsuit", "sued", "downgrade",
       "pn17", "default", "resign", "quits", "fraud", "warning", "delay", "terminated", "rugi", "jatuh", "merosot", "siasat",
       "saman", "letak jawatan", "weak", "lower profit", "cuts", "slides"]

SUFFIX = re.compile(r"\b(berhad|bhd\.?|holdings?|group|corporation|corp\.?|resources|industries|technologies|international)\b", re.I)


def short_name(n):
    n = re.sub(r"\s*\(.*?\)", "", n or "").strip()
    n = re.sub(r"\b(berhad|bhd\.?)$", "", n, flags=re.I).strip()
    return n


def tone(title):
    t = title.lower()
    p = any(k in t for k in POS)
    q = any(k in t for k in NEG)
    return "+" if p and not q else "-" if q and not p else "0"


def fetch(name):
    q = f'"{name}" (Bursa OR Berhad OR Bhd OR saham) when:{KEEP_DAYS}d'
    url = f"https://news.google.com/rss/search?q={quote(q)}&hl=en-MY&gl=MY&ceid=MY:en"
    r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (ProSyariah news bot)"})
    r.raise_for_status()
    root = ET.fromstring(r.content)
    out = []
    key = SUFFIX.sub("", name).strip().lower() or name.lower()
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        src = (it.findtext("source") or "").strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3].strip()
        if " estimates – " in title.lower() or " estimates - " in title.lower():
            continue  # halaman anggaran automatik, bukan berita
        if key.split()[0] not in title.lower():
            continue  # buang hasil yang tidak menyebut syarikat
        try:
            d = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone(timedelta(hours=8)))  # tarikh waktu Malaysia
        except Exception:
            continue
        out.append({"t": title, "s": src, "u": (it.findtext("link") or "").strip(), "d": d.strftime("%Y-%m-%d"), "x": tone(title)})
    out.sort(key=lambda x: x["d"], reverse=True)
    seen, res = set(), []
    for x in out:
        k = x["t"].lower()[:60]
        if k in seen:
            continue
        seen.add(k)
        res.append(x)
    return res[:PER_STOCK]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "_site", "data"))
    a = ap.parse_args()
    M = json.load(open(os.path.join(a.out, "market.json")))
    stocks = M["stocks"]
    old = json.load(open(STORE)) if os.path.exists(STORE) else {"items": {}}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")

    # Keutamaan: isyarat aktif (patuh), kemudian skor teknikal tinggi
    act = [c for c, v in stocks.items() if v.get("s") == "ok" and any((o.get("ago") or 0) <= 2 and (o.get("ev") or 0) > 0 for o in v.get("op", []))]
    strong = sorted([c for c, v in stocks.items() if v.get("s") == "ok" and (v.get("sc") or 0) >= 4 and c not in act],
                    key=lambda c: -(stocks[c].get("sc") or 0))
    codes = (act + strong)[:MAX_STOCKS]

    items = {c: [x for x in v if x["d"] >= cutoff] for c, v in old.get("items", {}).items()}
    ok = fail = 0
    for c in codes:
        nm = short_name(stocks[c].get("n"))
        if not nm:
            continue
        try:
            got = fetch(nm)
            merged = got + [x for x in items.get(c, []) if x["t"] not in {g["t"] for g in got}]
            items[c] = sorted(merged, key=lambda x: x["d"], reverse=True)[:PER_STOCK]
            ok += 1
        except Exception as e:
            fail += 1
            print("  gagal", c, nm, e)
        time.sleep(0.8)
    items = {c: v for c, v in items.items() if v}
    out = {"asof": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "items": items}
    json.dump(out, open(os.path.join(a.out, "news.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    json.dump(out, open(STORE, "w"), ensure_ascii=False, separators=(",", ":"))
    print(f"✓ Berita: {ok} saham disemak, {fail} gagal, {len(items)} saham ada berita")


if __name__ == "__main__":
    main()
