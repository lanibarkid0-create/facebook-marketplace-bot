import csv
import os
import shutil
import time

from helpers.csv_helper import normalize_marketplace_title, record_uploaded_listing


def _xpath_literal(value):
	if "'" not in value:
		return "'" + value + "'"
	if '"' not in value:
		return '"' + value + '"'

	return "concat(" + ', "\'", '.join("'" + part + "'" for part in value.split("'")) + ")"


def _contains_xpath(expression, value):
	"""Build a contains() predicate that is safe for any quote character.

	Building XPath by string concatenation breaks as soon as the value contains
	a double quote, and normalize_marketplace_title deliberately turns typographic
	quotes into plain ones, so titles frequently do.
	"""
	return 'contains(' + expression + ', ' + _xpath_literal(value) + ')'


def _text_xpath(value):
	return 'normalize-space(.)=' + _xpath_literal(value)



def _label_xpath(*labels):
	label_conditions = ' or '.join(_text_xpath(label) for label in labels)
	return '//span[' + label_conditions + ']'


def _combobox_xpath(*labels):
	label_conditions = ' or '.join(_text_xpath(label) for label in labels)
	return '//label[@role="combobox"][.//span[' + label_conditions + ']]'


def _option_xpath(option):
	localized_options = {
		'clothing & accessories': ('Clothing & accessories', 'Pakaian & aksesori'),
		'bags & luggage': ('Bags & luggage', 'Tas & koper'),
		"women's clothing & shoes": (
			"Women's clothing & shoes",
			'Pakaian & sepatu wanita'
		),
		"men's clothing & shoes": (
			"Men's clothing & shoes",
			'Pakaian & sepatu pria'
		),
		'jewellery and accessories': (
			'Jewellery and accessories',
			'Perhiasan dan aksesori'
		),
		'health & beauty': ('Health & beauty', 'Kesehatan & kecantikan'),
		'baby & children': ('Baby & children', 'Bayi & anak-anak'),
		'sport and outdoors': (
			'Sport and outdoors',
			'Olahraga dan aktivitas luar ruangan'
		),
		'vehicles': ('Vehicles', 'Kendaraan')
	}
	options = localized_options.get(option.casefold(), (option,))
	option_conditions = ' or '.join(_text_xpath(candidate) for candidate in options)
	return '//span[' + option_conditions + ']'


def _condition_option_xpath(option):
	labels = (option, 'Baru') if option.casefold() == 'new' else (option,)
	label_conditions = ' or '.join(_text_xpath(label) for label in labels)
	return (
		'//div[@role="option"][.//span[' + label_conditions + ']]'
	)


FACEBOOK_ERROR_DIALOG_XPATH = (
	'//div[@role="dialog"]'
	'[' + _contains_xpath('.', 'Terjadi kesalahan')
	+ ' or ' + _contains_xpath('.', 'Maaf') + ']'
)


def _dismiss_facebook_error_dialog(scraper):
	dialog = scraper.find_element_by_xpath(
		FACEBOOK_ERROR_DIALOG_XPATH,
		False,
		3
	)
	if not dialog:
		return False

	print(
		'Facebook menampilkan pesan error sementara setelah percobaan publikasi; '
		'memeriksa status listing sebelum mencoba ulang.'
	)
	close_button_xpath = (
		FACEBOOK_ERROR_DIALOG_XPATH
		+ '//div[@role="button"][.//span['
		+ _text_xpath('Tutup')
		+ ' or '
		+ _text_xpath('Close')
		+ ']]'
		+ ' | '
		+ FACEBOOK_ERROR_DIALOG_XPATH
		+ '//div[@role="button" and (@aria-label='
		+ _xpath_literal('Tutup')
		+ ' or @aria-label='
		+ _xpath_literal('Close')
		+ ')]'
	)
	close_button = scraper.find_element_by_xpath(close_button_xpath, False, 3)
	if close_button:
		scraper.element_click_by_xpath(close_button_xpath)
	return True


def _recover_and_check_listing(title, scraper):
	try:
		scraper.go_to_page('https://www.facebook.com/marketplace/you/selling')
	except Exception as error:
		print('ERROR: Could not return to Marketplace listings: ' + str(error))
		return None

	try:
		# required=True: an unknown search result must not trigger a retry,
		# because republishing blindly could create a duplicate listing.
		return bool(find_listing_by_title(title, scraper, required=True))
	except Exception as error:
		print('ERROR: Could not verify listing "' + title + '": ' + str(error))
		return None


def _publish_with_recovery(listing, listing_type, scraper, title):
	try:
		if publish_listing(listing, listing_type, scraper):
			print('Listing published: ' + title)
			return True
	except Exception as error:
		print('ERROR: First publish attempt failed for "' + title + '": ' + str(error))

	existing = _recover_and_check_listing(title, scraper)
	if existing is None:
		print('Skipping retry because the listing status could not be verified: ' + title)
		return False
	if existing:
		try:
			print('Listing is already present after the publish attempt: ' + title.encode('ascii', 'replace').decode('ascii'))
		except Exception:
			print('Listing is already present after the publish attempt: ' + repr(title))
		return True

	try:
		print('Retrying listing once after verifying it is not present: ' + title.encode('ascii', 'replace').decode('ascii'))
	except Exception:
		print('Retrying listing once after verifying it is not present: ' + repr(title))
	try:
		if publish_listing(listing, listing_type, scraper):
			try:
				print('Listing published after retry: ' + title.encode('ascii', 'replace').decode('ascii'))
			except Exception:
				print('Listing published after retry: ' + repr(title))
			return True
	except Exception as error:
		print('ERROR: Retry failed for "' + title + '": ' + str(error))

	existing = _recover_and_check_listing(title, scraper)
	if existing:
		try:
			print('Listing is present after retry: ' + title.encode('ascii', 'replace').decode('ascii'))
		except Exception:
			print('Listing is present after retry: ' + repr(title))
		return True
	elif existing is False:
		try:
			print('ERROR: Listing was not published after retry; continuing to the next product: ' + title.encode('ascii', 'replace').decode('ascii'))
		except Exception:
			print('ERROR: Listing was not published after retry; continuing to the next product: ' + repr(title))
	else:
		try:
			print('ERROR: Could not confirm the final status; continuing without another retry: ' + title.encode('ascii', 'replace').decode('ascii'))
		except Exception:
			print('ERROR: Could not confirm the final status; continuing without another retry: ' + repr(title))
	return False


# Publish listings that are not already present
def update_listings(
	listings,
	type,
	scraper,
	csv_file_name=None,
	skip_existing_check=False
):
	if not listings:
		print('No ' + type + ' listings to process.')
		return

	if csv_file_name is None:
		csv_file_name = 'items' if type == 'item' else 'vehicles'

	published_count = 0
	existing_count = 0
	failed_count = 0
	
	# Keep track of items to remove from the main list
	remaining_listings = []

	for listing in listings:
		try:
			title = generate_title_for_listing_type(listing, type)
		except KeyError as error:
			print(
				'ERROR: Kolom wajib ' + str(error) + ' tidak ada di ' + type
				+ ' CSV untuk baris "' + str(listing.get('Title', 'unknown'))
				+ '"; baris dilewati.'
			)
			failed_count += 1
			remaining_listings.append(listing)
			continue
		try:
			print('Publishing listing: ' + title.encode('ascii', 'replace').decode('ascii'))
		except Exception:
			print('Publishing listing: ' + repr(title))
		existing = False

		if not skip_existing_check:
			# Look for the title on the selling page first so re-running the
			# batch does not create duplicates. A failed lookup must not abort
			# the product: the search field may be missing, in which case the
			# result is unknown and publishing continues with a warning.
			try:
				existing = bool(find_listing_by_title(title, scraper))
			except Exception as error:
				print(
					'PERINGATAN: Gagal memeriksa listing yang sudah ada untuk "'
					+ title + '": ' + str(error)
					+ '. Melanjutkan ke publikasi.'
				)
				existing = False

		if existing:
			try:
				print('Skipping existing listing: ' + title.encode('ascii', 'replace').decode('ascii'))
			except Exception:
				print('Skipping existing listing: ' + repr(title))
			existing_count += 1
			# Record as done even if it was already there
			record_uploaded_listing(csv_file_name, listing)
			continue

		try:
			print('Creating listing: ' + title.encode('ascii', 'replace').decode('ascii'))
		except Exception:
			print('Creating listing: ' + repr(title))
		if _publish_with_recovery(listing, type, scraper, title):
			published_count += 1
			record_uploaded_listing(csv_file_name, listing)
		else:
			failed_count += 1
			remaining_listings.append(listing)

	# Update the CSV to only contain items that failed or were not processed
	file_path = 'csvs' + os.path.sep + csv_file_name + '.csv'

	# Rebuild the header from every processed row so the CSV stays readable even
	# when nothing is left, and so rows with extra keys do not crash DictWriter.
	fieldnames = []
	for listing in listings:
		for key in listing:
			if key not in fieldnames:
				fieldnames.append(key)

	try:
		os.makedirs(os.path.dirname(file_path) or '.', exist_ok=True)
		with open(file_path, mode='w', newline='', encoding='UTF-8-SIG') as f:
			writer = csv.DictWriter(
				f,
				fieldnames=fieldnames,
				extrasaction='ignore',
				restval=''
			)
			writer.writeheader()
			writer.writerows(remaining_listings)
	except Exception as err:
		print('Gagal memperbarui file CSV utama: ' + str(err))

	print(
		'Batch summary for '
		+ type
		+ ' listings: '
		+ str(published_count)
		+ ' published or confirmed, '
		+ str(existing_count)
		+ ' already present, '
		+ str(failed_count)
		+ ' failed/skipped after errors.'
	)

def remove_listing(data, listing_type, scraper) :
	title = generate_title_for_listing_type(data, listing_type)
	listing_title = find_listing_by_title(title, scraper)

	# Listing not found so stop the function
	if not listing_title:
		return

	listing_title.click()

	# Click on the delete listing button
	scraper.element_click('div:not([role="gridcell"]) > div[aria-label="Delete"][tabindex="0"]')
	
	# Click on confirm button to delete
	confirm_delete_selector = 'div[aria-label="Delete listing"] div[aria-label="Delete"][tabindex="0"]'
	if scraper.find_element(confirm_delete_selector, False, 3):
		scraper.element_click(confirm_delete_selector)
	else:
		confirm_delete_selector = 'div[aria-label="Delete Listing"] div[aria-label="Delete"][tabindex="0"]'
		if scraper.find_element(confirm_delete_selector, True, 3):
			scraper.element_click(confirm_delete_selector)
	
	# Wait until the popup is closed
	scraper.element_wait_to_be_invisible('div[aria-label="Your Listing"]')

def publish_listing(data, listing_type, scraper):
	# Choose listing type
	scraper.go_to_page('https://www.facebook.com/marketplace/create/' + listing_type)

	# Create string that contains all of the image paths separeted by \n
	images_path = generate_multiple_images_path(data['Photos Folder'], data['Photos Names'])
	# Add images to the the listing
	scraper.input_file_add_files('input[accept="image/*,image/heif,image/heic"]', images_path)

	# Add specific fields based on the listing_type
	function_name = 'add_fields_for_' + listing_type
	# Call function by name dynamically
	globals()[function_name](data, scraper)
	
	scraper.element_send_keys_by_xpath(
		_label_xpath('Price', 'Harga') + '/following-sibling::input[1]',
		data['Price']
	)
	description_xpath = _label_xpath(
		'Description', 'Deskripsi', 'Keterangan'
	) + '/following-sibling::div/textarea'
	if not scraper.find_element_by_xpath(description_xpath, False, 3):
		details_xpath = _label_xpath('More details', 'Detail selengkapnya')
		scraper.element_click_by_xpath(details_xpath)
		description_xpath = _label_xpath(
			'Description', 'Deskripsi', 'Keterangan'
		) + '/following-sibling::div/textarea'
	scraper.element_send_keys_by_xpath(description_xpath, data['Description'])
	location_selector = (
		'input[aria-label="Location"], '
		'input[aria-label="Lokasi"]'
	)
	location_input = scraper.find_element(location_selector)
	requested_location = data['Location'].strip()
	current_location = (location_input.get_attribute('value') or '').strip()
	if current_location.casefold() != requested_location.casefold():
		location_input.clear()
		scraper.element_send_keys(location_selector, requested_location)
		location_suggestion_selector = 'ul[role="listbox"] li:first-child > div'
		if not scraper.find_element(location_suggestion_selector, False, 10):
			raise RuntimeError(
				'Facebook did not suggest the requested location "'
				+ requested_location + '".'
			)
		scraper.element_click(location_suggestion_selector)

	next_button_selector = (
		'div[role="button"][aria-label="Next"], '
		'div[role="button"][aria-label="Berikutnya"]'
	)
	next_button = scraper.find_element(next_button_selector, False, 3)
	if next_button:
		# Go to the next step
		scraper.element_click(next_button_selector)
		# Add listing to multiple groups
		add_listing_to_multiple_groups(data, scraper)
	
	close_button_selector = (
		'//span[' + _text_xpath('Close') + ' or ' + _text_xpath('Tutup') + ']'
	)
	close_button = scraper.find_element_by_xpath(close_button_selector, False, 10)
	if close_button:
		scraper.element_click_by_xpath(close_button_selector)
		scraper.go_to_page('https://www.facebook.com/marketplace/you/selling')
		return False

	# Facebook may keep the publish button disabled while the audience step loads.
	publish_selector = (
		'div[aria-label="Publish"]:not([aria-disabled]), '
		'div[aria-label="Terbitkan"]:not([aria-disabled])'
	)
	if not scraper.find_element(publish_selector, False, 60):
		raise RuntimeError('Facebook did not enable the Publish button within 60 seconds.')
	scraper.element_click(publish_selector)
	
	# Wait for potential error dialog
	if _dismiss_facebook_error_dialog(scraper):
		return False

	leave_page_selector = (
		'//div[@tabindex="0"] '
		'//span[' + _text_xpath('Leave Page') + ' or '
		+ _text_xpath('Tinggalkan Halaman') + ']'
	)
	leave_page = scraper.find_element_by_xpath(leave_page_selector, False, 15)
	if leave_page:
		scraper.element_click_by_xpath(leave_page_selector)

	# Wait until the listing is published
	wait_until_listing_is_published(listing_type, scraper)
	scraper.go_to_page('https://www.facebook.com/marketplace/you/selling')
	title = generate_title_for_listing_type(data, listing_type)
	if not find_listing_by_title(title, scraper):
		print('ERROR: Listing is not visible in Marketplace after publishing: ' + title)
		return False

	if not next_button and any(
		group_name.strip()
		for group_name in data.get('Groups', '').split(';')
	):
		post_listing_to_multiple_groups(data, listing_type, scraper)
	
	return True


def generate_multiple_images_path(path, images):
	images_path = ''

	# Split image names into array by this symbol ";"
	image_names = images.split(';')

	# Create string that contains all of the image paths separeted by \n
	if image_names:
		for image_name in image_names:
			# Remove whitespace before and after the string
			image_name = image_name.strip()

			# Add "\n" for indicating new file
			if images_path != '':
				images_path += '\n'

			images_path += os.path.join(path, image_name)

	return images_path

# Add specific fields for listing from type vehicle
def add_fields_for_vehicle(data, scraper):
	# Expand vehicle type select
	scraper.element_click_by_xpath(_combobox_xpath('Vehicle type', 'Jenis kendaraan'))
	# Select vehicle type
	scraper.element_click_by_xpath(_option_xpath(data['Vehicle Type']))

	# Scroll to years select
	scraper.scroll_to_element_by_xpath(_combobox_xpath('Year', 'Tahun'))
	# Expand years select
	scraper.element_click_by_xpath(_combobox_xpath('Year', 'Tahun'))
	scraper.element_click_by_xpath(_option_xpath(data['Year']))

	scraper.element_send_keys_by_xpath(
		_label_xpath('Make', 'Merek') + '/following-sibling::input[1]',
		data['Make']
	)
	scraper.element_send_keys_by_xpath(
		_label_xpath('Model') + '/following-sibling::input[1]',
		data['Model']
	)

	# Scroll to mileage input
	mileage_xpath = _label_xpath('Mileage', 'Jarak tempuh') + '/following-sibling::input[1]'
	scraper.scroll_to_element_by_xpath(mileage_xpath)
	# Click on the mileage input
	scraper.element_send_keys_by_xpath(mileage_xpath, data['Mileage'])

	# Expand fuel type select
	scraper.element_click_by_xpath(_combobox_xpath('Fuel type', 'Jenis bahan bakar'))
	# Select fuel type
	scraper.element_click_by_xpath(_option_xpath(data['Fuel Type']))

# Add specific fields for listing from type item
def add_fields_for_item(data, scraper):
	scraper.element_send_keys_by_xpath(
		_label_xpath('Title', 'Judul') + '/following-sibling::input[1]',
		data['Title']
	)

	# Scroll to "Category" select field
	category_xpath = _combobox_xpath('Category', 'Kategori')
	scraper.scroll_to_element_by_xpath(category_xpath)
	# Expand category select
	scraper.element_click_by_xpath(category_xpath)
	# Select category
	scraper.element_click_by_xpath(_option_xpath(data['Category']))

	# Expand category select
	condition_xpath = _combobox_xpath('Condition', 'Kondisi')
	scraper.element_click_by_xpath(condition_xpath)
	scraper.element_click_by_xpath(_condition_option_xpath(data['Condition']))

	# Some categories (for example Sports & Outdoors) expose an extra Brand
	# input. Fill it only when the field is actually present on the form.
	brand = str(data.get('Brand') or '').strip()
	if brand:
		brand_xpath = _label_xpath('Brand', 'Merek') + '/following-sibling::input[1]'
		if scraper.find_element_by_xpath(brand_xpath, False, 3):
			scraper.element_send_keys_by_xpath(brand_xpath, brand)

def generate_title_for_listing_type(data, listing_type):
	title = ''

	if listing_type == 'item':
		title = data['Title']

	if listing_type == 'vehicle':
		title = data['Year'] + ' ' + data['Make'] + ' ' + data['Model']

	return normalize_marketplace_title(title)

def add_listing_to_multiple_groups(data, scraper):
	group_names = [name.strip() for name in data['Groups'].split(';') if name.strip()]

	if not group_names:
		return

	# Post in different groups
	for group_name in group_names:
		scraper.element_click_by_xpath(
			'//span[' + _text_xpath(group_name) + ']'
		)

def post_listing_to_multiple_groups(data, listing_type, scraper):
	title = generate_title_for_listing_type(data, listing_type)
	title_element = find_listing_by_title(title, scraper)

	# If there is no add with this title do not do nothing
	if not title_element:
		return

	group_names = [name.strip() for name in data['Groups'].split(';') if name.strip()]

	if not group_names:
		return

	search_input_selector = '[aria-label="Search for groups"]'

	# Post in different groups
	for group_name in group_names:
		# Click on the Share button to the listing that we want to share
		scraper.element_click_by_xpath(
			'//*[' + _contains_xpath('@aria-label', title) + ']'
			'//span//span[' + _text_xpath('Share') + ']'
		)

		# Click on the Share to a group button
		scraper.element_click_by_xpath('//span[' + _text_xpath('Group') + ']')

		# Remove current text from this input
		scraper.element_delete_text(search_input_selector)
		# Enter the title of the group in the input for search
		scraper.element_send_keys(search_input_selector, group_name[:51])

		scraper.element_click_by_xpath(
			'//span[' + _text_xpath(group_name) + ']'
		)

		if (scraper.find_element('[aria-label="Create a public post…"]', False, 3)):
			scraper.element_send_keys('[aria-label="Create a public post…"]', data['Description'])
		elif (scraper.find_element('[aria-label="Write something..."]', False, 3)):
			scraper.element_send_keys('[aria-label="Write something..."]', data['Description'])

		scraper.element_click('[aria-label="Post"]:not([aria-disabled])')
		# Wait till the post is posted successfully
		scraper.element_wait_to_be_invisible('[role="dialog"]')
		scraper.element_wait_to_be_invisible('[aria-label="Loading..."]')
		scraper.find_element_by_xpath('//span[' + _text_xpath('Shared to your group.') + ']', False, 10)

def find_listing_by_title(title, scraper, required=False):
	"""Look for an existing listing with this title on the selling page.

	Returns the matching element, or None when the title is not there. When the
	search field itself cannot be found the result is unknown: `required=False`
	returns None so the caller can still publish, while `required=True` raises so
	the caller can skip the product instead of risking a duplicate.
	"""
	normalized_title = ' '.join(title.split()).casefold()

	# Wait for the page to load content before searching
	time.sleep(5)

	search_selector = (
		'input[placeholder="Search your listings"], '
		'input[placeholder="Cari daftar Anda"], '
		'input[placeholder="Cari tawaran Anda"], '
		'input[placeholder="Telusuri tawaran Anda"], '
		'input[aria-label="Cari tawaran Anda"]'
	)

	# Try to find search input with multiple retries and refreshes
	searchInput = None
	for attempt in range(3):
		searchInput = scraper.find_element(search_selector, False, 20)
		if searchInput:
			break
		print(f'Pencarian belum muncul (percobaan {attempt + 1}/3), memuat ulang halaman...')
		scraper.driver.refresh()
		time.sleep(10)

	if not searchInput:
		message = (
			'Could not find the listing search field, so it is unknown whether '
			'this listing already exists.'
		)
		if required:
			raise RuntimeError(message)
		print('PERINGATAN: ' + message + ' Melanjutkan ke publikasi.')
		return None

	# Clear input field for searching listings before entering title
	scraper.element_delete_text(search_selector)
	# Enter the title of the listing in the input for search
	scraper.element_send_keys(search_selector, normalized_title)

	return scraper.find_element_by_xpath(
		'//span[translate(normalize-space(.), '
		+ '"ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")='
		+ _xpath_literal(normalized_title)
		+ ']',
		False,
		10
	) or scraper.find_element_by_xpath(
		'//div[' + _contains_xpath('@aria-label', normalized_title) + ']',
		False,
		10
	)


def wait_until_listing_is_published(listing_type, scraper):
	if listing_type == 'item':
		scraper.element_wait_to_be_invisible_by_xpath(
			'//h1[' + _text_xpath('Item for sale') + ']'
		)
	elif listing_type == 'vehicle':
		scraper.element_wait_to_be_invisible_by_xpath(
			'//h1[' + _text_xpath('Vehicle for sale') + ']'
		)
