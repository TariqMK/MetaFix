"""End-to-end check of a running MetaFix: load, preview, apply, undo and backup clean-up on copies of a sample JPEG.

It drives the app's local API the same way the window does, with the app's real ExifTool.
It only touches the copies it makes in the work folder. Standard library only, so it runs on any test machine.

Usage:
  1. Start MetaFix (source or a build) with ExifTool set in Tools.
  2. Find the port it listens on:
       macOS:   lsof -nP -a -p <pid> -iTCP -sTCP:LISTEN
       Linux:   ss -ltnp | grep MetaFix
       Windows: (Get-NetTCPConnection -State Listen -OwningProcess (Get-Process MetaFix).Id).LocalPort
  3. python scripts/check_e2e.py http://127.0.0.1:<port> <sample.jpg> <new empty folder>
     The sample must be a JPEG that has EXIF dates, for example t/images/ExifTool.jpg from the ExifTool source.
     The work folder path must not contain a folder named "backups".
"""
import hashlib, json, shutil, sys, urllib.request
from pathlib import Path

base, sample, work = sys.argv[1].rstrip('/'), Path(sys.argv[2]), Path(sys.argv[3])
failures = []


def check(name, ok, detail=''):
    print(('PASS ' if ok else 'FAIL ') + name + (f' -- {detail}' if detail and not ok else ''))
    if not ok:
        failures.append(name)


def call(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, headers={'Content-Type': 'application/json'},
                                 method='GET' if body is None else 'POST')
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read().decode('utf-8', 'replace')
            return r.status, (json.loads(raw) if raw.lstrip().startswith(('{', '[')) else raw)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or '{}')


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


if work.exists() and any(work.iterdir()):
    # The check edits every file it loads from this folder, so never run it on real photos.
    sys.exit(f'Work folder must be new or empty: {work}')
work.mkdir(parents=True, exist_ok=True)
a, b = work / 'photo-a.jpg', work / 'photo-b.jpg'
shutil.copyfile(sample, a)
shutil.copyfile(sample, b)
orig = {str(a): sha(a), str(b): sha(b)}

status, page = call('/')
check('UI page loads', status == 200 and 'MetaFix' in str(page))
status, cfg = call('/api/config')
check('ExifTool path configured', status == 200 and bool(cfg.get('exiftool_path')), cfg)

call('/api/clear_files', {})
status, res = call('/api/drop_files', {'paths': [str(work)]})
loaded = [f.get('path', f) if isinstance(f, dict) else f for f in res.get('files', [])]
check('Folder load finds 2 files', status == 200 and len(loaded) == 2, res)
paths = sorted(str(p) for p in loaded)

status, before = call('/api/read_metadata', {})
check('Metadata read returns a date per file', status == 200 and all(str(before.get(p, {}).get('value', ''))[:4].isdigit() for p in paths), before)

req = {'mode': 'manual', 'datetime': '2024:01:02 03:04:05',
       'dest_fields': ['DateTimeOriginal', 'CreateDate'], 'touch_fs': True}
status, prev = call('/api/preview', req)
check('Preview plans the new date', status == 200 and all('2024:01:02 03:04' in str(prev.get(p)) for p in paths), prev)
check('Preview changes nothing on disk', all(sha(p) == orig[p] for p in paths))

status, res = call('/api/apply', req)
check('Apply succeeds', status == 200 and res.get('ok'), res)
status, after = call('/api/read_metadata', {})
check('Dates are written', all('2024:01:02 03:04' in str(after.get(p, {}).get('value')) for p in paths), after)
check('Files changed on disk', all(sha(p) != orig[p] for p in paths))
check('Backups created', (work / 'BACKUPS').is_dir() and len(list((work / 'BACKUPS').iterdir())) >= 2)

status, res = call('/api/undo', {})
check('Undo succeeds', status == 200 and res.get('ok'), res)
check('Undo restores original bytes', all(sha(p) == orig[p] for p in paths))

shift = {'mode': 'shift', 'days': 1, 'hours': 2, 'dest_fields': ['DateTimeOriginal'],
         'selected_paths': [paths[0]]}
status, res = call('/api/apply', shift)
check('Shift on one selected file succeeds', status == 200 and res.get('ok') and len(res.get('results', {})) == 1, res)
check('Unselected file untouched', sha(paths[1]) == orig[paths[1]])
status, res = call('/api/undo', {})
check('Shift undo restores bytes', status == 200 and sha(paths[0]) == orig[paths[0]], res)

status, res = call('/api/cleanup_backups', {})
check('Cleanup asks for confirmation first', res.get('confirmation_required') is True, res)
status, res = call('/api/cleanup_backups', {'confirm_paths': res.get('backups')})
remaining = list((work / 'BACKUPS').iterdir()) if (work / 'BACKUPS').exists() else []
check('Cleanup removes the backups', status == 200 and not remaining, res)

call('/api/clear_files', {})
print(f'RESULT: {"FAIL" if failures else "PASS"} ({len(failures)} failed)')
sys.exit(1 if failures else 0)
