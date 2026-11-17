"""Bounded public imagery fallback for the QGIS XYZ provider; no Collar credentials.

Only fixed Esri URLs are fetched. The loopback listener is owned by the enabled
plugin, accepts validated tile coordinates only and never proxies arbitrary URLs.
"""
import re
import threading
import time
import urllib.request
import urllib.error
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from qgis.PyQt.QtCore import QByteArray, QBuffer, QIODevice, QRectF
from qgis.PyQt.QtGui import QImage, QImageReader, QPainter

TILES = 'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}?blankTile=false'
MAX_ZOOM = 19
MAX_IMAGE = 2 * 1024 * 1024
MAX_CACHE = 32 * 1024 * 1024
ROUTE = re.compile(r'/esri/(0|[1-9][0-9]?)/(0|[1-9][0-9]{0,6})/(0|[1-9][0-9]{0,6})\.png\Z')

class MissingTile(Exception):
    pass

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def fetch_tile(z, x, y):
    request = urllib.request.Request(TILES.format(z=z, x=x, y=y), headers={'User-Agent':'Collar for QGIS/0.3.2'})
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=4) as response:
            if response.status == 204:
                raise MissingTile()
            if response.headers.get_content_type() not in ('image/jpeg', 'image/png'):
                raise ValueError('Unexpected imagery response')
            data = response.read(MAX_IMAGE + 1)
            if len(data) > MAX_IMAGE:
                raise ValueError('Imagery response limit exceeded')
            return data
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise MissingTile() from None
        raise


def decode_tile(data):
    if len(data) > MAX_IMAGE:
        raise ValueError('Imagery response limit exceeded')
    encoded = QByteArray(data)
    source = QBuffer(encoded)
    source.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(source)
    size = reader.size()
    if size.width() != 256 or size.height() != 256:
        raise ValueError('Invalid imagery tile dimensions')
    image = reader.read()
    if image.isNull():
        raise ValueError('Invalid imagery tile')
    return image


def crop_parent(data, z, x, y, level):
    image = decode_tile(data)
    if z != level:
        factor = 2 ** (z - level)
        source = QRectF((x % factor) * 256 / factor, (y % factor) * 256 / factor, 256 / factor, 256 / factor)
        result = QImage(256, 256, QImage.Format.Format_ARGB32)
        result.fill(0)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(QRectF(0, 0, 256, 256), image, source)
        painter.end()
        image = result
    encoded = QByteArray()
    buffer = QBuffer(encoded)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, 'PNG'):
        raise ValueError('Could not prepare imagery')
    return bytes(encoded)


class TileCache:
    def __init__(self, fetch=fetch_tile):
        self.fetch = fetch
        self.cache = OrderedDict()
        self.missing = OrderedDict()
        self.size = 0
        self.lock = threading.RLock()
        self.stopped = threading.Event()

    def tile(self, z, x, y):
        if not (0 <= z <= MAX_ZOOM and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
            raise ValueError('Invalid tile coordinates')
        deadline = time.monotonic() + 20
        for level in range(z, -1, -1):
            if self.stopped.is_set() or time.monotonic() >= deadline:
                raise TimeoutError('Imagery request stopped')
            key = (level, x >> (z-level), y >> (z-level))
            with self.lock:
                data = self.cache.get(key)
                if data is not None:
                    self.cache.move_to_end(key)
                missing = self.missing.get(key, 0) > time.monotonic()
            if missing:
                continue
            if data is None:
                try:
                    data = self.fetch(*key)
                    # Validate before storing; never cache placeholders or non-images.
                    decode_tile(data)
                except MissingTile:
                    if self.stopped.is_set():
                        raise TimeoutError('Imagery request stopped')
                    with self.lock:
                        self.missing[key] = time.monotonic() + 60
                        self.missing.move_to_end(key)
                        while len(self.missing) > 512:
                            self.missing.popitem(last=False)
                    continue
                with self.lock:
                    if self.stopped.is_set():
                        raise TimeoutError('Imagery request stopped')
                    previous = self.cache.pop(key, None)
                    if previous:
                        self.size -= len(previous)
                    self.cache[key] = data
                    self.size += len(data)
                    while self.size > MAX_CACHE:
                        _, value = self.cache.popitem(last=False)
                        self.size -= len(value)
            return crop_parent(data, z, x, y, level)
        raise MissingTile()

    def close(self):
        self.stopped.set()
        with self.lock:
            self.cache.clear()
            self.missing.clear()
            self.size = 0


class LimitedServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    block_on_close = False
    request_queue_size = 16
    allow_reuse_address = False

    def __init__(self, cache):
        self.cache = cache
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(('127.0.0.1', 0), TileHandler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            request.settimeout(5)
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, *_):
        pass  # No request paths, map extents or request headers in logs.


class TileHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        match = ROUTE.fullmatch(self.path)
        if not match or self.headers.get('Host') != '127.0.0.1:' + str(self.server.server_port):
            self.send_error(400)
            return
        try:
            z, x, y = map(int, match.groups())
            data = self.server.cache.tile(z, x, y)
        except ValueError:
            self.send_error(400)
            return
        except Exception:
            self.send_error(503, 'Imagery temporarily unavailable')
            return
        self.send_response(200)
        self.send_header('Content-Type', 'image/png')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(data)


class ImageryService:
    def __init__(self, fetch=fetch_tile):
        self.cache = TileCache(fetch)
        self.server = LimitedServer(self.cache)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval':0.05}, name='Collar public imagery', daemon=True)
        self.thread.start()

    @property
    def url(self):
        return 'http://127.0.0.1:' + str(self.server.server_port) + '/esri/{z}/{x}/{y}.png'

    def close(self):
        self.cache.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=1)
