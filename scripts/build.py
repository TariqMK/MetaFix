"""Build and archive a native portable distribution on the current runner."""
import argparse
import os
import platform
from pathlib import Path
import re
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'\d+\.\d+\.\d+', args.version):
        parser.error('version must be MAJOR.MINOR.PATCH')
    root = Path(__file__).resolve().parent.parent
    os.chdir(root)
    system = platform.system()
    icon = root / 'docs/assets/icon.png'
    if not icon.is_file():
        raise SystemExit(f'Application icon is missing: {icon}')
    arch = platform.machine().lower()
    if system == 'Darwin' and arch != 'arm64':
        raise SystemExit('macOS releases must be built natively for Apple Silicon')
    # Embed the allocated release version without committing a version bump.
    (root / 'metafix' / '_version.txt').write_text(args.version + '\n', encoding='utf-8')
    # Run from the repo root without --specpath, so PyInstaller resolves these relative paths
    # from here. --specpath made it look for them under build/ instead.
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
               '--onedir', '--windowed', '--name', 'MetaFix',
               '--add-data', 'metafix/templates:metafix/templates',
               '--add-data', 'metafix/static:metafix/static',
               '--add-data', 'metafix/_version.txt:metafix',
               '--add-data', f'{icon.relative_to(root).as_posix()}:metafix/assets',
               '--hidden-import', 'webview.platforms.qt',
               '--collect-data', 'webview', '--collect-submodules', 'webview.dom']
    # Embed the native file icon; Linux uses the bundled PNG at runtime.
    if system in ('Windows', 'Darwin'):
        native_icon = icon.with_suffix('.ico' if system == 'Windows' else '.icns')
        if not native_icon.is_file():
            raise SystemExit(f'Application icon is missing: {native_icon}')
        command += ['--icon', native_icon.relative_to(root).as_posix()]
    if system == 'Darwin':
        command += ['--target-architecture', 'arm64', '--osx-bundle-identifier', 'com.tariqmk.metafix']
    subprocess.run(command + ['MetaFix.py'], check=True)
    if system == 'Darwin':
        stamp_macos_version(root / 'dist/MetaFix.app', args.version)
    executable = {
        'Windows': root / 'dist/MetaFix/MetaFix.exe',
        'Darwin': root / 'dist/MetaFix.app/Contents/MacOS/MetaFix',
        'Linux': root / 'dist/MetaFix/MetaFix',
    }[system]
    env = dict(os.environ)
    env['QT_QPA_PLATFORM'] = 'offscreen'
    # The self-test exits 1 when the built-in version differs. A windowed Windows build
    # prints nothing, so only macOS and Linux check the printed line too.
    result = subprocess.run([str(executable), '--self-test', '--expect-version', args.version],
                            timeout=120, env=env, capture_output=True, text=True)
    print(result.stdout + result.stderr)
    if result.returncode:
        raise SystemExit(f'Self-test failed with exit code {result.returncode}')
    if system != 'Windows':
        lines = result.stdout.strip().splitlines()
        if not lines or lines[-1] != f'MetaFix v{args.version}':
            raise SystemExit(f'Self-test did not print MetaFix v{args.version}')
    output = root / 'release-assets'
    output.mkdir(exist_ok=True)
    target = {'Windows': 'windows-x64', 'Darwin': 'macos-arm64', 'Linux': 'linux-x64'}[system]
    basename = output / f'MetaFix-v{args.version}-{target}'
    if system == 'Darwin':
        # ditto preserves app bundle symlinks, resource forks, and permissions.
        subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent',
                        'dist/MetaFix.app', str(basename) + '.zip'], check=True)
    else:
        shutil.make_archive(str(basename), 'zip' if system == 'Windows' else 'gztar',
                            root_dir='dist', base_dir='MetaFix')


def stamp_macos_version(app, version):
    """Set the version Finder shows (PyInstaller leaves 0.0.0), then sign again.

    Editing Info.plist breaks PyInstaller's ad-hoc signature, and Apple Silicon won't
    open an app with a broken signature.
    """
    plist = app / 'Contents/Info.plist'
    # plutil -replace also adds a missing key. PyInstaller's plist has no CFBundleVersion,
    # so PlistBuddy's "Set" fails on it.
    for key in ('CFBundleShortVersionString', 'CFBundleVersion'):
        subprocess.run(['plutil', '-replace', key, '-string', version, str(plist)], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)


if __name__ == '__main__':
    main()
