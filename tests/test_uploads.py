import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tempfile
import unittest

from collar_qgis.uploads import FilePart


class FilePartTests(unittest.TestCase):
    def test_reads_only_the_requested_range_and_rejects_changed_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.tif'
            path.write_bytes(b'0123456789')
            stat = path.stat()
            part = FilePart(str(path), 3, 4, stat.st_size, stat.st_mtime_ns)
            self.assertEqual(part.read(), b'3456')
            path.write_bytes(b'changed-source')
            with self.assertRaises(ValueError):
                part.read()
