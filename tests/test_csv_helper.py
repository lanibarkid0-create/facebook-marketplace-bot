import csv
import os
import tempfile
import unittest

from helpers.csv_helper import record_uploaded_listing


class DoneCsvTests(unittest.TestCase):
	"""csvs/<name>_done.csv accumulates rows across batches, so its header must
	stay stable even when individual rows carry different columns."""

	def setUp(self):
		self.workspace = tempfile.TemporaryDirectory()
		self.previous_directory = os.getcwd()
		os.chdir(self.workspace.name)
		os.makedirs('csvs', exist_ok=True)
		self.addCleanup(self.workspace.cleanup)
		self.addCleanup(os.chdir, self.previous_directory)

	def _read_done(self, name='demo'):
		with open(
			os.path.join('csvs', name + '_done.csv'),
			encoding='utf-8-sig',
			newline=''
		) as csv_file:
			return list(csv.DictReader(csv_file))

	def test_rows_with_different_columns_share_one_header(self):
		record_uploaded_listing('demo', {'Title': 'A', 'Price': '1000'})
		record_uploaded_listing(
			'demo',
			{'Title': 'B', 'Price': '2000', 'Extra Note': 'later batch'}
		)

		rows = self._read_done()

		self.assertEqual([row['Title'] for row in rows], ['A', 'B'])
		self.assertEqual([row['Price'] for row in rows], ['1000', '2000'])
		# The extra column must not shift the earlier values.
		self.assertEqual(rows[0]['Extra Note'], '')
		self.assertEqual(rows[1]['Extra Note'], 'later batch')

	def test_repeated_runs_do_not_lose_earlier_entries(self):
		for index in range(5):
			record_uploaded_listing('demo', {'Title': 'Product ' + str(index)})

		rows = self._read_done()

		self.assertEqual(
			[row['Title'] for row in rows],
			['Product 0', 'Product 1', 'Product 2', 'Product 3', 'Product 4']
		)

	def test_blank_rows_are_not_reintroduced(self):
		record_uploaded_listing('demo', {'Title': 'A', 'Price': '1'})
		record_uploaded_listing('demo', {'Title': 'B', 'Price': '2'})

		self.assertEqual(len(self._read_done()), 2)

	def test_photos_are_recorded_as_done(self):
		photos = os.path.join(self.workspace.name, 'photos')
		os.makedirs(photos, exist_ok=True)
		with open(os.path.join(photos, '01.jpg'), 'wb') as photo:
			photo.write(b'image')

		record_uploaded_listing(
			'demo',
			{'Title': 'A', 'Photos Folder': photos, 'Photos Names': '01.jpg'}
		)

		self.assertTrue(
			os.path.isfile(os.path.join(photos, 'uploaded_done', '01.jpg'))
		)
		self.assertEqual([row['Title'] for row in self._read_done()], ['A'])


if __name__ == '__main__':
	unittest.main()
