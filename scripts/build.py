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
    arch = platform.machine().lower()
    if system == 'Darwin' and arch != 'arm64':
        raise SystemExit('macOS releases must be built natively for Apple Silicon')
    # Embed the allocated release version without committing a version bump.
    (root / 'metafix' / '_version.txt').write_text(args.version + '\n', encoding='utf-8')
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
               '--onedir', '--windowed', '--name', 'MetaFix', '--specpath', 'build',
               # Data sources are resolved relative to the generated spec in
               # build/, so they must be absolute rather than project-relative.
               '--add-data', f'{root / "metafix/templates"}:metafix/templates',
               '--add-data', f'{root / "metafix/static"}:metafix/static',
               '--add-data', f'{root / "metafix/_version.txt"}:metafix',
               '--hidden-import', 'webview.platforms.qt',
               '--collect-data', 'webview', '--collect-submodules', 'webview.dom']
    if system == 'Darwin':
        command += ['--target-architecture', 'arm64', '--osx-bundle-identifier', 'com.tariqmk.metafix']
    subprocess.run(command + ['MetaFix.py'], check=True)
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


if __name__ == '__main__':
    main()
