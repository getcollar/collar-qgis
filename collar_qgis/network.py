"""Bounded, proxy-aware HTTPS requests run off the QGIS UI thread."""

import json

from qgis.core import QgsApplication, QgsBlockingNetworkRequest, QgsFeedback, QgsTask
from qgis.PyQt.QtCore import QByteArray, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest

from .uploads import FilePart

ORIGIN = 'https://app.getcollar.io'
MAX_RESPONSE = 32 * 1024 * 1024
USER_AGENT = b'Collar for QGIS/0.4.2'


def _attribute(name):
    """Return a QNetworkRequest attribute across Qt 5 and Qt 6."""
    enum = getattr(QNetworkRequest, 'Attribute', QNetworkRequest)
    return getattr(enum, name)


def _redirect_policy(name):
    """Return a redirect policy across Qt 5 and Qt 6."""
    enum = getattr(QNetworkRequest, 'RedirectPolicy', QNetworkRequest)
    return getattr(enum, name)


def _error_code(name):
    """Return a QgsBlockingNetworkRequest error code across QGIS 3 and 4."""
    enum = getattr(QgsBlockingNetworkRequest, 'ErrorCode', QgsBlockingNetworkRequest)
    return getattr(enum, name)


class RequestTask(QgsTask):
    def __init__(self, method, path, token, organisation, body, callback):
        super().__init__('Collar: ' + method, QgsTask.Flag.CanCancel)
        if not path.startswith('/api/') or path.startswith('//') or '#' in path:
            raise ValueError('Invalid Collar API path')
        self.method, self.path = method, path
        self.token, self.organisation = token, organisation
        self.body, self.callback = body, callback
        self.result, self.error = None, None
        self.http_status = None
        self.connection_error = False
        self.feedback = QgsFeedback()

    def cancel(self):
        self.feedback.cancel()
        super().cancel()

    def _network_request(self):
        request = QNetworkRequest(QUrl(ORIGIN + self.path))
        request.setRawHeader(b'Content-Type', b'application/json')
        request.setRawHeader(b'X-Client', b'api')
        request.setRawHeader(b'User-Agent', USER_AGENT)
        request.setAttribute(
            _attribute('RedirectPolicyAttribute'),
            _redirect_policy('ManualRedirectPolicy'),
        )
        request.setTransferTimeout(45_000)
        if self.token:
            request.setRawHeader(b'Authorization', ('Bearer ' + self.token).encode('utf-8'))
        if self.organisation:
            request.setRawHeader(b'X-Organisation-Id', self.organisation.encode('utf-8'))
        return request

    def run(self):
        if self.isCanceled():
            self.token = None
            return False
        binary = isinstance(self.body, (bytes, FilePart))
        try:
            if isinstance(self.body, FilePart):
                data = self.body.read()
            elif isinstance(self.body, bytes):
                data = self.body
            elif self.body is None:
                data = None
            else:
                data = json.dumps(self.body).encode('utf-8')
        except Exception as error:
            self.error = str(error)
            self.token = None
            return False
        if data and len(data) > (8 if binary else 4) * 1024 * 1024:
            self.token = None
            self.error = "Upload exceeds Collar's 4 MiB request limit. Publish a smaller selection."
            return False

        request = self._network_request()
        if binary:
            request.setRawHeader(b'Content-Type', b'application/octet-stream')
        network = QgsBlockingNetworkRequest()
        try:
            body = QByteArray(data or b'')
            if self.method == 'GET':
                outcome = network.get(request, True, self.feedback)
            elif self.method == 'POST':
                outcome = network.post(request, body, True, self.feedback)
            elif self.method == 'PUT':
                outcome = network.put(request, body, self.feedback)
            elif self.method == 'DELETE':
                outcome = network.deleteResource(request, self.feedback)
            else:
                raise ValueError('Unsupported HTTP method')

            reply = network.reply()
            status = reply.attribute(_attribute('HttpStatusCodeAttribute'))
            self.http_status = int(status) if status is not None else None
            payload = bytes(reply.content())
            if len(payload) > MAX_RESPONSE:
                raise ValueError('Layer exceeds the plugin response limit')
            if outcome != _error_code('NoError') or not (200 <= (self.http_status or 0) < 300):
                if self.isCanceled():
                    self.error = 'Request cancelled'
                    return False
                if self.http_status is None:
                    self.connection_error = True
                    self.error = (
                        'Could not reach Collar. Local edits are retained; '
                        'check your connection and try again.'
                    )
                    return False
                try:
                    message = json.loads(payload[:8192]).get('message', 'Request rejected')
                except (ValueError, AttributeError):
                    message = 'Request rejected'
                self.error = (
                    'Session expired. Sign out, then connect to Collar again.'
                    if self.http_status == 401
                    else str(message)
                )
                return False
            self.result = json.loads(payload) if payload else None
            return True
        except ValueError as error:
            self.error = str(error)
        except Exception:
            self.connection_error = not self.isCanceled()
            self.error = (
                'Request cancelled'
                if self.isCanceled()
                else 'Could not reach Collar. Local edits are retained; '
                'check your connection and try again.'
            )
        finally:
            self.token = None
        return False

    def finished(self, success):
        try:
            self.callback(
                self.result if success else None,
                self.error or (None if success else 'Request cancelled'),
            )
        finally:
            self.result = None
            self.body = None
            self.callback = None


def request(method, path, token, organisation, body, callback):
    task = RequestTask(method, path, token, organisation, body, callback)
    QgsApplication.taskManager().addTask(task)
    return task
