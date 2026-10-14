import unittest
from email.message import Message
from io import BytesIO

from web_app import _read_skip_existing_check


class SkipExistingCheckBodyTests(unittest.TestCase):
	"""The panel's start button posts an optional JSON flag."""

	def _request(self, body):
		class UploadRequest:
			pass

		request = UploadRequest()
		request.headers = Message()
		request.headers['Content-Length'] = str(len(body))
		request.rfile = BytesIO(body)
		return request

	def test_reads_true_flag(self):
		self.assertTrue(
			_read_skip_existing_check(self._request(b'{"skip_existing_check": true}'))
		)

	def test_defaults_to_false_without_a_body(self):
		self.assertFalse(_read_skip_existing_check(self._request(b'')))

	def test_defaults_to_false_when_the_flag_is_absent(self):
		self.assertFalse(_read_skip_existing_check(self._request(b'{}')))

	def test_ignores_a_malformed_body(self):
		self.assertFalse(_read_skip_existing_check(self._request(b'not json')))

	def test_ignores_a_non_boolean_payload(self):
		self.assertFalse(
			_read_skip_existing_check(self._request(b'"skip_existing_check"'))
		)


if __name__ == '__main__':
	unittest.main()