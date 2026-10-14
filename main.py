import argparse
import os
import signal

from helpers.scraper import Scraper
from helpers.csv_helper import get_data_from_csv
from helpers.listing_helper import update_listings


def run(login_only=False, skip_existing_check=False):
	scraper = None
	try:
		scraper = Scraper('https://www.facebook.com')

		scraper.add_login_functionality(
			'https://www.facebook.com',
			'svg[aria-label="Your profile"], svg[aria-label="Profil Anda"]',
			'facebook'
		)
		if login_only:
			print('Login Facebook berhasil. Cookie akun sudah disimpan.')
			return

		scraper.go_to_page('https://www.facebook.com/marketplace/you/selling')

		skip_check = (
			skip_existing_check
			or os.environ.get('MARKETPLACE_SKIP_EXISTING_CHECK') == '1'
		)
		item_listings = get_data_from_csv('items')
		update_listings(
			item_listings,
			'item',
			scraper,
			'items',
			skip_existing_check=skip_check
		)

		vehicle_listings = get_data_from_csv('vehicles')
		update_listings(
			vehicle_listings,
			'vehicle',
			scraper,
			'vehicles',
			skip_existing_check=skip_check
		)
	finally:
		if scraper is not None:
			scraper.close()


def _handle_stop_signal(_signal_number, _frame):
	raise KeyboardInterrupt


if __name__ == '__main__':
	if hasattr(signal, 'SIGBREAK'):
		signal.signal(signal.SIGBREAK, _handle_stop_signal)

	parser = argparse.ArgumentParser()
	parser.add_argument(
		'--login-only',
		action='store_true',
		help='login ke Facebook dan simpan cookie tanpa memproses listing'
	)
	parser.add_argument(
		'--skip-existing-check',
		action='store_true',
		help=(
			'terbitkan langsung tanpa mencari dulu listing yang sudah ada. '
			'Lebih cepat, tetapi bisa membuat listing duplikat di akun Anda'
		)
	)
	arguments = parser.parse_args()

	try:
		run(
			login_only=arguments.login_only,
			skip_existing_check=arguments.skip_existing_check
		)
	except KeyboardInterrupt:
		print('Bot stopped by user.')
