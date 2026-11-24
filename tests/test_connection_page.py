import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import base64
import hashlib

from collar_qgis.connection_page import SCRIPT, SCRIPT_HASH, SECURITY_HEADERS, response_body


class ConnectionPageTests(unittest.TestCase):
    def test_confirmation_is_self_contained_and_has_explicit_close_fallback(self):
        page = response_body(True).decode()
        self.assertIn('Connected successfully', page)
        self.assertIn('return to QGIS', page)
        self.assertIn('Close window', page)
        self.assertIn('close this tab manually', page)
        self.assertIn(SCRIPT, page)
        self.assertNotIn('<script src=', page)
        self.assertNotIn('<img', page)
        self.assertIn("default-src 'none'", SECURITY_HEADERS.decode())
        self.assertIn("frame-ancestors 'none'", SECURITY_HEADERS.decode())
        self.assertIn(
            base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode(), SCRIPT_HASH
        )
        self.assertIn('Cache-Control: no-store', SECURITY_HEADERS.decode())

    def test_failed_exchange_never_claims_success(self):
        page = response_body(False).decode()
        self.assertIn('Connection not completed', page)
        self.assertNotIn('Connected successfully', page)
