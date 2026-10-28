# ProSyariah by ProKuiz

App saringan syariah & **indicator** saham Bursa. Ia memaparkan indicator, bukan untuk membeli atau menjual saham. Semua data dikemas kini **automatik** oleh robot GitHub — pengguna hanya buka app dan nilai keputusan.

## Apa yang robot buat

| Bila | Apa |
|---|---|
| Setiap hari bekerja, 6.30 ptg (MYT) | Tarik harga harian semua kaunter Bursa, kira skor teknikal, RSI, MACD, EMA, golden cross |
| Setiap kali berjalan | Semak Senarai Sekuriti Patuh Syariah SC melalui pautan tetap SC; jika ada senarai baharu, baca dan simpan |
| Sabtu 10 pagi (MYT) | Larian tambahan untuk tangkap senarai SC yang terbit Jumaat terakhir Mei / November |

Hasilnya diterbitkan ke GitHub Pages. App membaca `data/market.json`, `data/sc-list.json` dan `data/s/<kod>.json`.

Jika bacaan senarai SC gagal (contohnya SC tukar susun atur dokumen), robot **tidak** mengubah senarai lama, dan GitHub hantar emel kepada anda. Log disimpan sebagai artifact `sc-debug`.

## Kebarangkalian & paras harga (indicator)

Robot menjalankan **backtest** atas sejarah ~5 tahun setiap saham untuk 4 persediaan beli
(koreksi dalam trend menaik, golden cross, momentum MACD, lantunan lebih jualan).
Setiap kali isyarat berlaku dalam sejarah, robot mencatat sama ada harga sampai **paras atas (2× ATR)**
atau **paras bawah (1.25× ATR)** dahulu, atau tiada dalam **40 hari dagangan**. Kos 0.3% diambil kira. App memaparkan:

- **% kebarangkalian** harga sampai paras atas sebelum paras bawah (dengan pelarasan untuk sampel kecil)
- **Paras neutral** — kadar dijangka jika pergerakan harga rawak
- **Tempoh biasa** ke paras atas (median & julat hari dagangan)
- **Paras sokongan mengekor** untuk pegangan (harga tertinggi − 2.5× ATR)

Tetapan boleh diubah di `scripts/backtest.py` (H, TGT_ATR, STP_ATR, FEE).
Ini statistik sejarah, bukan jaminan.

## Ketepatan isyarat (forward test)

Setiap isyarat teknikal baharu direkod dalam `data/signals.json` dan disemak dengan harga sebenar
hari-hari berikutnya (paras atas / paras bawah / 40 hari). App memaparkan kadar sebenar berbanding
dijangka, prestasi ikut jenis isyarat, dan semakan kalibrasi. Tiada isyarat dipadam atau dipilih.

## Dwibahasa

- Butang **BM | EN** di header menukar seluruh app. Terjemahan dalam `index.html` (EN_EXACT, EN_RX).

## Pemasangan (sekali sahaja)

1. **Cipta repo baharu** di GitHub, contohnya `prosyariah`, dan muat naik semua fail dalam folder ini (termasuk folder tersembunyi `.github`).
2. **Kunci EODHD (percuma)** — daftar di eodhd.com, salin API key.
   Repo → *Settings → Secrets and variables → Actions → New repository secret*
   - Nama: `EODHD_API_KEY`  · Nilai: kunci anda
   Kunci ini hanya digunakan untuk senarai kod saham KLSE (1 panggilan sehari).
3. **Hidupkan GitHub Pages** — *Settings → Pages → Build and deployment → Source: **GitHub Actions***.
4. **Jalankan robot kali pertama** — tab *Actions → Kemas kini data ProSyariah → Run workflow*. Tunggu ~5–15 minit.
5. Buka `https://USERNAME.github.io/prosyariah/` — app sudah berfungsi dengan data penuh.

## Untuk APK

Dalam `index.html`, tukar baris ini kepada alamat Pages anda:

```js
const PAGES_URL='https://USERNAME.github.io/prosyariah/';
```

Kemudian bina APK seperti biasa. (Atau jadikan APK sebagai pembungkus yang terus membuka alamat Pages — app sentiasa versi terkini tanpa bina semula.)

## Pilihan lanjutan

- **Penyedia harga**: lalai `yfinance` (percuma). Untuk guna EODHD berbayar, tambah *Variable* `PRICE_PROVIDER` = `eodhd` (Settings → Secrets and variables → Actions → Variables).
- **Uji tempatan**: `pip install -r requirements.txt` kemudian `python scripts/sc_list.py` dan `python scripts/market.py --limit 20`.

## Penting sebelum dilancarkan kepada orang awam

- **Lesen data harga**: yfinance dan pelan peribadi EODHD untuk kegunaan peribadi. Jika app diedarkan kepada orang awam, dapatkan pelan data komersial (contohnya EODHD Commercial) atau penyedia data Bursa berlesen.
- **Isyarat teknikal kepada orang awam** boleh dianggap nasihat pelaburan di bawah peraturan SC. Dapatkan nasihat undang-undang sebelum mengkomersialkan.
- **Semakan syariah**: dapatkan pengesahan penasihat syariah bertauliah untuk formula penyucian dan panduan tindakan.
