import base64
import hashlib
import secrets
from urllib.parse import urlencode, urlsplit, parse_qs
from qgis.PyQt.QtCore import QObject, QTimer, QUrl, pyqtSignal
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtNetwork import QTcpServer, QHostAddress
from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsSettings
from .network import ORIGIN
from .connection_page import response_body, SECURITY_HEADERS


class TokenStore:
    """Only an encrypted QGIS auth database stores the revocable session."""
    def __init__(self):
        self.auth_id = QgsSettings().value("collar/authcfg", "", type=str)

    def read(self):
        if not self.auth_id:
            return None
        config = QgsAuthMethodConfig()
        if QgsApplication.authManager().loadAuthenticationConfig(self.auth_id, config, True):
            return config.config("password") or None
        return None

    def save(self, token):
        manager = QgsApplication.authManager()
        if not manager.setMasterPassword(True):
            raise ValueError("Unlock the QGIS authentication database to connect Collar")
        config = QgsAuthMethodConfig()
        config.setName("Collar for QGIS")
        config.setMethod("Basic")
        config.setConfig("username", "collar-session")
        config.setConfig("password", token)
        if self.auth_id:
            config.setId(self.auth_id)
            ok = manager.updateAuthenticationConfig(config)
        else:
            ok = manager.storeAuthenticationConfig(config)
        if not ok:
            raise ValueError("QGIS could not securely store the Collar session")
        self.auth_id = config.id()
        QgsSettings().setValue("collar/authcfg", self.auth_id)

    def clear(self):
        if self.auth_id:
            QgsApplication.authManager().removeAuthenticationConfig(self.auth_id)
        QgsSettings().remove("collar/authcfg")
        self.auth_id = ""


class BrowserLogin(QObject):
    ready = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server = QTcpServer(self)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.expire)
        self.server.newConnection.connect(self.receive)
        self.sockets = []
        self.pending_socket = None

    def start(self):
        self.stop()
        self.verifier, self.state = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).decode().rstrip("=")
        if not self.server.listen(QHostAddress.SpecialAddress.LocalHost, 0):
            raise ValueError("Could not open the QGIS local callback")
        self.redirect = "http://127.0.0.1:{}/callback".format(self.server.serverPort())
        self.timer.start(120000)
        url = ORIGIN + "/integrations/qgis?" + urlencode({"challenge": challenge, "state": self.state, "redirectUri": self.redirect})
        if not QDesktopServices.openUrl(QUrl(url)):
            self.stop()
            raise ValueError("Could not open your browser")

    def receive(self):
        socket = self.server.nextPendingConnection()
        self.sockets.append(socket)
        socket.setProperty("request", b"")
        socket.readyRead.connect(lambda: self.read(socket))
        socket.disconnected.connect(socket.deleteLater)

    def read(self, socket):
        if socket.property("handled"):
            return
        data = bytes(socket.property("request") or b"") + bytes(socket.readAll())
        socket.setProperty("request", data)
        if len(data) > 8192:
            socket.disconnectFromHost()
            return
        if b"\r\n\r\n" not in data:
            return
        socket.setProperty("handled", True)
        valid = False
        try:
            method, target, _ = data.split(b"\r\n", 1)[0].decode("ascii").split(" ")
            url = urlsplit(target)
            query = parse_qs(url.query)
            code = query.get("code", [""])[0]
            valid = method == "GET" and url.path == "/callback" and not url.netloc and secrets.compare_digest(query.get("state", [""])[0], self.state) and len(code) == 36
        except (ValueError, UnicodeError):
            pass
        if valid:
            self.stop()
            self.pending_socket = socket
            self.timer.start(60000)
            self.ready.emit({"code": code, "verifier": self.verifier, "redirectUri": self.redirect})
        else:
            self.respond(socket, False)

    def respond(self, socket, success):
        message = response_body(success)
        status = b"200 OK" if success else b"400 Bad Request"
        try:
            socket.write(b"HTTP/1.1 " + status + b"\r\nContent-Type: text/html; charset=utf-8\r\n" + SECURITY_HEADERS + b"Connection: close\r\nContent-Length: " + str(len(message)).encode() + b"\r\n\r\n" + message)
            socket.disconnectFromHost()
        except RuntimeError:
            pass  # The browser may have closed the tab during sign-in.

    def complete(self, success):
        if self.pending_socket is not None:
            socket, self.pending_socket = self.pending_socket, None
            self.timer.stop()
            self.respond(socket, success)

    def stop(self):
        self.complete(False)
        self.timer.stop()
        self.server.close()
        self.sockets = []

    def expire(self):
        self.stop()
        self.failed.emit("Connection timed out. Select Connect to try again.")
