import argparse
import csv
import hashlib
import os
import re
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from openpyxl import load_workbook

from helpers.csv_helper import normalize_marketplace_title


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_CSV = PROJECT_ROOT / 'csvs' / 'imported_items.csv'
IMAGE_ROOT = PROJECT_ROOT / 'images' / 'imported_items'
IMAGE_CACHE = IMAGE_ROOT / '_source'
DEFAULT_SOURCE_FILE = Path(
	r'C:\Users\lanib\Downloads\500_produk_fixed_tanpa_duplikat.xlsx'
)
PRICE = '5000'
LOCATION = 'Cirebon'
MAX_PHOTOS_PER_ITEM = 3
MAX_IMAGE_BYTES = 20 * 1024 * 1024

CATEGORY_MAP = {
	'Fashion Accessories': 'Jewellery and accessories',
	'Muslim Fashion': 'Clothing & accessories',
	'Men Clothes': "Men's clothing & shoes",
	'Women Clothes': "Women's clothing & shoes",
	'Baby & Kids Fashion': 'Baby & children',
	'Women Bags': 'Bags & luggage',
	'Sports & Outdoors': 'Sport and outdoors',
	'Beauty': 'Health & beauty',
	'Health': 'Health & beauty',
	'Food & Beverages': 'Health & beauty',
	'Motorcycles': 'Vehicles'
}

ITEM_COLUMNS = [
	'Title',
	'Photos Folder',
	'Photos Names',
	'Price',
	'Category',
	'Condition',
	'Brand',
	'Description',
	'Location',
	'Groups'
]

IMAGE_EXTENSIONS = {
	'image/jpeg': '.jpg',
	'image/png': '.png',
	'image/webp': '.webp'
}


def _download_image(url):
	parsed_url = urlparse(url)
	if parsed_url.scheme != 'https' or parsed_url.hostname != 'cf.shopee.co.id':
		return None, 'URL foto bukan domain Shopee yang diharapkan.'

	cache_prefix = IMAGE_CACHE / hashlib.sha256(url.encode('utf-8')).hexdigest()
	for extension in IMAGE_EXTENSIONS.values():
		cached_file = cache_prefix.with_suffix(extension)
		if cached_file.is_file() and cached_file.stat().st_size:
			return cached_file, None

	request = Request(
		url,
		headers={'User-Agent': 'Mozilla/5.0'}
	)
	for attempt in range(3):
		try:
			with urlopen(request, timeout=25) as response:
				content_type = response.headers.get_content_type()
				extension = IMAGE_EXTENSIONS.get(content_type)
				if extension is None:
					return None, 'Sumber tidak mengembalikan format gambar yang didukung.'

				image_bytes = response.read(MAX_IMAGE_BYTES + 1)
				if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
					return None, 'Ukuran foto kosong atau melebihi 20 MB.'

				if content_type == 'image/jpeg' and not image_bytes.startswith(b'\xff\xd8'):
					return None, 'Konten foto JPEG tidak valid.'
				if content_type == 'image/png' and not image_bytes.startswith(b'\x89PNG\r\n\x1a\n'):
					return None, 'Konten foto PNG tidak valid.'

				cache_file = cache_prefix.with_suffix(extension)
				IMAGE_CACHE.mkdir(parents=True, exist_ok=True)
				with tempfile.NamedTemporaryFile(
					mode='wb',
					dir=IMAGE_CACHE,
					delete=False
				) as temporary_file:
					temporary_file.write(image_bytes)
					temporary_path = Path(temporary_file.name)
				os.replace(temporary_path, cache_file)
				return cache_file, None
		except (HTTPError, URLError, TimeoutError, OSError) as error:
			if attempt == 2:
				return None, str(error)
			time.sleep(1 + attempt * 2)
	return None, 'Unduhan foto gagal setelah beberapa percobaan.'


def _read_source_rows(source_file):
	if not source_file.is_file():
		raise FileNotFoundError('File Excel sumber tidak ditemukan: ' + str(source_file))

	workbook = load_workbook(source_file, read_only=True, data_only=True)
	try:
		worksheet = workbook.active
		headers = [cell.value for cell in worksheet[3]]
		required_headers = ('Nama Produk', 'Kategori', 'Foto Sampul')
		missing = [header for header in required_headers if header not in headers]
		if missing:
			raise ValueError(
				'Kolom wajib tidak ditemukan di baris 3: ' + ', '.join(missing)
			)

		columns = {header: headers.index(header) for header in headers if header}
		photo_columns = [
			header for header in headers
			if header == 'Foto Sampul' or re.fullmatch(r'Foto Produk \d+', str(header or ''))
		]

		rows = []
		seen_source_titles = set()
		seen_marketplace_titles = set()
		duplicate_count = 0
		for row_number, values in enumerate(
			worksheet.iter_rows(min_row=6, values_only=True),
			start=6
		):
			title_value = values[columns['Nama Produk']] if columns['Nama Produk'] < len(values) else None
			if title_value is None or not str(title_value).strip():
				continue

			source_title = ' '.join(str(title_value).split())
			source_key = source_title.casefold()
			if source_key in seen_source_titles:
				duplicate_count += 1
				continue
			seen_source_titles.add(source_key)

			product_id = str(
				values[columns['Kode Produk']]
				if 'Kode Produk' in columns
				and columns['Kode Produk'] < len(values)
				and values[columns['Kode Produk']]
				else row_number
			).strip()

			title = normalize_marketplace_title(source_title)
			if title.casefold() in seen_marketplace_titles:
				id_suffix = re.sub(r'[^A-Za-z0-9]+', '', product_id)[-6:]
				if not id_suffix:
					id_suffix = str(row_number)
				suffix = ' [' + id_suffix + ']'
				base_limit = 80 - len(suffix)
				shortened_base = source_title[:base_limit].rsplit(' ', 1)[0].rstrip()
				if not shortened_base:
					shortened_base = source_title[:base_limit].rstrip()
				title = shortened_base + suffix
				if title.casefold() in seen_marketplace_titles:
					suffix = ' [' + str(row_number) + ']'
					base_limit = 80 - len(suffix)
					shortened_base = source_title[:base_limit].rsplit(' ', 1)[0].rstrip()
					if not shortened_base:
						shortened_base = source_title[:base_limit].rstrip()
					title = shortened_base + suffix
			seen_marketplace_titles.add(title.casefold())

			raw_category = str(
				values[columns['Kategori']] if columns['Kategori'] < len(values) else ''
			).strip()
			if ' - ' in raw_category:
				raw_category = raw_category.split(' - ', 1)[1].strip()
			category_root = raw_category.split('/', 1)[0].strip()
			category = CATEGORY_MAP.get(category_root)
			if category is None:
				print(
					'Skipping Excel row '
					+ str(row_number)
					+ ': no Facebook category mapping for '
					+ repr(category_root)
				)
				continue

			photo_urls = []
			for photo_column in photo_columns:
				index = columns[photo_column]
				url = str(values[index]).strip() if index < len(values) and values[index] else ''
				if url.startswith('https://') and url not in photo_urls:
					photo_urls.append(url)
				if len(photo_urls) == MAX_PHOTOS_PER_ITEM:
					break

			rows.append({
				'row_number': row_number,
				'product_id': product_id,
				'Title': title,
				'Category': category,
				'Photo URLs': photo_urls
			})

		return rows, duplicate_count
	finally:
		workbook.close()


def prepare_import(source_file=None):
	"""Prepare imported_items.csv and its local photos from a Shopee export."""
	if source_file is None:
		source_file = DEFAULT_SOURCE_FILE

	products, duplicate_count = _read_source_rows(source_file)
	urls = {
		url
		for product in products
		for url in product['Photo URLs']
	}
	IMAGE_CACHE.mkdir(parents=True, exist_ok=True)

	print(
		'Downloading '
		+ str(len(urls))
		+ ' unique product photos for '
		+ str(len(products))
		+ ' unique product titles.'
	)
	downloaded = {}
	with ThreadPoolExecutor(max_workers=8) as executor:
		futures = {
			executor.submit(_download_image, url): url
			for url in urls
		}
		for completed, future in enumerate(as_completed(futures), start=1):
			url = futures[future]
			downloaded[url] = future.result()
			if completed % 50 == 0 or completed == len(futures):
				print(
					f'Downloaded {completed}/{len(futures)} unique product photos.',
					flush=True
				)

	items = []
	failed_products = 0
	failed_photos = 0
	for product_index, product in enumerate(products, start=1):
		# Download first so skipped products do not leave an empty folder behind.
		copied_photos = []
		for url in product['Photo URLs']:
			cached_file, error = downloaded[url]
			if error:
				failed_photos += 1
				continue
			copied_photos.append(cached_file)

		if not copied_photos:
			failed_products += 1
			print(
				'Skipping product without downloaded photos: '
				+ product['Title']
			)
			continue

		product_id = re.sub(r'[^A-Za-z0-9_-]+', '_', product['product_id'])
		photos_folder = IMAGE_ROOT / (f'{product_index:04d}_{product_id}')
		photos_folder.mkdir(parents=True, exist_ok=True)

		photo_names = []
		for cached_file in copied_photos:
			photo_name = f'{len(photo_names) + 1:02d}{cached_file.suffix}'
			shutil.copyfile(cached_file, photos_folder / photo_name)
			photo_names.append(photo_name)

		items.append({
			'Title': product['Title'],
			'Photos Folder': str(photos_folder.relative_to(PROJECT_ROOT)),
			'Photos Names': '; '.join(photo_names),
			'Price': PRICE,
			'Category': product['Category'],
			'Condition': 'New',
			'Brand': '',
			'Description': product['Title'],
			'Location': LOCATION,
			'Groups': ''
		})

	if not items:
		raise RuntimeError('Tidak ada produk dengan minimal satu foto yang berhasil disiapkan.')

	OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
	with tempfile.NamedTemporaryFile(
		mode='w',
		newline='',
		encoding='UTF-8-SIG',
		dir=OUTPUT_CSV.parent,
		delete=False
	) as temporary_csv:
		writer = csv.DictWriter(temporary_csv, fieldnames=ITEM_COLUMNS)
		writer.writeheader()
		writer.writerows(items)
		temporary_csv_path = Path(temporary_csv.name)
	os.replace(temporary_csv_path, OUTPUT_CSV)

	print(
		f'Prepared {len(items)} products; skipped {duplicate_count} duplicate titles, '
		f'{failed_products} products without photos, and {failed_photos} failed photo downloads.'
	)
	failed_urls = [
		(url, error)
		for url, (_, error) in downloaded.items()
		if error
	]
	for url, error in failed_urls[:20]:
		print('Photo download failed for ' + url + ': ' + error)
	if len(failed_urls) > 20:
		print(f'{len(failed_urls) - 20} additional photo download errors were omitted.')
	print('Saved listings to ' + str(OUTPUT_CSV))


def _resolve_source_file(argv):
	if argv:
		return Path(argv[0]).expanduser()
	environment_path = os.environ.get('MARKETPLACE_SOURCE_EXCEL')
	if environment_path:
		return Path(environment_path).expanduser()
	return DEFAULT_SOURCE_FILE


def main(argv=None):
	parser = argparse.ArgumentParser(
		description=(
			'Siapkan csvs/imported_items.csv beserta foto lokalnya dari file '
			'Excel ekspor Shopee.'
		)
	)
	parser.add_argument(
		'source',
		nargs='?',
		help=(
			'Path file .xlsx sumber. Bisa juga diatur lewat environment variable '
			'MARKETPLACE_SOURCE_EXCEL. Default: ' + str(DEFAULT_SOURCE_FILE)
		)
	)
	arguments = parser.parse_args(argv)
	prepare_import(_resolve_source_file([arguments.source] if arguments.source else []))


if __name__ == '__main__':
	main()
