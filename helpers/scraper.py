import os
import pickle
import time
import random
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from webdriver_manager.chrome import ChromeDriverManager
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import InvalidArgumentException
from selenium.common.exceptions import ElementClickInterceptedException
from selenium.common.exceptions import InvalidSelectorException
from selenium.common.exceptions import SessionNotCreatedException
from selenium.common.exceptions import StaleElementReferenceException
from selenium.common.exceptions import TimeoutException
from selenium.common.exceptions import WebDriverException


class ScraperError(RuntimeError):
	pass

class Scraper:
	# This time is used when we are waiting for element to get loaded in the html
	wait_element_time = 60
	page_load_timeout = 60

	# In this folder we will save cookies from logged in users
	cookies_folder = 'cookies' + os.path.sep

	def __init__(self, url):
		self.url = url

		self.setup_driver_options()
		self.setup_driver()
	# Add these options in order to make chrome driver appear as a human instead of detecting it as a bot
	# Also change the 'cdc_' string in the chromedriver.exe with Notepad++ for example with 'abc_' to prevent detecting it as a bot
	def setup_driver_options(self):
		self.driver_options = Options()
		self.driver_options.page_load_strategy = 'none'

		arguments = [
			'--disable-blink-features=AutomationControlled',
			'--lang=id-ID'
		]

		experimental_options = {
			'excludeSwitches': ['enable-automation', 'enable-logging'],
			'prefs': {
				'profile.default_content_setting_values.notifications': 2,
				'intl.accept_languages': 'id-ID,id,en-US,en'
			}
		}

		for argument in arguments:
			self.driver_options.add_argument(argument)

		for key, value in experimental_options.items():
			self.driver_options.add_experimental_option(key, value)

	# Setup chrome driver with predefined options
	def setup_driver(self):
		cached_drivers = list(
			(Path.home() / '.wdm' / 'drivers' / 'chromedriver').glob(
				'**/chromedriver.exe'
			)
		)
		cached_driver = None
		if cached_drivers:
			cached_driver = max(
				cached_drivers,
				key=lambda path: tuple(
					int(part) if part.isdigit() else 0
					for part in path.parent.name.split('.')
				)
			)

		self.driver = None
		if cached_driver is not None:
			print('Using cached ChromeDriver: ' + str(cached_driver))
			try:
				self.driver = self._start_driver(Service(str(cached_driver)))
			except SessionNotCreatedException as error:
				# The cached driver no longer matches the installed Chrome
				# version, so fall back to downloading a compatible one.
				print(
					'Cached ChromeDriver is not compatible with the installed '
					'Chrome version; downloading a matching driver.'
				)
				print('Detail: ' + str(error))
				self.close()

		if self.driver is None:
			print('Downloading a compatible ChromeDriver.')
			try:
				chrome_driver = Service(ChromeDriverManager().install())
			except (WebDriverException, OSError, ValueError) as error:
				raise ScraperError(
					'ChromeDriver tidak dapat diunduh: '
					+ str(error)
					+ '. Periksa koneksi internet lalu jalankan ulang program.'
				) from error
			self.driver = self._start_driver(chrome_driver)

		self.driver.set_page_load_timeout(self.page_load_timeout)
		try:
			self.driver.get(self.url)
			self._wait_for_page_host(self.url)
		except TimeoutException as error:
			self.close()
			message = (
				f'Facebook tidak selesai dimuat dalam {self.page_load_timeout} detik. '
				'Periksa koneksi internet, lalu jalankan ulang program.'
			)
			raise ScraperError(message) from error
		self.driver.maximize_window()

	def _wait_for_page_host(self, page):
		expected_host = urlsplit(page).hostname
		WebDriverWait(self.driver, self.page_load_timeout).until(
			lambda driver: urlsplit(driver.current_url).hostname == expected_host
		)

	def _start_driver(self, service):
		"""Start Chrome and translate driver startup failures into ScraperError.

		SessionNotCreatedException is re-raised so setup_driver can fall back to
		a freshly downloaded driver when a cached one no longer matches Chrome.
		"""
		try:
			return webdriver.Chrome(service=service, options=self.driver_options)
		except SessionNotCreatedException:
			raise
		except WebDriverException as error:
			message = (
				'Browser Chrome tidak dapat dijalankan: '
				+ str(error)
				+ '. Pastikan Google Chrome sudah terpasang dan versinya didukung.'
			)
			print('ERROR: ' + message)
			raise ScraperError(message) from error

	# Automatically close driver on destruction of the object
	def __del__(self):
		try:
			self.close()
		except Exception:
			# Never let an interpreter shutdown failure mask the real error.
			pass

	def close(self):
		driver = getattr(self, 'driver', None)
		if driver is not None:
			self.driver = None
			try:
				driver.quit()
			except WebDriverException as error:
				print('Warning: Chrome tidak dapat ditutup dengan bersih: ' + str(error))

	# Add login functionality and load cookies if there are any with 'cookies_file_name'
	def add_login_functionality(self, login_url, is_logged_in_selector, cookies_file_name):
		self.login_url = login_url
		self.is_logged_in_selector = is_logged_in_selector
		self.cookies_file_name = cookies_file_name + '.pkl'
		self.cookies_file_path = self.cookies_folder + self.cookies_file_name

		# Check if there is a cookie file saved
		if self.is_cookie_file():
			if self.load_cookies():
				# Check if user is logged in after adding the cookies
				is_logged_in = self.is_logged_in(5)
				if is_logged_in:
					return
		
		# Wait for the user to log in with maximum amount of time 5 minutes
		print('Please login manually in the browser and after that you will be automatically logged in with cookies. Note that if you do not log in for five minutes, the program will turn off.')
		is_logged_in = self.is_logged_in(300)

		# User is not logged in so exit from the program
		if not is_logged_in:
			raise ScraperError('Login Facebook tidak selesai dalam 5 menit.')

		# User is logged in so save the cookies
		self.save_cookies()

	# Check if cookie file exists
	def is_cookie_file(self):
		return os.path.exists(self.cookies_file_path)

	# Load cookies from file
	def load_cookies(self):
		try:
			with open(self.cookies_file_path, 'rb') as cookies_file:
				cookies = pickle.load(cookies_file)
		except (EOFError, pickle.UnpicklingError):
			print(
				'Warning: file cookie Facebook kosong atau rusak. '
				'Silakan login manual untuk membuat cookie baru.'
			)
			return False

		if not isinstance(cookies, list) or not all(
			isinstance(cookie, dict) for cookie in cookies
		):
			print(
				'Warning: format file cookie Facebook tidak valid. '
				'Silakan login manual untuk membuat cookie baru.'
			)
			return False

		for cookie in cookies:
			self.driver.add_cookie(cookie)

		self.go_to_page(self.url)
		return True

	# Save cookies to file
	def save_cookies(self):
		# Do not save cookies if there is no cookies_file name 
		if not hasattr(self, 'cookies_file_path'):
			return

		# Create folder for cookies if there is no folder in the project
		os.makedirs(self.cookies_folder, exist_ok=True)
		# Get current cookies from the driver
		cookies = self.driver.get_cookies()

		# Replace the cookie file only after the new data has been written.
		cookie_directory = os.path.dirname(self.cookies_file_path) or '.'
		with tempfile.NamedTemporaryFile(
			mode='wb',
			dir=cookie_directory,
			delete=False
		) as cookies_file:
			pickle.dump(cookies, cookies_file)
			temporary_path = cookies_file.name
		os.replace(temporary_path, self.cookies_file_path)

	# Check if user is logged in based on a html element that is visible only for logged in users
	def is_logged_in(self, wait_element_time = None):
		if wait_element_time is None:
			wait_element_time = self.wait_element_time

		def has_logged_in_session(driver):
			cookie_names = {
				cookie.get('name')
				for cookie in driver.get_cookies()
			}
			if {'c_user', 'xs'}.issubset(cookie_names):
				return True

			return any(
				element.is_displayed()
				for element in driver.find_elements(
					By.CSS_SELECTOR,
					self.is_logged_in_selector
				)
			)

		try:
			return WebDriverWait(self.driver, wait_element_time).until(
				has_logged_in_session
			)
		except TimeoutException:
			return False

	# Wait random amount of seconds before taking some action so the server won't be able to tell if you are a bot
	def wait_random_time(self):
		random_sleep_seconds = round(random.uniform(0.20, 1.20), 2)

		time.sleep(random_sleep_seconds)

	# Goes to a given page and waits random time before that to prevent detection as a bot
	def go_to_page(self, page):
		# Wait random time before refreshing the page to prevent the detection as a bot
		self.wait_random_time()

		# Refresh the site url with the loaded cookies so the user will be logged in
		try:
			self.driver.get(page)
			self._wait_for_page_host(page)
		except TimeoutException as error:
			message = (
				f'Halaman Facebook tidak selesai dimuat dalam '
				f'{self.page_load_timeout} detik: {page}'
			)
			raise ScraperError(message) from error

	def find_element(self, selector, exit_on_missing_element = True, wait_element_time = None):
		if wait_element_time is None:
			wait_element_time = self.wait_element_time

		# Initialize the condition to wait
		wait_until = EC.element_to_be_clickable((By.CSS_SELECTOR, selector))

		try:
			# Wait for element to load
			element = WebDriverWait(self.driver, wait_element_time).until(wait_until)
		except TimeoutException as error:
			if exit_on_missing_element:
				message = 'Timed out waiting for the element with CSS selector "' + selector + '".'
				print('ERROR: ' + message)
				raise ScraperError(message) from error
			else:
				return None

		return element

	def find_element_by_xpath(self, xpath, exit_on_missing_element = True, wait_element_time = None):
		if wait_element_time is None:
			wait_element_time = self.wait_element_time

		# Initialize the condition to wait
		wait_until = EC.element_to_be_clickable((By.XPATH, xpath))

		try:
			# Wait for element to load
			element = WebDriverWait(self.driver, wait_element_time).until(wait_until)
		except TimeoutException as error:
			if exit_on_missing_element:
				message = 'Timed out waiting for the element with XPath "' + xpath + '".'
				print('ERROR: ' + message)
				raise ScraperError(message) from error
			else:
				return None

		return element

	# Wait random time before clicking on the element
	def element_click(self, selector, delay = True, exit_on_missing_element = True):
		if delay:
			self.wait_random_time()

		element = self.find_element(selector, exit_on_missing_element)

		if element is None:
			return False

		try:
			element.click()
		except ElementClickInterceptedException:
			self.driver.execute_script("arguments[0].click();", element)

		return True

	# Wait random time before clicking on the element
	def element_click_by_xpath(self, xpath, delay = True, exit_on_missing_element = True):
		if delay:
			self.wait_random_time()

		element = self.find_element_by_xpath(xpath, exit_on_missing_element)

		if element is None:
			return False

		try:
			element.click()
		except ElementClickInterceptedException:
			self.driver.execute_script("arguments[0].click();", element)

		return True

	# Wait random time before sending the keys to the element
	def element_send_keys(self, selector, text, delay = True, exit_on_missing_element = True):
		if delay:
			self.wait_random_time()

		element = self.find_element(selector, exit_on_missing_element)

		if element is None:
			return False

		for attempt in range(2):
			try:
				element.click()
				break
			except StaleElementReferenceException:
				if attempt:
					raise
				element = self.find_element(selector, exit_on_missing_element)
				if element is None:
					return False
			except ElementClickInterceptedException:
				self.driver.execute_script("arguments[0].click();", element)
				break

		element.send_keys(text)

		return True

	# Wait random time before sending the keys to the element
	def element_send_keys_by_xpath(self, xpath, text, delay = True, exit_on_missing_element = True):
		if delay:
			self.wait_random_time()

		element = self.find_element_by_xpath(xpath, exit_on_missing_element)

		if element is None:
			return False

		try:
			element.click()
		except ElementClickInterceptedException:
			self.driver.execute_script("arguments[0].click();", element)

		element.send_keys(text)

		return True

	def input_file_add_files(self, selector, files):
		# Initialize the condition to wait
		wait_until = EC.presence_of_element_located((By.CSS_SELECTOR, selector))

		try:
			input_file = WebDriverWait(self.driver, max(self.wait_element_time, 60)).until(wait_until)
		except TimeoutException as error:
			message = 'Timed out waiting for the image input with selector "' + selector + '".'
			print('ERROR: ' + message)
			raise ScraperError(message) from error

		self.wait_random_time()

		try:
			input_file.send_keys(files)
		except InvalidArgumentException as error:
			message = 'Invalid image file paths:\n' + files
			print('ERROR: ' + message)
			raise ScraperError(message) from error

	# Wait random time before clearing the element
	def element_clear(self, selector, delay = True, exit_on_missing_element = True):
		if delay:
			self.wait_random_time()

		element = self.find_element(selector, exit_on_missing_element)

		if element is None:
			return False

		element.clear()

		return True

	def element_delete_text(self, selector, delay = True, exit_on_missing_element = True):
		if delay:
			self.wait_random_time()

		element = self.find_element(selector, exit_on_missing_element)

		if element is None:
			return False

		# Select all of the text in the input
		element.send_keys(Keys.LEFT_SHIFT + Keys.HOME)
		# Remove the selected text with backspace
		element.send_keys(Keys.BACK_SPACE)

		return True

	def element_wait_to_be_invisible(self, selector):
		wait_until = EC.invisibility_of_element_located((By.CSS_SELECTOR, selector))

		try:
			WebDriverWait(self.driver, self.wait_element_time).until(wait_until)
		except TimeoutException:
			print('Warning when waiting the element with selector "' + selector + '" to be invisible')
		except InvalidSelectorException as error:
			print('ERROR: invalid CSS selector "' + selector + '": ' + str(error))

	def element_wait_to_be_invisible_by_xpath(self, xpath):
		wait_until = EC.invisibility_of_element_located((By.XPATH, xpath))

		try:
			WebDriverWait(self.driver, self.wait_element_time).until(wait_until)
		except TimeoutException:
			print('Warning when waiting the element with xpath "' + xpath + '" to be invisible')
		except InvalidSelectorException as error:
			print('ERROR: invalid XPath "' + xpath + '": ' + str(error))

	def scroll_to_element(self, selector, exit_on_missing_element = True):
		element = self.find_element(selector, exit_on_missing_element)

		if element is None:
			return False

		self.driver.execute_script(
			'arguments[0].scrollIntoView({block: "center", inline: "nearest"});',
			element
		)

		return True

	def scroll_to_element_by_xpath(self, xpath, exit_on_missing_element = True):
		element = self.find_element_by_xpath(xpath, exit_on_missing_element)

		if element is None:
			return False

		self.driver.execute_script(
			'arguments[0].scrollIntoView({block: "center", inline: "nearest"});',
			element
		)

		return True
