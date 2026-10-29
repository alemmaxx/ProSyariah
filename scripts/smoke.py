"""Ujian ringkas app sebelum dinaikkan: buka laman dalam pelayar, semak skrin utama, Robot, Tetapan
dan alat, dalam BM & EN. Gagal (exit 1) jika ada ralat JavaScript atau bahagian penting tiada.

Guna: python scripts/smoke.py --site _site
"""
import argparse
import functools
import http.server
import os
import socketserver
import sys
import threading


def serve(root):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    h = functools.partial(Quiet, directory=root)
    srv = socketserver.TCPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def main():
    from playwright.sync_api import sync_playwright

    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="_site")
    ap.add_argument("--min", type=int, default=500)
    a = ap.parse_args()
    srv, port = serve(os.path.abspath(a.site))
    base = f"http://127.0.0.1:{port}/"
    errs, fails = [], []

    def check(cond, msg):
        if not cond:
            fails.append(msg)
            print("  ✗", msg)
        else:
            print("  ✓", msg)

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page(viewport={"width": 390, "height": 844})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        # luar talian: jangan bergantung pada fon / Firebase semasa ujian
        pg.route("https://fonts.**", lambda r: r.abort())
        pg.route("https://www.gstatic.com/**", lambda r: r.abort())
        pg.goto(base + "index.html")
        pg.evaluate("localStorage.setItem('prosyariah_v1', JSON.stringify({onb:2,settings:{lang:'bm'}}))")
        pg.reload()
        pg.wait_for_function("typeof S!=='undefined' && S.market && S.market.stocks", timeout=30000)
        pg.wait_for_timeout(1500)
        n = pg.evaluate("Object.keys(S.market.stocks).length")
        check(n > a.min, f"data pasaran dimuat ({n} kaunter)")
        check(pg.locator(".hero").count() > 0, "skrin utama: bahagian utama ada")
        check(pg.locator(".tools3").count() > 0, "skrin utama: Penapis / Kalendar / Banding ada")
        for fn in ["openScreener()", "openCal()", "CMP=[];openCompare()"]:
            pg.evaluate(fn)
            pg.wait_for_timeout(300)
            check(pg.locator("#sheetBody").inner_text().strip() != "", f"pop up {fn.split(';')[-1]} dibuka")
            pg.evaluate("closeSheet()")
        for tab in ["robot", "portfolio", "tathir", "zakat", "tetapan", "saham"]:
            pg.evaluate(f"goTab('{tab}')")
            pg.wait_for_timeout(300)
            check(len(pg.inner_text("#main").strip()) > 20, f"tab {tab} dipaparkan")
        pg.evaluate("setLang('en')")
        pg.wait_for_timeout(500)
        check("Settings" in pg.inner_text("nav"), "terjemahan EN berfungsi")
        b.close()
    srv.shutdown()
    for e in errs:
        print("  ✗ ralat JavaScript:", e)
    if errs or fails:
        print(f"::error::Ujian app gagal ({len(fails)} semakan, {len(errs)} ralat JS). Versi baharu TIDAK dinaikkan.")
        sys.exit(1)
    print("✓ Ujian app lulus")


if __name__ == "__main__":
    main()
