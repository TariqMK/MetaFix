"""Runs MetaFix.py --self-test from source, so a change can't break it unnoticed."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent


def run(*args):
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    return subprocess.run([sys.executable, str(ROOT / 'MetaFix.py'), *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)


class SelfTestTests(unittest.TestCase):
    def test_passes_and_prints_version_last(self):
        from metafix import __version__
        result = run('--self-test')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip().splitlines()[-1], f'MetaFix v{__version__}')

    def test_wrong_expected_version_fails(self):
        result = run('--self-test', '--expect-version', '99.99.99')
        self.assertEqual(result.returncode, 1)
        self.assertIn('expected 99.99.99', result.stdout)


if __name__ == '__main__':
    unittest.main()
