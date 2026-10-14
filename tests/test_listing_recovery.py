import csv
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

from helpers.listing_helper import (
	_dismiss_facebook_error_dialog,
	_combobox_xpath,
	_condition_option_xpath,
	_option_xpath,
	find_listing_by_title,
	update_listings
)


def _listing(title):
	return {
		'Title': title,
		'Photos Folder': '',
		'Photos Names': '',
		'Price': '1000',
		'Category': '',
		'Condition': '',
		'Brand': '',
		'Description': '',
		'Location': '',
		'Groups': ''
	}


class ListingRecoveryTests(unittest.TestCase):
	def setUp(self):
		# update_listings rewrites csvs/<name>.csv relative to the working
		# directory, so run in a temporary directory to keep the real CSVs intact.
		self.workspace = tempfile.TemporaryDirectory()
		self.previous_directory = os.getcwd()
		os.chdir(self.workspace.name)
		os.makedirs('csvs', exist_ok=True)
		self.addCleanup(self.workspace.cleanup)
		self.addCleanup(os.chdir, self.previous_directory)
	def test_condition_option_xpath_does_not_require_listbox_aria_label(self):
		xpath = _condition_option_xpath('New')

		self.assertIn('//div[@role="option"]', xpath)
		self.assertIn("normalize-space(.)='New'", xpath)
		self.assertIn("normalize-space(.)='Baru'", xpath)
		self.assertNotIn('@aria-label', xpath)

	def test_combobox_xpath_targets_role_and_supports_both_languages(self):
		xpath = _combobox_xpath('Category', 'Kategori')

		self.assertIn('//label[@role="combobox"]', xpath)
		self.assertIn("normalize-space(.)='Category'", xpath)
		self.assertIn("normalize-space(.)='Kategori'", xpath)

	def test_category_option_xpath_supports_english_and_indonesian(self):
		xpath = _option_xpath('Clothing & accessories')

		self.assertIn("normalize-space(.)='Clothing & accessories'", xpath)
		self.assertIn("normalize-space(.)='Pakaian & aksesori'", xpath)

	@patch('helpers.listing_helper.time.sleep')
	def test_listing_lookup_matches_titles_case_insensitively(self, sleep):
		scraper = Mock()
		scraper.find_element.return_value = object()
		listing = object()
		scraper.find_element_by_xpath.return_value = listing

		self.assertIs(find_listing_by_title('  Product   A  ', scraper), listing)

		xpath = scraper.find_element_by_xpath.call_args.args[0]
		self.assertIn(
			'translate(normalize-space(.), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")',
			xpath
		)
		self.assertIn("'product a'", xpath)
		scraper.element_send_keys.assert_called_once_with(
			'input[placeholder="Search your listings"], '
			'input[placeholder="Cari daftar Anda"], '
			'input[placeholder="Cari tawaran Anda"], '
			'input[placeholder="Telusuri tawaran Anda"], '
			'input[aria-label="Cari tawaran Anda"]',
			'product a'
		)
		sleep.assert_called_once_with(5)

	@patch('helpers.listing_helper.record_uploaded_listing')
	@patch('helpers.listing_helper.find_listing_by_title', return_value=object())
	def test_custom_csv_name_updates_only_that_csv(
		self,
		find_listing,
		record_uploaded
	):
		listing = _listing('Excel product')

		update_listings(
			[listing],
			'item',
			Mock(),
			csv_file_name='imported_items'
		)

		record_uploaded.assert_called_once_with('imported_items', listing)
		find_listing.assert_called_once()
		# Only imported_items.csv is written; items.csv must not appear at all.
		self.assertEqual(os.listdir('csvs'), ['imported_items.csv'])

	@patch('helpers.listing_helper.find_listing_by_title')
	@patch('helpers.listing_helper.record_uploaded_listing')
	@patch('helpers.listing_helper._publish_with_recovery', return_value=True)
	def test_skip_existing_check_skips_pre_upload_product_search(
		self,
		publish,
		record_uploaded,
		find_listing
	):
		update_listings(
			[_listing('Excel product')],
			'item',
			Mock(),
			csv_file_name='imported_items',
			skip_existing_check=True
		)

		publish.assert_called_once()
		find_listing.assert_not_called()
		record_uploaded.assert_called_once_with('imported_items', _listing('Excel product'))

	@patch('helpers.listing_helper.record_uploaded_listing')
	@patch('helpers.listing_helper.find_listing_by_title', return_value=None)
	@patch('helpers.listing_helper._publish_with_recovery', return_value=True)
	def test_main_csv_keeps_its_header_when_every_listing_is_published(
		self,
		publish,
		find_listing,
		record_uploaded
	):
		update_listings([_listing('Product A'), _listing('Product B')], 'item', Mock())

		self.assertEqual(publish.call_count, 2)
		with open(
			os.path.join('csvs', 'items.csv'),
			encoding='utf-8-sig',
			newline=''
		) as csv_file:
			rows = list(csv.DictReader(csv_file))

		# A fully drained CSV keeps a usable header instead of becoming 0 bytes.
		self.assertEqual(rows, [])

	@patch('helpers.listing_helper.record_uploaded_listing')
	@patch('helpers.listing_helper.find_listing_by_title', return_value=None)
	@patch('helpers.listing_helper._publish_with_recovery', side_effect=[True, False])
	def test_unpublished_rows_are_written_back_with_the_full_header(
		self,
		publish,
		find_listing,
		record_uploaded
	):
		failed = _listing('Product B')
		failed['Extra Note'] = 'kept'

		update_listings([_listing('Product A'), failed], 'item', Mock())

		with open(
			os.path.join('csvs', 'items.csv'),
			encoding='utf-8-sig',
			newline=''
		) as csv_file:
			rows = list(csv.DictReader(csv_file))

		self.assertEqual([row['Title'] for row in rows], ['Product B'])
		# Extra keys present on one row must not raise or drop other columns.
		self.assertEqual(rows[0]['Extra Note'], 'kept')

	@patch('helpers.listing_helper.record_uploaded_listing')
	@patch('helpers.listing_helper.find_listing_by_title')
	def test_missing_required_column_skips_the_row_instead_of_raising(
		self,
		find_listing,
		record_uploaded
	):
		# A vehicle row without the Year/Make/Model columns used to raise a raw
		# KeyError that aborted the whole batch.
		broken = {'Title': 'Broken vehicle', 'Price': '1000'}

		update_listings([broken], 'vehicle', Mock())

		find_listing.assert_not_called()
		record_uploaded.assert_not_called()
		with open(
			os.path.join('csvs', 'vehicles.csv'),
			encoding='utf-8-sig',
			newline=''
		) as csv_file:
			rows = list(csv.DictReader(csv_file))
		self.assertEqual([row['Title'] for row in rows], ['Broken vehicle'])

	def test_detects_and_closes_facebook_temporary_error_dialog(self):
		scraper = Mock()
		scraper.find_element_by_xpath.side_effect = [object(), object()]

		self.assertTrue(_dismiss_facebook_error_dialog(scraper))

		self.assertEqual(scraper.find_element_by_xpath.call_count, 2)
		scraper.element_click_by_xpath.assert_called_once()

	def test_returns_false_if_facebook_error_dialog_is_not_present(self):
		scraper = Mock()
		scraper.find_element_by_xpath.return_value = False

		self.assertFalse(_dismiss_facebook_error_dialog(scraper))

		scraper.element_click_by_xpath.assert_not_called()

	def test_error_dialog_xpath_uses_quoted_literals(self):
		from helpers.listing_helper import FACEBOOK_ERROR_DIALOG_XPATH

		self.assertIn("contains(., 'Terjadi kesalahan')", FACEBOOK_ERROR_DIALOG_XPATH)
		self.assertIn("contains(., 'Maaf')", FACEBOOK_ERROR_DIALOG_XPATH)
		self.assertNotIn('contains(., "', FACEBOOK_ERROR_DIALOG_XPATH)

	def test_titles_with_double_quotes_stay_valid_xpath(self):
		"""normalize_marketplace_title turns curly quotes into plain ones, so
		titles frequently contain a double quote. Every lookup must survive that."""
		from helpers.listing_helper import (
			_contains_xpath,
			_text_xpath,
			_xpath_literal
		)

		# A value containing only double quotes is wrapped in single quotes.
		dquote_title = 'Karpet "Besar" 120x180'
		self.assertEqual(
			_text_xpath(dquote_title),
			"normalize-space(.)='Karpet \"Besar\" 120x180'"
		)
		self.assertEqual(
			_contains_xpath('@aria-label', dquote_title),
			"contains(@aria-label, 'Karpet \"Besar\" 120x180')"
		)

		# A value containing both quote kinds must use concat() so neither
		# character terminates its enclosing literal.
		mixed_title = 'Kaos "Polos" ' + chr(39) + 'Premium' + chr(39)
		for expression in (_text_xpath(mixed_title), _contains_xpath('.', mixed_title)):
			self.assertIn('concat(', expression)
			# The literal never opens with a bare double quote.
			self.assertNotIn('@"', expression)
			self.assertNotIn('="', expression)

		# Titles without quotes stay simple, readable literals.
		self.assertEqual(_text_xpath('Plain title'), "normalize-space(.)='Plain title'")

	def test_find_listing_by_title_never_opens_a_double_quoted_literal(self):
		scraper = Mock()
		scraper.find_element.return_value = object()
		scraper.find_element_by_xpath.return_value = None

		with patch('helpers.listing_helper.time.sleep'):
			find_listing_by_title('Kaos "Polos" ' + chr(39) + 'Premium' + chr(39), scraper)

		used_xpaths = [
			call.args[0] for call in scraper.find_element_by_xpath.call_args_list
		]
		self.assertEqual(len(used_xpaths), 2)
		for xpath in used_xpaths:
			# A raw double quote inside a double-quoted literal breaks the query.
			self.assertNotIn('@"', xpath)
			self.assertNotIn('="', xpath)
			self.assertIn('concat(', xpath)

	@patch('helpers.listing_helper.time.sleep')
	def test_missing_search_field_still_publishes_by_default(self, sleep):
		"""A search box that never appears must not silently skip every product."""
		scraper = Mock()
		scraper.find_element.return_value = None

		with patch('builtins.print') as printer:
			result = find_listing_by_title('Product A', scraper)

		self.assertIsNone(result)
		# It warns, and it does not raise.
		messages = ' '.join(str(call.args[0]) for call in printer.call_args_list)
		self.assertIn('PERINGATAN', messages)
		self.assertNotIn('Traceback', messages)

	@patch('helpers.listing_helper.time.sleep')
	def test_missing_search_field_raises_when_the_result_is_required(self, sleep):
		"""Duplicate verification must fail loudly rather than guess."""
		scraper = Mock()
		scraper.find_element.return_value = None

		with self.assertRaises(RuntimeError):
			find_listing_by_title('Product A', scraper, required=True)

	@patch('helpers.listing_helper.record_uploaded_listing')
	@patch('helpers.listing_helper.find_listing_by_title', return_value=None)
	@patch('helpers.listing_helper._publish_with_recovery', return_value=True)
	def test_skip_existing_check_publishes_without_searching(
		self,
		publish,
		find_listing,
		record_uploaded
	):
		update_listings(
			[_listing('Product A'), _listing('Product B')],
			'item',
			Mock(),
			skip_existing_check=True
		)

		# No search is performed, so the batch is fast and nothing is skipped.
		find_listing.assert_not_called()
		self.assertEqual(publish.call_count, 2)
		self.assertEqual(record_uploaded.call_count, 2)

	@patch('helpers.listing_helper.publish_listing')
	@patch('helpers.listing_helper.find_listing_by_title')
	def test_continues_to_next_listing_after_a_publish_error(self, find_listing, publish):
		scraper = Mock()
		find_listing.side_effect = [None, False, False, None]
		publish.side_effect = [
			RuntimeError('Publish button did not enable'),
			RuntimeError('Publish button did not enable'),
			True
		]

		update_listings([_listing('Product A'), _listing('Product B')], 'item', scraper)

		self.assertEqual(publish.call_count, 3)
		self.assertEqual(find_listing.call_count, 4)
		self.assertEqual(scraper.go_to_page.call_count, 2)

	@patch('helpers.listing_helper.publish_listing')
	@patch('helpers.listing_helper.find_listing_by_title')
	def test_does_not_retry_when_listing_status_cannot_be_verified(self, find_listing, publish):
		scraper = Mock()
		find_listing.side_effect = [None, RuntimeError('search unavailable'), None]
		publish.side_effect = [RuntimeError('Publish result unknown'), True]

		update_listings([_listing('Product A'), _listing('Product B')], 'item', scraper)

		self.assertEqual(publish.call_count, 2)
		self.assertEqual(find_listing.call_count, 3)
		self.assertEqual(scraper.go_to_page.call_count, 1)


if __name__ == '__main__':
	unittest.main()
