"""Bounded HTTPS requests run off the QGIS UI thread. Redirects never carry tokens."""
import json
import urllib.error
import urllib.request
from qgis.core import QgsTask, QgsApplication
from .uploads import FilePart

ORIGIN = "https://app.getcollar.io"
MAX_RESPONSE = 32 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RequestTask(QgsTask):
    def __init__(self, method, path, token, organisation, body, callback):
        super().__init__("Collar: " + method, QgsTask.Flag.CanCancel)
        if not path.startswith('/api/') or path.startswith('//') or '#' in path:
            raise ValueError("Invalid Collar API path")
        self.method, self.path = method, path
        self.token, self.organisation = token, organisation
        self.body, self.callback = body, callback
        self.result, self.error = None, None
        self.http_status = None
        self.connection_error = False

    def run(self):
        if self.isCanceled():
            self.token = None
            return False
        headers = {"Content-Type": "application/json", "X-Client": "api", "User-Agent": "Collar for QGIS/0.3.2"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if self.organisation:
            headers["X-Organisation-Id"] = self.organisation
        binary = isinstance(self.body, (bytes, FilePart))
        try:
            data = self.body.read() if isinstance(self.body, FilePart) else self.body if isinstance(self.body, bytes) else None if self.body is None else json.dumps(self.body).encode("utf-8")
        except Exception as error:
            self.error = str(error)
            self.token = None
            return False
        if binary:
            headers["Content-Type"] = "application/octet-stream"
        if data and len(data) > (8 if binary else 4) * 1024 * 1024:
            self.token = None
            self.error = "Upload exceeds Collar's 4 MiB request limit. Publish a smaller selection."
            return False
        request = urllib.request.Request(ORIGIN + self.path, data=data, headers=headers, method=self.method)
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=45) as response:
                payload = response.read(MAX_RESPONSE + 1)
                if len(payload) > MAX_RESPONSE:
                    raise ValueError("Layer exceeds the plugin response limit")
                self.result = json.loads(payload)
            return True
        except urllib.error.HTTPError as error:
            self.http_status = error.code
            try:
                message = json.loads(error.read(8192)).get("message", "Request rejected")
            except (ValueError, AttributeError):
                message = "Request rejected"
            self.error = ("Session expired. Sign out, then connect to Collar again." if error.code == 401 else str(message))
        except Exception:
            self.connection_error = True
            self.error = "Could not reach Collar. Local edits are retained; check your connection and try again."
        finally:
            self.token = None
        return False

    def finished(self, success):
        try:
            self.callback(self.result if success else None, self.error or (None if success else "Request cancelled"))
        finally:
            self.result = None
            self.body = None
            self.callback = None


def request(method, path, token, organisation, body, callback):
    task = RequestTask(method, path, token, organisation, body, callback)
    QgsApplication.taskManager().addTask(task)
    return task
