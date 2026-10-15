"""ExifTool execution, including Unicode-safe Windows arguments."""
import subprocess
from .processes import run_hidden
import logging
from pathlib import Path
import re
from .config import state

def exiftool_path():
    p = state["config"].get("exiftool_path", "")
    if not p:
        raise Exception("ExifTool path not set.")
    return p


def run_exiftool(args):
    """All ExifTool read calls. Uses a UTF-8 argfile to avoid Windows codepage
    mangling of Unicode paths (e.g. curly apostrophes in folder names)."""
    import tempfile
    et = exiftool_path()
    # Write args to a temp file in UTF-8 — ExifTool reads it with -@
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                     suffix='.txt', delete=False) as f:
        f.write('\n'.join(args))
        argfile = f.name
    try:
        result = run_hidden(
            [et, '-api', 'QuickTimeUTC=1', '-charset', 'filename=UTF8', '-@', argfile],
            capture_output=True, encoding='utf-8', errors='replace', timeout=120
        )
    finally:
        try:
            Path(argfile).unlink(missing_ok=True)
        except OSError:
            logging.exception('Unable to remove ExifTool argument file')
    return result


def run_exiftool_write(args):
    """Write with explicit local-to-UTC conversion for QuickTime integer dates."""
    import tempfile
    et = exiftool_path()
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                     suffix='.txt', delete=False) as f:
        f.write('\n'.join(args))
        argfile = f.name
    try:
        result = run_hidden(
            [et, '-api', 'QuickTimeUTC=1', '-charset', 'filename=UTF8', '-m', '-@', argfile],
            capture_output=True, encoding='utf-8', errors='replace', timeout=120
        )
    finally:
        try:
            Path(argfile).unlink(missing_ok=True)
        except OSError:
            logging.exception('Unable to remove ExifTool argument file')
    return result


def exiftool_error(r):
    """Extract meaningful error text from an ExifTool result."""
    # ExifTool writes errors/warnings to stdout (as plain text) and stderr
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    # Filter out the "1 image files updated" success lines
    lines = [l for l in out.splitlines()
             if l and not re.match(r'^\s*\d+ image files? (updated|unchanged|created)', l, re.I)]
    combined = "\n".join(lines)
    if err:
        combined = (combined + "\n" + err).strip()
    return combined or None

