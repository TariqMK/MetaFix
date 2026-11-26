"""Tool pickers: the ExifTool and FFmpeg programs must be selectable on every system."""
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from metafix import create_app, routes
from metafix.config import state
from webview.util import parse_file_type


def qt_shows(file_types, filename):
    """True when any filter in the picker lets Qt show a file with this name."""
    from PySide6.QtCore import QDir
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, filename).touch()
        for file_type in file_types:
            patterns = re.search(r'\((.*)\)', file_type).group(1).split(';')
            if QDir(tmp).entryList(patterns, QDir.Files):
                return True
    return False


class PickerTests(unittest.TestCase):
    def setUp(self):
        self.saved = dict(state['config'])
        self.client = create_app().test_client()

    def tearDown(self):
        state['config'] = self.saved

    def pick(self, route, chosen):
        window = MagicMock()
        window.create_file_dialog.return_value = [chosen]
        with patch.object(routes.webview, 'windows', [window]), \
             patch.object(routes, 'save_config') as save:
            response = self.client.post(route, json={})
        return response.get_json(), window.create_file_dialog.call_args.kwargs, save

    def test_exiftool_without_extension_is_selectable(self):
        # The reported bug: on macOS the picker only offered *.exe and *.*.
        if os.name == 'nt':
            self.skipTest('Windows tools end in .exe')
        result, kwargs, save = self.pick('/api/browse_exiftool', '/opt/homebrew/bin/exiftool')
        self.assertTrue(qt_shows(kwargs['file_types'], 'exiftool'), kwargs['file_types'])
        self.assertTrue(qt_shows(kwargs['file_types'], 'ffmpeg'))
        self.assertEqual(result, {'ok': True, 'path': '/opt/homebrew/bin/exiftool'})
        self.assertEqual(state['config']['exiftool_path'], '/opt/homebrew/bin/exiftool')
        save.assert_called_once()

    def test_ffmpeg_picker_saves_its_own_setting(self):
        result, kwargs, _ = self.pick('/api/browse_ffmpeg', '/usr/local/bin/ffmpeg')
        self.assertEqual(state['config']['ffmpeg_path'], '/usr/local/bin/ffmpeg')
        self.assertEqual(kwargs['file_types'], routes.tool_file_types(os.name == 'nt'))

    def test_windows_filters_show_exe(self):
        types = routes.tool_file_types(True)
        self.assertTrue(qt_shows(types, 'exiftool.exe'))

    def test_filters_are_valid_for_pywebview(self):
        for windows in (True, False):
            for file_type in routes.tool_file_types(windows):
                parse_file_type(file_type)  # Raises on a filter pywebview rejects.

    def test_start_folder_is_where_the_tool_is(self):
        folder = routes.tool_start_folder('exiftool', which=lambda name: '/opt/tools/exiftool')
        self.assertEqual(folder, '/opt/tools')

    def test_start_folder_falls_back_to_install_folder(self):
        if os.name == 'nt':
            self.skipTest('No standard tool folder on Windows')
        folder = routes.tool_start_folder('exiftool', which=lambda name: None,
                                          isdir=lambda path: path == '/usr/local/bin')
        self.assertEqual(folder, '/usr/local/bin')


if __name__ == '__main__':
    unittest.main()
