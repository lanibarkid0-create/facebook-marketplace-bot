import unittest
import os
import pickle
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from selenium.common.exceptions import (
	InvalidSelectorException,
	SessionNotCreatedException,
	StaleElementReferenceException,
	TimeoutException,
	WebDriverException,
)
from selenium.webdriver.common.by import By

from helpers.scraper import Scraper, ScraperError


class ElementSendKeysTests(unittest.TestCase):
	def test_refinds_element_once_when_click_reference_is_stale(self):
		stale_element = Mock()
		stale_element.click.side_effect = StaleElementReferenceException()
		current_element = Mock()
		scraper = object.__new__(Scraper)

		with (
			patch.object(scraper, 'wait_random_time'),
			patch.object(
				scraper,
				'find_element',
				side_effect=[stale_element, current_element]
			) as find_element
		):
			scraper.element_send_keys('input[name="title"]', 'Product', delay=False)

		self.assertEqual(find_element.call_count, 2)
		current_element.click.assert_called_once_with()
		current_element.send_keys.assert_called_once_with('Product')

	def test_raises_if_refound_element_is_stale_too(self):
		first_element = Mock()
		second_element = Mock()
		first_element.click.side_effect = StaleElementReferenceException()
		second_element.click.side_effect = StaleElementReferenceException()
		scraper = object.__new__(Scraper)

		with (
			patch.object(scraper, 'wait_random_time'),
			patch.object(scraper, 'find_element', side_effect=[first_element, second_element])
		):
			with self.assertRaises(StaleElementReferenceException):
				scraper.element_send_keys('input[name="title"]', 'Product', delay=False)

		second_element.send_keys.assert_not_called()


class FacebookCookieTests(unittest.TestCase):
	def test_login_detection_accepts_facebook_auth_cookies(self):
		scraper = object.__new__(Scraper)
		scraper.driver = Mock()
		scraper.driver.get_cookies.return_value = [
			{'name': 'c_user', 'value': 'user-id'},
			{'name': 'xs', 'value': 'session-token'}
		]
		scraper.is_logged_in_selector = 'profile'

		self.assertTrue(scraper.is_logged_in(wait_element_time=1))
		scraper.driver.find_elements.assert_not_called()

	def test_login_detection_checks_profile_selector_when_cookies_are_missing(self):
		scraper = object.__new__(Scraper)
		scraper.driver = Mock()
		scraper.driver.get_cookies.return_value = []
		profile = Mock()
		profile.is_displayed.return_value = True
		scraper.driver.find_elements.return_value = [profile]
		scraper.is_logged_in_selector = 'profile'

		self.assertTrue(scraper.is_logged_in(wait_element_time=1))
		scraper.driver.find_elements.assert_called_once_with(
			By.CSS_SELECTOR,
			'profile'
		)

	def test_empty_cookie_file_falls_back_to_manual_login(self):
		scraper = object.__new__(Scraper)
		scraper.driver = Mock()
		scraper.is_logged_in = Mock(return_value=False)

		with tempfile.TemporaryDirectory() as temporary_directory:
			scraper.cookies_folder = temporary_directory + os.path.sep
			Path(scraper.cookies_folder, 'facebook.pkl').touch()
			with patch('builtins.print'):
				with self.assertRaises(ScraperError):
					scraper.add_login_functionality(
						'https://www.facebook.com',
						'profile',
						'facebook'
					)

		scraper.is_logged_in.assert_called_once_with(300)

	def test_loads_valid_cookie_list(self):
		scraper = object.__new__(Scraper)
		scraper.url = 'https://www.facebook.com'
		scraper.driver = Mock()
		scraper.go_to_page = Mock()
		cookies = [{'name': 'session', 'value': 'cookie-value'}]

		with tempfile.TemporaryDirectory() as temporary_directory:
			scraper.cookies_file_path = str(Path(temporary_directory, 'facebook.pkl'))
			with open(scraper.cookies_file_path, 'wb') as cookie_file:
				pickle.dump(cookies, cookie_file)

			self.assertTrue(scraper.load_cookies())

		scraper.driver.add_cookie.assert_called_once_with(cookies[0])
		scraper.go_to_page.assert_called_once_with(scraper.url)

	def test_chrome_does_not_wait_for_full_page_load(self):
		scraper = object.__new__(Scraper)

		scraper.setup_driver_options()

		self.assertEqual(scraper.driver_options.page_load_strategy, 'none')

	def test_initial_page_load_timeout_is_reported_and_driver_closed(self):
		scraper = object.__new__(Scraper)
		scraper.url = 'https://www.facebook.com'
		scraper.setup_driver_options()
		driver = Mock()
		driver.get.side_effect = TimeoutException()

		with tempfile.TemporaryDirectory() as temporary_directory:
			with (
				patch('helpers.scraper.Path.home', return_value=Path(temporary_directory)),
				patch('helpers.scraper.ChromeDriverManager') as driver_manager,
				patch('helpers.scraper.webdriver.Chrome', return_value=driver)
			):
				driver_manager.return_value.install.return_value = 'chromedriver.exe'
				with self.assertRaisesRegex(ScraperError, 'Periksa koneksi internet'):
					scraper.setup_driver()

		driver.set_page_load_timeout.assert_called_once_with(Scraper.page_load_timeout)
		driver.quit.assert_called_once_with()

	def test_incompatible_cached_driver_falls_back_to_a_fresh_download(self):
		scraper = object.__new__(Scraper)
		scraper.url = 'https://www.facebook.com'
		scraper.setup_driver_options()
		fresh = Mock()
		fresh.current_url = scraper.url

		def start_chrome(service=None, options=None):
			# The cached driver fails to create a session because its version no
			# longer matches the installed Chrome; the fresh one succeeds.
			if '114.0.0.0' in str(getattr(service, 'path', '')):
				raise SessionNotCreatedException('version mismatch')
			return fresh

		with tempfile.TemporaryDirectory() as temporary_directory:
			cached_directory = (
				Path(temporary_directory) / '.wdm' / 'drivers' / 'chromedriver'
				/ '114.0.0.0'
			)
			cached_directory.mkdir(parents=True)
			(cached_directory / 'chromedriver.exe').write_bytes(b'driver')

			with (
				patch('helpers.scraper.Path.home', return_value=Path(temporary_directory)),
				patch(
					'helpers.scraper.ChromeDriverManager',
					return_value=Mock(install=Mock(return_value='fresh-chromedriver.exe'))
				),
				patch('helpers.scraper.webdriver.Chrome', side_effect=start_chrome) as chrome
			):
				scraper.setup_driver()

		# The cached driver is abandoned and a freshly downloaded one is used.
		self.assertEqual(chrome.call_count, 2)
		self.assertIs(scraper.driver, fresh)
		fresh.maximize_window.assert_called_once_with()

	def test_browser_start_failure_is_reported_as_scraper_error(self):
		scraper = object.__new__(Scraper)
		scraper.url = 'https://www.facebook.com'
		scraper.setup_driver_options()

		with tempfile.TemporaryDirectory() as temporary_directory:
			with (
				patch('helpers.scraper.Path.home', return_value=Path(temporary_directory)),
				patch('helpers.scraper.ChromeDriverManager') as driver_manager,
				patch(
					'helpers.scraper.webdriver.Chrome',
					side_effect=WebDriverException('chrome not reachable')
				)
			):
				driver_manager.return_value.install.return_value = 'chromedriver.exe'
				with self.assertRaisesRegex(ScraperError, 'Google Chrome'):
					scraper.setup_driver()


class MissingElementTests(unittest.TestCase):
	"""Optional lookups return None, so every helper must tolerate that."""

	def _scraper(self):
		scraper = object.__new__(Scraper)
		scraper.driver = Mock()
		scraper.wait_random_time = Mock()
		return scraper

	def test_element_click_reports_missing_element_instead_of_crashing(self):
		scraper = self._scraper()
		scraper.find_element = Mock(return_value=None)

		self.assertFalse(scraper.element_click('missing', delay=False))

	def test_element_click_by_xpath_reports_missing_element_instead_of_crashing(self):
		scraper = self._scraper()
		scraper.find_element_by_xpath = Mock(return_value=None)

		self.assertFalse(scraper.element_click_by_xpath('//missing', delay=False))

	def test_element_send_keys_reports_missing_element_instead_of_crashing(self):
		scraper = self._scraper()
		scraper.find_element = Mock(return_value=None)

		self.assertFalse(scraper.element_send_keys('missing', 'text', delay=False))

	def test_element_send_keys_by_xpath_reports_missing_element_instead_of_crashing(self):
		scraper = self._scraper()
		scraper.find_element_by_xpath = Mock(return_value=None)

		self.assertFalse(scraper.element_send_keys_by_xpath('//missing', 'text', delay=False))

	def test_element_clear_and_delete_text_report_missing_element(self):
		scraper = self._scraper()
		scraper.find_element = Mock(return_value=None)

		self.assertFalse(scraper.element_clear('missing', delay=False))
		self.assertFalse(scraper.element_delete_text('missing', delay=False))

	def test_scroll_helpers_report_missing_element(self):
		scraper = self._scraper()
		scraper.find_element = Mock(return_value=None)
		scraper.find_element_by_xpath = Mock(return_value=None)

		self.assertFalse(scraper.scroll_to_element('missing'))
		self.assertFalse(scraper.scroll_to_element_by_xpath('//missing'))

	def test_invisible_wait_reports_invalid_selector(self):
		scraper = self._scraper()
		scraper.driver = Mock()

		with patch(
			'helpers.scraper.WebDriverWait',
			side_effect=InvalidSelectorException('bad selector')
		):
			with patch('builtins.print') as printer:
				scraper.element_wait_to_be_invisible('[aria-label="Loading...]')

		self.assertIn('invalid CSS selector', printer.call_args.args[0])

	def test_close_survives_a_driver_that_is_already_gone(self):
		scraper = object.__new__(Scraper)
		scraper.driver = Mock()
		scraper.driver.quit.side_effect = WebDriverException('session deleted')

		with patch('builtins.print'):
			scraper.close()

		self.assertIsNone(scraper.driver)


if __name__ == '__main__':
	unittest.main()
