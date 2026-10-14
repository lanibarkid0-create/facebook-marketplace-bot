import csv
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import webbrowser


ROOT = Path(__file__).resolve().parent
HOST = '127.0.0.1'
PORT = 8765
LOG_LIMIT = 500
MAX_BODY_SIZE = 15 * 1024 * 1024


class BotAlreadyRunningError(Exception):
	pass


class BotController:
	def __init__(self):
		self._lock = threading.Lock()
		self._process = None
		self._logs = deque(maxlen=LOG_LIMIT)
		self._external_pids = []
		self._external_check_time = 0.0

	def _find_external_bot_processes(self):
		if os.name == 'nt':
			command = (
				"$processes = Get-CimInstance Win32_Process | "
				"Where-Object { $_.Name -match '^python(w)?\\.exe$' "
				"-and $_.CommandLine -match "
				"'python(w)?\\.exe\"?\\s+(?:\".*[\\\\/])?main\\.py(?:\"|\\s|$)' }; "
				"$processes | Select-Object -ExpandProperty ProcessId"
			)
			result = subprocess.run(
				['powershell', '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', command],
				capture_output=True,
				text=True,
				timeout=5,
				check=True
			)
			return [
				int(line.strip())
				for line in result.stdout.splitlines()
				if line.strip().isdigit()
			]

		process_ids = []
		proc_root = Path('/proc')
		if not proc_root.exists():
			return process_ids

		for entry in proc_root.iterdir():
			if not entry.name.isdigit() or int(entry.name) == os.getpid():
				continue
			try:
				arguments = (entry / 'cmdline').read_bytes().split(b'\0')
			except FileNotFoundError:
				continue
			if any(re.search(rb'(^|[/\\])main\.py$', argument) for argument in arguments):
				process_ids.append(int(entry.name))
		return process_ids

	def _get_external_pids(self):
		now = time.monotonic()
		with self._lock:
			if now - self._external_check_time < 5:
				return list(self._external_pids)

		process_ids = self._find_external_bot_processes()
		with self._lock:
			if self._process is not None:
				process_ids = [
					process_id
					for process_id in process_ids
					if process_id != self._process.pid
				]
			self._external_pids = process_ids
			self._external_check_time = now
			return list(process_ids)

	def status(self):
		external_pids = self._get_external_pids()
		with self._lock:
			process = self._process
			running = process is not None and process.poll() is None
			return {
				'running': running,
				'pid': process.pid if running else None,
				'external_processes': external_pids,
				'exit_code': process.poll() if process is not None and not running else None,
				'logs': list(self._logs),
				'items_count': self._csv_row_count('items.csv'),
				'vehicles_count': self._csv_row_count('vehicles.csv'),
				'has_cookie': (ROOT / 'cookies' / 'facebook.pkl').is_file()
			}

	def _csv_row_count(self, filename):
		csv_path = ROOT / 'csvs' / filename
		if not csv_path.is_file():
			return 0
		with csv_path.open(encoding='utf-8-sig', newline='') as csv_file:
			return sum(1 for _ in csv.DictReader(csv_file))

	def start(self, skip_existing_check=False):
		external_pids = self._find_external_bot_processes()
		with self._lock:
			process = self._process
			if process is not None and process.poll() is None:
				raise BotAlreadyRunningError('Bot yang dikelola panel ini sedang berjalan.')
			if external_pids:
				self._external_pids = external_pids
				self._external_check_time = time.monotonic()
				raise BotAlreadyRunningError(
					'Bot sudah berjalan di luar panel (PID: '
					+ ', '.join(str(pid) for pid in external_pids)
					+ '). Tunggu sampai proses tersebut selesai.'
				)
			self._logs.clear()
			environment = os.environ.copy()
			environment['PYTHONUNBUFFERED'] = '1'
			environment.pop('MARKETPLACE_SKIP_EXISTING_CHECK', None)
			if skip_existing_check:
				environment['MARKETPLACE_SKIP_EXISTING_CHECK'] = '1'
			options = {
				'cwd': str(ROOT),
				'stdout': subprocess.PIPE,
				'stderr': subprocess.STDOUT,
				'text': True,
				'encoding': 'utf-8',
				'errors': 'replace',
				'bufsize': 1,
				'env': environment
			}
			if os.name == 'nt':
				options['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
			else:
				options['start_new_session'] = True
			self._process = subprocess.Popen(
				[sys.executable, str(ROOT / 'main.py')],
				**options
			)
			self._external_pids = []
			self._external_check_time = time.monotonic()
			threading.Thread(
				target=self._collect_logs,
				args=(self._process,),
				daemon=True
			).start()
			return self._process.pid

	def _collect_logs(self, process):
		if process.stdout is None:
			return
		for line in process.stdout:
			with self._lock:
				self._logs.append(line.rstrip())
		process.stdout.close()

	def stop(self):
		with self._lock:
			process = self._process
			if process is None or process.poll() is not None:
				return False

		if os.name == 'nt':
			os.kill(process.pid, signal.CTRL_BREAK_EVENT)
		else:
			os.killpg(process.pid, signal.SIGINT)
		try:
			process.wait(timeout=10)
		except subprocess.TimeoutExpired:
			with self._lock:
				self._logs.append('Stop signal sent; the bot is still shutting down.')
		return True


def _read_skip_existing_check(handler):
	"""Read the optional {skip_existing_check: true} JSON body of /api/start.

	An empty body keeps the previous behaviour of searching for duplicates.
	"""
	content_length = handler.headers.get('Content-Length')
	if not content_length:
		return False
	try:
		body_length = int(content_length)
	except ValueError:
		return False
	if body_length <= 0 or body_length > MAX_BODY_SIZE:
		return False

	raw_body = handler.rfile.read(body_length)
	if not raw_body.strip():
		return False
	try:
		payload = json.loads(raw_body.decode('utf-8'))
	except (ValueError, UnicodeDecodeError):
		return False
	return bool(payload.get('skip_existing_check')) if isinstance(payload, dict) else False


controller = BotController()


class DashboardHandler(BaseHTTPRequestHandler):
	def _send(self, status, content_type, body):
		encoded = body.encode('utf-8')
		self.send_response(status)
		self.send_header('Content-Type', content_type + '; charset=utf-8')
		self.send_header('Content-Length', str(len(encoded)))
		self.send_header('Cache-Control', 'no-store')
		self.send_header('X-Content-Type-Options', 'nosniff')
		self.send_header('Referrer-Policy', 'no-referrer')
		self.end_headers()
		self.wfile.write(encoded)

	def _send_json(self, status, value):
		self._send(
			status,
			'application/json',
			json.dumps(value, ensure_ascii=False)
		)

	def _is_local_request(self):
		return (
			self.client_address[0] in ('127.0.0.1', '::1')
			and self.headers.get('Host') in (
				f'{HOST}:{PORT}',
				f'localhost:{PORT}'
			)
		)

	def _has_valid_origin(self):
		return self.headers.get('Origin') in (
			f'http://{HOST}:{PORT}',
			f'http://localhost:{PORT}'
		)

	def do_GET(self):
		if not self._is_local_request():
			self.send_error(403, 'Panel ini hanya tersedia di komputer ini.')
			return

		path = urlparse(self.path).path
		if path == '/api/status':
			try:
				self._send_json(200, controller.status())
			except (OSError, subprocess.SubprocessError) as error:
				self._send_json(503, {'error': str(error)})
			return

		files = {
			'/': ROOT / 'dashboard.html',
			'/generator': ROOT / 'index.html'
		}
		file_path = files.get(path)
		if file_path is None:
			self.send_error(404, 'Halaman tidak ditemukan.')
			return
		self._send(200, 'text/html', file_path.read_text(encoding='utf-8-sig'))

	def do_POST(self):
		if not self._is_local_request() or not self._has_valid_origin():
			self.send_error(403, 'Permintaan harus berasal dari panel lokal.')
			return

		path = urlparse(self.path).path
		try:
			if path == '/api/start':
				pid = controller.start(
					skip_existing_check=_read_skip_existing_check(self)
				)
				self._send_json(200, {'started': True, 'pid': pid})
			elif path == '/api/stop':
				stopping = controller.stop()
				self._send_json(200, {'stopping': stopping})
			else:
				self.send_error(404, 'Endpoint tidak ditemukan.')
		except BotAlreadyRunningError as error:
			self._send_json(409, {'error': str(error)})
		except (OSError, subprocess.SubprocessError) as error:
			self._send_json(503, {'error': str(error)})

	def log_message(self, _format, *_args):
		return


def main():
	server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
	url = f'http://{HOST}:{PORT}'
	print('Panel lokal berjalan di ' + url)
	print('Panel hanya menerima koneksi dari komputer ini.')
	threading.Timer(0.5, webbrowser.open, args=(url,)).start()
	try:
		server.serve_forever()
	except KeyboardInterrupt:
		print('\nPanel dihentikan.')
	finally:
		if controller.stop():
			print('Sinyal berhenti dikirim ke bot.')
		server.server_close()


if __name__ == '__main__':
	main()
