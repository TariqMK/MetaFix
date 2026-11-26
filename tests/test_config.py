"""Settings file loading: accepts files with or without a UTF-8 BOM."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from metafix import config


class LoadConfigTests(unittest.TestCase):
    def load(self, raw):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.json'
            path.write_bytes(raw)
            with patch.object(config, 'CONFIG', path):
                return config.load_config()

    def test_plain_utf8(self):
        self.assertEqual(self.load(json.dumps({'exiftool_path': 'C:/et.exe'}).encode()),
                         {'exiftool_path': 'C:/et.exe'})

    def test_utf8_with_bom(self):
        # Windows PowerShell 5.1 and Notepad in older Windows save UTF-8 with a BOM.
        raw = b'\xef\xbb\xbf' + json.dumps({'exiftool_path': 'C:/et.exe'}).encode()
        self.assertEqual(self.load(raw), {'exiftool_path': 'C:/et.exe'})

    def test_broken_file_gives_empty_settings(self):
        self.assertEqual(self.load(b'{not json'), {})


if __name__ == '__main__':
    unittest.main()
