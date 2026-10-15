"""Regression tests use temporary dummy media, never user files or external tools."""
from copy import deepcopy
from pathlib import Path
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from metafix import create_app
from metafix import backups, dates, desktop, exiftool, ffmpeg, operations, processes
from metafix.config import state
from metafix.files import collect_paths, _add_paths
from metafix.session import session_lock


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.saved = deepcopy(state)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.records_patch = patch.object(backups, 'RECORDS_DIR', self.root / 'app-data' / 'backup-records')
        self.records_patch.start()
        self.file = self.root / 'photo.jpg'
        self.file.write_bytes(b'original')
        state.update(files=[str(self.file)], last_batch=[], config={'ffmpeg_path': 'ffmpeg'})
        self.request = {'mode': 'manual', 'datetime': '2024:01:02 03:04:05',
                        'dest_fields': ['CreateDate'], 'win_creation': False}

    def tearDown(self):
        state.clear()
        state.update(self.saved)
        self.records_patch.stop()
        self.tmp.cleanup()

    def write(self, args):
        file = Path(args[-1])
        file.write_bytes(file.read_bytes() + b'-edited')
        return SimpleNamespace(returncode=0, stdout='1 image files updated', stderr='')

    def apply(self, **options):
        with patch.object(operations, 'run_exiftool_write', side_effect=self.write):
            return operations.apply_changes(self.request | options)

    def test_backups_are_flat_and_keep_original_filenames(self):
        self.apply()
        self.apply()
        folder = self.root / 'BACKUPS'
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ['photo(1).jpg', 'photo.jpg'])
        self.assertTrue(all(p.is_file() for p in folder.iterdir()))
        self.assertEqual((folder / 'photo.jpg').read_bytes(), b'original')
        self.assertEqual((folder / 'photo(1).jpg').read_bytes(), b'original-edited')
        self.assertEqual(len(list(backups.RECORDS_DIR.glob('*.json'))), 2)

    def test_existing_flat_backup_is_not_overwritten_or_adopted(self):
        folder = self.root / 'BACKUPS'
        folder.mkdir()
        (folder / 'photo.jpg').write_bytes(b'older backup')
        self.apply()
        self.assertEqual((folder / 'photo.jpg').read_bytes(), b'older backup')
        plan = operations.cleanup_backups()
        self.assertEqual(plan['backups'], [str(folder / 'photo(1).jpg')])
        operations.cleanup_backups({'confirm_paths': plan['backups']})
        self.assertEqual((folder / 'photo.jpg').read_bytes(), b'older backup')

    def test_repeated_apply_undo_uses_latest_backup(self):
        self.apply()
        first = self.file.read_bytes()
        self.apply()
        self.assertTrue(operations.undo()['ok'])
        self.assertEqual(self.file.read_bytes(), first)

    def test_rename_undo_restores_name_and_removes_modified_copy(self):
        result = self.apply(rename=True)
        new = Path(result['renamed'][str(self.file)])
        self.assertTrue(new.exists())
        self.assertFalse(self.file.exists())
        self.assertTrue(operations.undo()['ok'])
        self.assertEqual(self.file.read_bytes(), b'original')
        self.assertFalse(new.exists())
        self.assertEqual(state['files'], [str(self.file)])

    def test_failed_restore_remains_retryable(self):
        self.apply()
        edited = self.file.read_bytes()
        self.file.write_bytes(b'external change')
        self.assertFalse(operations.undo()['ok'])
        self.assertEqual(self.file.read_bytes(), b'external change')
        self.assertTrue(state['last_batch'])
        self.file.write_bytes(edited)
        self.assertTrue(operations.undo()['ok'])

    def test_undo_does_not_overwrite_file_at_old_name(self):
        self.apply(rename=True)
        self.file.write_bytes(b'someone else')
        self.assertFalse(operations.undo()['ok'])
        self.assertEqual(self.file.read_bytes(), b'someone else')

    def test_backup_failure_prevents_write(self):
        with patch.object(operations, 'create_backup', side_effect=OSError('disk full')), \
             patch.object(operations, 'run_exiftool_write') as write:
            result = operations.apply_changes(self.request)
            self.assertFalse(result['ok'])
            write.assert_not_called()
        self.assertEqual(self.file.read_bytes(), b'original')

    def test_renaming_never_overwrites_existing_timestamp_name(self):
        collision = self.root / '2024-01-02_03-04-05_photo.jpg'
        collision.write_bytes(b'existing')
        result = self.apply(rename=True)
        self.assertTrue(result['ok'])
        self.assertEqual(collision.read_bytes(), b'existing')
        self.assertIn('(1)', result['renamed'][str(self.file)])

    def test_failed_write_does_not_rename_or_replace_previous_undo(self):
        self.apply()
        previous = deepcopy(state['last_batch'])
        failed = SimpleNamespace(returncode=1, stdout='', stderr='Error: failed')
        with patch.object(operations, 'run_exiftool_write', return_value=failed), \
             patch.object(operations, '_rename_file') as rename:
            result = operations.apply_changes(self.request | {'rename': True})
            self.assertFalse(result['ok'])
            rename.assert_not_called()
        self.assertEqual(state['last_batch'], previous)

    def test_partial_failed_write_has_recovery_record(self):
        def fail(args):
            self.write(args)
            raise RuntimeError('tool crashed')
        with patch.object(operations, 'run_exiftool_write', side_effect=fail):
            self.assertFalse(operations.apply_changes(self.request)['ok'])
        self.assertTrue(operations.undo()['ok'])
        self.assertEqual(self.file.read_bytes(), b'original')

    def test_postprocessing_failure_reported_and_undoable(self):
        with patch.object(operations, 'set_win_creation_time', side_effect=RuntimeError('PowerShell failed')):
            result = self.apply(win_creation=True)
        self.assertFalse(result['results'][str(self.file)]['ok'])
        self.assertTrue(result['can_undo'])
        self.assertTrue(operations.undo()['ok'])

    def test_rename_failure_reported(self):
        with patch.object(operations, '_rename_file', side_effect=OSError('not allowed')):
            result = self.apply(rename=True)
        self.assertIn('Rename failed', result['results'][str(self.file)]['error'])
        self.assertTrue(result['can_undo'])

    def test_scans_and_direct_add_exclude_backups(self):
        folder = self.root / 'BACKUPS'
        folder.mkdir()
        hidden = folder / 'photo.jpg'
        hidden.write_bytes(b'backup')
        nested = self.root / 'nested'
        nested.mkdir()
        (nested / 'another.jpg').write_bytes(b'photo')
        found = collect_paths([self.root], recursive=True)
        self.assertEqual(len(found), 2)
        self.assertNotIn(str(hidden), found)
        _add_paths([str(hidden)])
        self.assertEqual(state['files'], [str(self.file)])

    def test_cleanup_only_deletes_confirmed_owned_backups(self):
        self.apply()
        unrelated = self.root / 'BACKUPS' / 'old.jpg'
        unrelated.write_bytes(b'leave me')
        plan = operations.cleanup_backups()
        self.assertEqual(plan['count'], 1)
        self.assertTrue(Path(plan['backups'][0]).exists())
        result = operations.cleanup_backups({'confirm_paths': plan['backups']})
        self.assertEqual(result['count'], 1)
        self.assertEqual(unrelated.read_bytes(), b'leave me')
        self.assertFalse(state['last_batch'])

    def test_cleanup_requires_reconfirmation_when_scope_changes(self):
        self.apply()
        plan = operations.cleanup_backups()
        self.apply()
        result = operations.cleanup_backups({'confirm_paths': plan['backups']})
        self.assertTrue(result['confirmation_required'])
        self.assertEqual(result['count'], 2)

    def test_modified_backup_is_never_restored_or_cleaned(self):
        self.apply()
        Path(state['last_batch'][0]['backup']).write_bytes(b'changed')
        self.assertFalse(operations.undo()['ok'])
        self.assertEqual(operations.cleanup_backups()['count'], 0)

    def test_validation_rejects_entire_batch_before_write(self):
        invalid = [{'mode': 'unknown'}, {'datetime': '2024:99:01'},
                   {'dest_fields': ['CreateDate\n-overwrite_original']},
                   {'years': 'abc'}, {'rename': 'yes'}, {'selected_paths': ['missing.jpg']}]
        with patch.object(operations, 'run_exiftool_write') as write:
            for options in invalid:
                result, status = operations.apply_changes(self.request | options)
                self.assertEqual(status, 400)
            write.assert_not_called()
        self.assertFalse((self.root / 'BACKUPS').exists())

    def test_missing_copy_source_in_one_file_prevents_all_writes(self):
        other = self.root / 'other.jpg'
        other.write_bytes(b'other')
        state['files'].append(str(other))
        with patch.object(operations, 'read_source_datetime', side_effect=['2024:01:01 12:00:00', ValueError('empty')]), \
             patch.object(operations, 'run_exiftool_write') as write:
            result, code = operations.apply_changes(self.request | {'mode': 'copy'})
            self.assertEqual(code, 400)
            self.assertIn(str(other), result['file_errors'])
            write.assert_not_called()

    def test_avi_copy_preview_and_apply_resolve_same_date(self):
        avi = self.root / 'movie.avi'
        avi.write_bytes(b'avi')
        state['files'] = [str(avi)]
        data = self.request | {'mode': 'copy'}
        with patch.object(operations, 'read_source_datetime', return_value='2024:06:01 14:32:09.000000Z'), \
             patch.object(operations, 'ffmpeg_write_creation_time', return_value=(True, '')) as write:
            preview = operations.preview(data)
            self.assertTrue(operations.apply_changes(data)['ok'])
            self.assertEqual(write.call_args.args[1], preview[str(avi)])

    def test_fractional_seconds_and_offsets_parse(self):
        value = '2024-06-01T14:32:09.123456+02:00'
        self.assertEqual(dates.parse_datetime(value).utcoffset().total_seconds(), 7200)
        self.assertIsNotNone(dates.compute_shifted_dt(value, hours=1))
        self.assertEqual(dates.compute_shifted_dt('2024:01:31 12:00:00', months=1), '2024:02:29 12:00:00')

    def test_wall_clock_shift_crosses_daylight_saving_boundary(self):
        # Target is a local wall-clock date. ExifTool's QuickTimeUTC uses its
        # target date's local offset, rather than preserving a fixed UTC offset.
        self.assertEqual(dates.compute_shifted_dt('2024:03:30 12:00:00', days=1), '2024:03:31 12:00:00')
        self.assertEqual(dates.compute_shifted_dt('2024:10:26 12:00:00', days=1), '2024:10:27 12:00:00')

    def test_windows_tools_use_no_window_and_hidden_startup_flags(self):
        startup = SimpleNamespace(dwFlags=0, wShowWindow=99)
        with patch.object(processes.os, 'name', 'nt'), \
             patch.object(processes.subprocess, 'CREATE_NO_WINDOW', 0x08000000, create=True), \
             patch.object(processes.subprocess, 'STARTUPINFO', return_value=startup, create=True), \
             patch.object(processes.subprocess, 'STARTF_USESHOWWINDOW', 1, create=True), \
             patch.object(processes.subprocess, 'SW_HIDE', 0, create=True), \
             patch.object(processes.subprocess, 'run') as run:
            processes.run_hidden(['tool'], creationflags=8, capture_output=True)
            options = run.call_args.kwargs
            self.assertEqual(options['creationflags'], 0x08000008)
            self.assertEqual(options['startupinfo'].dwFlags & 1, 1)
            self.assertEqual(options['startupinfo'].wShowWindow, 0)

    def test_non_windows_processes_receive_no_windows_only_flags(self):
        with patch.object(processes.os, 'name', 'posix'), patch.object(processes.subprocess, 'run') as run:
            processes.run_hidden(['tool'], capture_output=True)
            self.assertNotIn('creationflags', run.call_args.kwargs)
            self.assertNotIn('startupinfo', run.call_args.kwargs)

    def test_legacy_tracked_backups_remain_cleanable(self):
        folder = self.root / 'BACKUPS' / '.metafix' / 'older'
        folder.mkdir(parents=True)
        backup = folder / self.file.name
        backup.write_bytes(b'legacy original')
        record = {'owner': backups.LEGACY_OWNER, 'original': str(self.file),
                  'current': str(self.file), 'backup': str(backup),
                  'before_hash': backups.fingerprint(backup)}
        backups.save_record(record)
        plan = operations.cleanup_backups()
        self.assertEqual(plan['backups'], [str(backup)])
        self.assertEqual(operations.cleanup_backups({'confirm_paths': plan['backups']})['count'], 1)
        self.assertFalse((self.root / 'BACKUPS').exists())
        self.assertEqual(self.file.read_bytes(), b'original')

    def test_powershell_filename_is_data_not_code(self):
        name = str(self.root / '$(Write-Output danger)$name.jpg')
        with patch.object(dates.subprocess, 'run', return_value=SimpleNamespace(returncode=0)) as run:
            dates.set_win_creation_time(name, '2024:01:01 12:00:00')
            command = run.call_args.args[0]
            self.assertNotIn(name, command[-1])
            self.assertEqual(run.call_args.kwargs['env']['METAFIX_FILE'], name)
            self.assertIn("$ErrorActionPreference = 'Stop'", command[-1])

    def test_exiftool_argument_file_removed_on_success_and_timeout(self):
        state['config']['exiftool_path'] = 'exiftool'
        paths = []
        def execute(command, **kwargs):
            path = Path(command[-1])
            self.assertTrue(path.exists())
            self.assertIn('QuickTimeUTC=1', command)
            paths.append(path)
            return SimpleNamespace(returncode=0, stdout='', stderr='')
        with patch.object(exiftool.subprocess, 'run', side_effect=execute):
            exiftool.run_exiftool(['-j', str(self.file)])
            exiftool.run_exiftool_write(['-CreateDate=2024:01:01 12:00:00', str(self.file)])
        self.assertTrue(all(not path.exists() for path in paths))
        def timeout(command, **kwargs):
            paths.append(Path(command[-1]))
            raise subprocess.TimeoutExpired(command, 120)
        with patch.object(exiftool.subprocess, 'run', side_effect=timeout):
            with self.assertRaises(subprocess.TimeoutExpired):
                exiftool.run_exiftool(['-j', str(self.file)])
        self.assertFalse(paths[-1].exists())

    def test_ffmpeg_temp_does_not_clobber_predictable_filename(self):
        avi = self.root / 'movie.avi'
        avi.write_bytes(b'original')
        collision = self.root / 'movie_metafix_tmp.avi'
        collision.write_bytes(b'untouched')
        created = []
        def execute(command, **kwargs):
            output = Path(command[-1])
            created.append(output)
            self.assertNotEqual(output, collision)
            output.write_bytes(b'remuxed')
            return SimpleNamespace(returncode=0, stderr='')
        with patch.object(ffmpeg.subprocess, 'run', side_effect=execute):
            self.assertTrue(ffmpeg.ffmpeg_write_creation_time(str(avi), '2024:01:01 12:00:00')[0])
        self.assertEqual(avi.read_bytes(), b'remuxed')
        self.assertEqual(collision.read_bytes(), b'untouched')
        self.assertFalse(created[0].exists())

    def test_ffmpeg_failure_cleans_only_its_reserved_temp(self):
        avi = self.root / 'movie.avi'
        avi.write_bytes(b'original')
        paths = []
        def fail(command, **kwargs):
            paths.append(Path(command[-1]))
            raise subprocess.TimeoutExpired(command, 600)
        with patch.object(ffmpeg.subprocess, 'run', side_effect=fail):
            self.assertFalse(ffmpeg.ffmpeg_write_creation_time(str(avi), '2024:01:01 12:00:00')[0])
        self.assertEqual(avi.read_bytes(), b'original')
        self.assertFalse(paths[0].exists())

    def test_bad_api_requests_fail_before_dialogs_or_file_mutation(self):
        client = create_app().test_client()
        with patch('metafix.routes.webview.windows') as windows:
            for route, payload in [('/api/preview', []), ('/api/apply', {'mode':'bad'}),
                                   ('/api/add_folder', {'recursive':'yes'}),
                                   ('/api/drop_files', {'paths':[[]]}),
                                   ('/api/remove_files', {'paths':[[]]})]:
                response = client.post(route, json=payload)
                self.assertEqual(response.status_code, 400, route)
                self.assertIn('error', response.json)
            self.assertFalse(windows.mock_calls)
        self.assertEqual(self.file.read_bytes(), b'original')

    def test_second_request_is_rejected_while_session_is_busy(self):
        held, release = threading.Event(), threading.Event()
        def hold():
            with session_lock:
                held.set()
                release.wait(5)
        thread = threading.Thread(target=hold)
        thread.start()
        try:
            held.wait(5)
            client = create_app().test_client()
            self.assertEqual(client.post('/api/clear_files', json={}).status_code, 409)
            self.assertEqual(state['files'], [str(self.file)])
        finally:
            release.set()
            thread.join()
        self.assertEqual(client.post('/api/read_metadata', json=[]).status_code, 400)

    def test_api_rejects_reading_unloaded_paths(self):
        client = create_app().test_client()
        response = client.post('/api/read_metadata', json={'files': ['not-loaded.jpg']})
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json)

    def test_native_drop_only_hands_paths_to_guarded_ui(self):
        with patch.object(desktop, '_window') as window:
            window.evaluate_js.return_value = False
            desktop.on_drop({'dataTransfer': {'files': [{'pywebviewFullPath': str(self.file)}]}})
            script = window.evaluate_js.call_args.args[0]
            self.assertIn('window.receiveNativeDrop(', script)
        self.assertEqual(state['files'], [str(self.file)])

    def test_desktop_binds_ephemeral_port_before_window(self):
        server = SimpleNamespace(server_port=54321)
        with patch.object(desktop, 'make_server', return_value=server) as make, \
             patch.object(desktop.threading, 'Thread') as thread, \
             patch.object(desktop.webview, 'create_window') as window, \
             patch.object(desktop.webview, 'start'), \
             patch.object(server, 'shutdown', create=True), \
             patch.object(server, 'server_close', create=True):
            desktop.main()
            self.assertEqual(make.call_args.args[:2], ('127.0.0.1', 0))
            self.assertEqual(window.call_args.args[1], 'http://127.0.0.1:54321')
            thread.return_value.start.assert_called_once()
            server.shutdown.assert_called_once()
            server.server_close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
