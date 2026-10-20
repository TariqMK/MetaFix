"""Check native build commands without running or installing PyInstaller."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import build


class BuildPathsTest(unittest.TestCase):
    def test_assets_exist_when_resolved_from_generated_spec_directory(self):
        for system, arch in [('Windows', 'AMD64'), ('Darwin', 'arm64'), ('Linux', 'x86_64')]:
            with self.subTest(system=system), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                (root / 'scripts').mkdir()
                (root / 'metafix/templates').mkdir(parents=True)
                (root / 'metafix/static').mkdir()
                (root / 'docs/assets').mkdir(parents=True)
                (root / 'docs/assets/icon.png').write_bytes(b'icon fixture')
                (root / 'docs/assets/icon.ico').write_bytes(b'ico fixture')
                (root / 'docs/assets/icon.icns').write_bytes(b'icns fixture')
                original_cwd = Path.cwd()
                try:
                    with patch.object(build, '__file__', str(root / 'scripts/build.py')), \
                         patch.object(sys, 'argv', ['build.py', '--version', '1.2.3']), \
                         patch.object(build.platform, 'system', return_value=system), \
                         patch.object(build.platform, 'machine', return_value=arch), \
                         patch.object(build.subprocess, 'run') as run, \
                         patch.object(build.shutil, 'make_archive'):
                        build.main()
                        command = run.call_args_list[0].args[0]
                        smoke = run.call_args_list[1]
                        self.assertIn('--smoke-test', smoke.args[0])
                        self.assertIn('--expect-version', smoke.args[0])
                        self.assertEqual(smoke.kwargs['timeout'], 120)
                        self.assertEqual(smoke.kwargs['env']['QT_QPA_PLATFORM'], 'offscreen')
                        sources = []
                        for i, value in enumerate(command):
                            if value == '--add-data':
                                source, destination = command[i + 1].rsplit(':', 1)
                                source = Path(source)
                                self.assertTrue(source.is_absolute())
                                self.assertTrue((root / 'build' / source).exists())
                                sources.append(destination)
                        self.assertEqual(sources, ['metafix/templates', 'metafix/static', 'metafix', 'metafix/assets'])
                        if system in ('Windows', 'Darwin'):
                            extension = 'ico' if system == 'Windows' else 'icns'
                            self.assertEqual(command[command.index('--icon') + 1],
                                             str(root / f'docs/assets/icon.{extension}'))
                        else:
                            self.assertNotIn('--icon', command)
                        self.assertEqual((root / 'metafix/_version.txt').read_text().strip(), '1.2.3')
                        if system == 'Darwin':
                            self.assertEqual(command[command.index('--target-architecture') + 1], 'arm64')
                finally:
                    os.chdir(original_cwd)


if __name__ == '__main__':
    unittest.main()
