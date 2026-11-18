"""Retakes the README feature screenshots from the real MetaFix interface, using made-up sample files.

Run from the project folder (Python 3.10+):

    uv run --python 3.12 --with flask --with python-dateutil --with playwright python docs/assets/make_screenshots.py

First time only, install the browser:  uv run --with playwright playwright install chromium

How it works:
- Starts the real Flask app from source on 127.0.0.1, without a native window.
- Creates made-up sample files in a temporary folder. Each file holds its own dates as JSON.
- Replaces ExifTool with a stand-in that reads and writes those JSON dates, so preview, apply,
  backups and undo all run the app's real code. No real media, settings or network are used.
- Captures the page content only (no system window frame) at 1200 x 820, scale 2, in dark and light.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import types
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / 'screenshots'
SIZE = {'width': 1200, 'height': 820}
NEUTRAL_ROOT = PurePosixPath('/Users/alex/Pictures')  # Shown in place of the temporary folder.

# Made-up sample files: name -> {field: value}. Values use ExifTool's date format.
READ_FROM_SAMPLES = {
    'IMG_0412.jpg': {'DateTimeOriginal': '2019:06:14 18:30:00'},
    'IMG_0413.jpg': {'DateTimeOriginal': '2019:06:14 18:42:17'},
    'IMG_0418.heic': {'DateTimeOriginal': '2019:06:15 09:05:51'},
    'DSC_1120.jpg': {'CreateDate': '2019:06:15 13:33:40'},
    'VID_0420.mov': {'ContentCreateDate': '2019:06:15 11:20:04'},
    'VID_0431.mp4': {'MediaCreateDate': '2019:06:16 16:02:55'},
    'IMG-20190616-WA0007.jpg': {'FileModifyDate': '2023:02:11 08:14:33'},
    'IMG-20190616-WA0008.jpg': {'FileModifyDate': '2023:02:11 08:14:35'},
    'IMG-20190617-WA0012.jpg': {'FileModifyDate': '2023:02:11 08:14:41'},
    'Scan_family_03.png': {'FileCreateDate': '2024:11:02 20:01:12'},
}
RENAME_SAMPLES = {
    'IMG_0412.jpg': {'DateTimeOriginal': '2019:06:14 18:30:00', 'CreateDate': '2023:02:11 08:14:33'},
    'IMG_0413.jpg': {'DateTimeOriginal': '2019:06:14 18:42:17', 'CreateDate': '2023:02:11 08:14:33'},
    'IMG_0418.jpg': {'DateTimeOriginal': '2019:06:15 09:05:51', 'CreateDate': '2023:02:11 08:14:34'},
    'IMG_0421.jpg': {'DateTimeOriginal': '2019:06:15 12:48:09', 'CreateDate': '2023:02:11 08:14:34'},
    'IMG_0436.jpg': {'DateTimeOriginal': '2019:06:16 19:12:44', 'CreateDate': '2023:02:11 08:14:35'},
}


def latest_tag():
    """Newest release tag, so the screenshots don't show the development version."""
    try:
        tags = subprocess.run(['git', 'tag', '--list', 'v*', '--sort=-v:refname'], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout.split()
        return tags[0].lstrip('v') if tags else '0.0.0+dev'
    except (OSError, subprocess.CalledProcessError):
        return '0.0.0+dev'


def install_stand_ins(work):
    """Isolate the app: no native window, no saved settings, fake ExifTool, records in the temp folder."""
    stub = types.ModuleType('webview')  # The real package opens native windows; nothing here needs one.
    stub.windows, stub.OPEN_DIALOG, stub.FOLDER_DIALOG = [], 10, 20
    sys.modules['webview'] = stub
    sys.path.insert(0, str(ROOT))

    import metafix, metafix.config, metafix.routes, metafix.metadata, metafix.operations, metafix.backups

    metafix.config.state['config'] = {'exiftool_path': 'exiftool (sample stand-in)'}
    metafix.routes.save_config = lambda cfg: None
    metafix.backups.RECORDS_DIR = work / 'backup-records'
    metafix.routes.__version__ = latest_tag()
    metafix.routes.os = types.SimpleNamespace(name='posix')  # Same images on every system.

    def result(items):
        return types.SimpleNamespace(returncode=0, stdout=json.dumps(items), stderr='')

    def fake_read(args):
        fields = [a[1:] for a in args if a.startswith('-') and a != '-j']
        items = []
        for name in (a for a in args if not a.startswith('-')):
            dates = json.loads(Path(name).read_text(encoding='utf-8'))
            item = {'SourceFile': Path(name).as_posix()}
            item.update({f: dates[f] for f in fields if f in dates})
            items.append(item)
        return result(items)

    def fake_write(args):
        target = Path(args[-1])
        dates = json.loads(target.read_text(encoding='utf-8'))
        for arg in args[:-1]:
            if '=' in arg:
                field, value = arg[1:].split('=', 1)
                dates[field] = value[:19]
        target.write_text(json.dumps(dates), encoding='utf-8')
        return result([])

    metafix.metadata.run_exiftool = fake_read
    metafix.operations.run_exiftool_write = fake_write
    return metafix.create_app()


def make_folder(base, name, samples):
    folder = base / name
    folder.mkdir(parents=True)
    for file, dates in samples.items():
        (folder / file).write_text(json.dumps(dates), encoding='utf-8')
    return folder


def neutral(path, work):
    return str(NEUTRAL_ROOT / PurePosixPath(Path(path).relative_to(work).as_posix()))


def capture(page, name, theme):
    OUT.mkdir(exist_ok=True)
    target = OUT / f'{name}-{theme}.png'
    page.screenshot(path=str(target))
    print('saved', target.name)


def reset_session():
    """Start each view with an empty file list and no undo batch."""
    from metafix.config import state
    state['files'], state['last_batch'] = [], []


def drop(page, folder):
    page.evaluate('paths => window.receiveNativeDrop(paths)', [str(folder)])
    page.wait_for_function("!document.getElementById('fileTable').innerHTML.includes('loading')")
    page.wait_for_timeout(300)


def run(url, work, theme, shots):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport=SIZE, device_scale_factor=2, color_scheme=theme,
                                      locale='en-GB', timezone_id='Europe/London')
        page = context.new_page()
        page.on('pageerror', lambda e: sys.exit(f'Page error: {e}'))
        # Show backup paths under a made-up folder instead of the real temporary folder.
        def rewrite(route):
            response = route.fetch()
            data = response.json()
            if 'backups' in data:
                data['backups'] = [neutral(p, work / theme) for p in data['backups']]
            route.fulfill(response=response, json=data)
        page.route('**/api/cleanup_backups', rewrite)

        if 'read-from' in shots:
            reset_session()
            page.goto(url)
            drop(page, work / theme / 'Camera roll')
            page.click('.mode-tab[data-mode="copy"]')
            page.wait_for_timeout(300)
            capture(page, 'read-from', theme)

        if {'rename-applied', 'backups'} & shots:
            reset_session()
            page.goto(url)
            drop(page, work / theme / 'Holiday 2019')
            page.click('.mode-tab[data-mode="copy"]')
            page.select_option('#copySource', 'DateTimeOriginal')
            page.check('#optRename')
            page.click('#commitBtn')  # Preview
            page.wait_for_timeout(1300)  # Apply stays locked for 1 s after a preview.
            page.click('#commitBtn')  # Apply
            page.wait_for_function("document.getElementById('statusMsg').textContent.includes('updated')")
            page.wait_for_timeout(300)
            page.mouse.move(0, SIZE['height'] - 1)
            if 'rename-applied' in shots:
                capture(page, 'rename-applied', theme)
            if 'backups' in shots:
                page.click('#cleanupBtn')
                page.wait_for_selector('#cleanupDialog[open]')
                page.wait_for_timeout(300)
                capture(page, 'backups', theme)
                page.click('#cleanupDialog button[value="keep"]')
        browser.close()


def main():
    views = ['read-from', 'rename-applied', 'backups']
    parser = argparse.ArgumentParser(description='Retake the MetaFix README screenshots.')
    parser.add_argument('--only', nargs='+', choices=views, default=views)
    shots = set(parser.parse_args().only)

    work = Path(tempfile.mkdtemp(prefix='metafix-shots-')).resolve()
    try:
        for theme in ('dark', 'light'):  # Separate copies, because applying changes the files.
            make_folder(work / theme, 'Camera roll', READ_FROM_SAMPLES)
            make_folder(work / theme, 'Holiday 2019', RENAME_SAMPLES)
        app = install_stand_ins(work)
        import logging
        logging.getLogger('werkzeug').setLevel(logging.ERROR)
        from werkzeug.serving import make_server
        server = make_server('127.0.0.1', 0, app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f'http://127.0.0.1:{server.server_port}/'
        for theme in ('dark', 'light'):
            run(url, work, theme, shots)
        server.shutdown()
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
