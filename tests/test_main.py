import unittest
from unittest.mock import Mock, patch

import main


class MainTests(unittest.TestCase):
	def test_login_only_saves_session_without_processing_listings(self):
		scraper = Mock()

		with (
			patch.object(main, 'Scraper', return_value=scraper),
			patch.object(main, 'get_data_from_csv') as get_data_from_csv,
			patch.object(main, 'update_listings') as update_listings,
			patch('builtins.print')
		):
			main.run(login_only=True)

		scraper.add_login_functionality.assert_called_once()
		scraper.close.assert_called_once_with()
		scraper.go_to_page.assert_not_called()
		get_data_from_csv.assert_not_called()
		update_listings.assert_not_called()


if __name__ == '__main__':
	unittest.main()
