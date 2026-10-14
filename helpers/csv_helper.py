import csv
import os
import re
import shutil
import sys
import tempfile
import unicodedata


MAX_MARKETPLACE_TITLE_LENGTH = 80
_FRACTION_REPLACEMENTS = {
	'½': ' 1/2 ',
	'¼': ' 1/4 ',
	'¾': ' 3/4 ',
	'⅓': ' 1/3 ',
	'⅔': ' 2/3 ',
	'⅛': ' 1/8 ',
	'⅜': ' 3/8 ',
	'⅝': ' 5/8 ',
	'⅞': ' 7/8 ',
	'⁄': ' / ',
	'∕': ' / ',
	'÷': ' / ',
}


def normalize_marketplace_title(title):
	title = unicodedata.normalize('NFKC', str(title or ''))
	for source, replacement in _FRACTION_REPLACEMENTS.items():
		title = title.replace(source, replacement)
	title = title.replace('–', ' - ').replace('—', ' - ').replace('‐', ' - ')
	title = title.replace('“', '"').replace('”', '"').replace('’', "'").replace('‘', "'")
	title = re.sub(r'\s+', ' ', title).strip()
	if len(title) <= MAX_MARKETPLACE_TITLE_LENGTH:
		return title

	shortened_title = title[:MAX_MARKETPLACE_TITLE_LENGTH].rsplit(' ', 1)[0].rstrip()
	return shortened_title or title[:MAX_MARKETPLACE_TITLE_LENGTH].rstrip()


def move_listing_photos_to_done(photos_folder, photos_names, done_folder_name='uploaded_done'):
	if not photos_folder or not photos_names:
		return

	target_dir = os.path.join(photos_folder, done_folder_name)
	os.makedirs(target_dir, exist_ok=True)

	names = [name.strip() for name in photos_names.split(';') if name.strip()]
	for name in names:
		src_path = os.path.join(photos_folder, name)
		if os.path.isfile(src_path):
			dest_path = os.path.join(target_dir, name)
			try:
				shutil.move(src_path, dest_path)
			except Exception as err:
				print('Gagal memindahkan file ' + name + ': ' + str(err))


def _write_done_csv(done_csv_path, rows, fieldnames):
	"""Rewrite the whole done CSV so every batch shares one stable header.

	Listings published in different batches can carry different keys (for
	example an Excel row that adds an extra column). Appending with the keys of
	the current row silently shifts every column, so the header is rebuilt from
	the union of all rows instead and written atomically.
	"""
	existing_rows = []
	if os.path.isfile(done_csv_path):
		with open(done_csv_path, encoding='UTF-8-SIG', newline='') as existing_file:
			reader = csv.DictReader(existing_file)
			fieldnames = list(reader.fieldnames or fieldnames)
			existing_rows = [
				row for row in reader if any((value or '').strip() for value in row.values())
			]

	for row in rows:
		for key in row:
			if key not in fieldnames:
				fieldnames.append(key)

	directory = os.path.dirname(done_csv_path) or '.'
	os.makedirs(directory, exist_ok=True)
	with tempfile.NamedTemporaryFile(
		mode='w',
		newline='',
		encoding='UTF-8-SIG',
		dir=directory,
		delete=False
	) as temporary_file:
		writer = csv.DictWriter(
			temporary_file,
			fieldnames=fieldnames,
			extrasaction='ignore',
			restval=''
		)
		writer.writeheader()
		writer.writerows(existing_rows)
		writer.writerows(rows)
		temporary_path = temporary_file.name
	os.replace(temporary_path, done_csv_path)


def record_uploaded_listing(csv_file_name, listing_row, done_folder_name='uploaded_done'):
	photos_folder = listing_row.get('Photos Folder', '')
	photos_names = listing_row.get('Photos Names', '')
	if photos_folder:
		move_listing_photos_to_done(photos_folder, photos_names, done_folder_name)

	done_csv_path = os.path.join('csvs', csv_file_name + '_done.csv')
	fieldnames = list(listing_row.keys())

	try:
		_write_done_csv(done_csv_path, [listing_row], fieldnames)
	except Exception as err:
		print('Gagal mencatat listing ke CSV done: ' + str(err))


def get_data_from_csv(csv_file_name):
	data = []

	file_path = 'csvs' + os.path.sep + csv_file_name + '.csv'

	try:
		with open(file_path, encoding='UTF-8-SIG', newline='') as csv_file:
			csv_dictionary = csv.DictReader(csv_file, delimiter=',')

			for dictionary_row in csv_dictionary:
				if 'Title' in dictionary_row:
					dictionary_row['Title'] = normalize_marketplace_title(
						dictionary_row['Title']
					)
				data.append(dictionary_row)
	except FileNotFoundError:
		print('File was not found in csvs' + os.path.sep + csv_file_name + '.csv')
		sys.exit(1)
	except (OSError, csv.Error, UnicodeDecodeError) as error:
		print('File CSV tidak dapat dibaca: ' + file_path + ' (' + str(error) + ')')
		sys.exit(1)

	return data
