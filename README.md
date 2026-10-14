# Facebook Marketplace Bot

Facebook marketplace bot that automatically removes and then uploads listings from CSV Files. You can define all of the information about the items and vehicles that will be posted automatically so you will save time removing and publishing them every single time. We are doing this to show the listings on the top of the marketplace or groups in order to be seen by more people and that leads to selling the items or vehicles faster.

## Table of Contents
- [Technologies used](#technologies-used)
- [Functionalities](#functionalities)
- [Installation](#installation)
- [How to Use](#how-to-use)

## Technologies Used
- Python
- Selenium
- Pickle

## Functionalities
- You can add multiple items or vehicles in the csv files that are in folder `csvs`. Note that for now the program only works with listing type `Item` or `Vehicle`
- Added items or vehicles in csv files are first checked if they exist by the title. Listings that are already on your account are **skipped** (not removed and re-published), so the bot never creates a duplicate. Listings that fail are left in the CSV so the next run retries only those.
- The item or vehicle can also be posted to multiple groups that you can define in the csv files

## Installation
1. You will need to have [Python](https://www.python.org/downloads/) and [pip](https://pip.pypa.io/en/stable/installation/) installed (on Mac they are already installed)
2. Install the project dependencies with `pip`:
    - Windows:
      ```
      python -m pip install -r requirements.txt
      ```
    - Linux or macOS:
      ```
      python3 -m pip install -r requirements.txt
      ```
3. Install the `Google Chrome` browser if you don't have it already - https://www.google.com/chrome/.

## How to Use
1. Open folder where this project is saved on your local machine
2. Open the `csvs` folder
3. Add items or vehicles in the `items.csv` and `vehicles.csv` files. You can open these files with programs like `Microsoft Excel`, `LibreOffice Calc`, etc
4. Please note these things for the csv columns:
	- `Photos Folder` column you will have to define only the folder path for the photos like this:
	    - Windows `C:\Pictures`
	    - Linux/Mac `/Users/myuser/Pictures`
	- `Photos Names` column should only have the names of photos separated with this symbol `;` like this `Photo 1.JPG; Photo 2.png; Photo3.jpg`
	- Marketplace fields that you have to select an option like `Category`, `Condition`, `Vehicle Type`, `Fuel Type`. You have to type the exact name of the option that you want to choose.
	- `Groups` column can have multiple groups and you will have to type their exact name and separate them by this symbol `;`. Example - `Group name 1; Group name 2; Group name`
5. Open terminal inside the main project folder
6. Run main.py with this command:
    - Windows / Linux
        ```
        python main.py
        ```
    - Mac
        ```
        python3 main.py
        ```
7. The first time that you use the program, you will have to log in manually in the browser that have opened. After that the program will log in you automatically using the cookies from the first log in.
   - To switch accounts, close the program and rename or remove `cookies/facebook.pkl`, then run `python main.py --login-only` and log in with the other account. This saves the new session without processing listings; run `python main.py` afterward when you are ready to publish. Empty or damaged cookie files are ignored so you can log in again. The browser reports a clear error if Facebook does not finish loading within 60 seconds; check your internet connection and retry.

### Mencari listing yang sudah ada

Secara default bot mencari dulu setiap judul di halaman tawaran Anda, lalu melewati yang sudah ada supaya tidak jadi duplikat. Kalau kotak pencarian tidak muncul (UI Facebook berubah, atau halaman lambat), hasil pencarian menjadi tidak diketahui. Bot sekarang **tetap menerbitkan** dan menampilkan peringatan, tidak lagi melewati semua produk.

Kalau Anda ingin langsung terbit tanpa pencarian sama sekali:

```text
python main.py --skip-existing-check
```

Atau beri tanda pada kotak **"Terbitkan langsung tanpa mencari listing yang sudah ada"** di panel lokal sebelum menekan tombol mulai.

> Peringatan: dengan opsi ini bot tidak menghindari duplikat, jadi menjalankannya dua kali akan membuat listing ganda di akun Anda.

## Local Web Panel
Run the local control panel from the project folder:

```text
python web_app.py
```

The panel opens at `http://127.0.0.1:8765`. It can start and stop the bot, show its recent output, and report the number of rows in each CSV. It also links to `index.html`, the CSV generator.

The panel is local-only: it binds to `127.0.0.1`. Keep the project and its cookie file private. If the bot was started separately with `python main.py`, wait for that run to finish before starting it from the panel.

Setiap listing yang berhasil dicatat di `csvs/<nama>_done.csv`. File ini memakai satu header tetap untuk semua batch, sehingga menambah kolom baru pada satu listing tidak menggeser nilai listing lain. Foto yang sudah dipakai dipindahkan ke subfolder `uploaded_done` di dalam folder foto tersebut.

### Menyiapkan produk dari ekspor Shopee (opsional)

`prepare_import.py` mengubah file Excel ekspor Shopee menjadi `csvs/imported_items.csv` beserta foto lokalnya:

```text
python prepare_import.py "C:\path\ke\500_produk.xlsx"
```

Path bisa juga diatur lewat environment variable `MARKETPLACE_SOURCE_EXCEL`. Jika tidak diberikan, script memakai path default yang tertulis di `prepare_import.py`. Produk tanpa foto yang berhasil diunduh dilewati tanpa membuat folder kosong.

Setelah file disiapkan, salin hasilnya ke `items.csv` supaya tombol **Jalankan CSV lama** di panel membacanya:

```text
copy csvs\imported_items.csv csvs\items.csv
```

### Pemulihan error saat publikasi

Jika satu listing gagal, bot mencatat error dan melanjutkan batch. Sebelum mencoba ulang satu kali, bot kembali ke daftar tawaran dan memeriksa apakah listing tersebut sudah muncul; jika statusnya tidak bisa dipastikan, bot tidak mengirim ulang dan lanjut ke produk berikutnya untuk menghindari duplikat. Ringkasan akhir menampilkan jumlah listing yang terbit/terkonfirmasi, sudah ada, dan gagal/dilewati. Error browser atau login yang membuat sesi tidak dapat digunakan tetap memerlukan tindakan manual.
