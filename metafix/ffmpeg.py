"""AVI metadata reading and lossless remuxing."""
import json
import subprocess
from .processes import run_hidden
from pathlib import Path
from .config import state
import os
import tempfile
from .dates import format_datetime, local_datetime

def ffmpeg_path():
    p = state["config"].get("ffmpeg_path", "")
    if not p:
        raise Exception("FFmpeg path not set. Click 'set ffmpeg' in the titlebar.")
    return p


def ffmpeg_available():
    return bool(state["config"].get("ffmpeg_path", ""))


def ffmpeg_read_creation_time(filepath):
    """Read creation_time from an AVI via ffprobe."""
    ffprobe = Path(ffmpeg_path()).parent / "ffprobe.exe"
    if not ffprobe.exists():
        ffprobe = "ffprobe"
    cmd = [str(ffprobe), "-v", "quiet", "-print_format", "json",
           "-show_format", str(filepath)]
    try:
        r = run_hidden(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=120)
        data = json.loads(r.stdout)
        tags = data.get("format", {}).get("tags", {})
        raw = tags.get("creation_time", "") or tags.get("date", "")
        if not raw:
            return ""
        # "2024-06-01T14:32:09.000000Z" → "2024:06:01 14:32:09"
        clean = format_datetime(raw)
        return clean
    except Exception as e:
        print("ffprobe error:", e)
        return ""


def ffmpeg_write_creation_time(filepath, dt_str):
    """Remux into a uniquely reserved file; caller owns the pre-write backup."""
    path = Path(filepath)
    temp = None
    try:
        dt = local_datetime(dt_str)
        if dt.tzinfo is None:
            dt = dt.astimezone()
        dt_iso = dt.isoformat(timespec='seconds')
        handle, name = tempfile.mkstemp(prefix='.metafix-', suffix=path.suffix, dir=path.parent)
        os.close(handle)
        temp = Path(name)
        result = run_hidden(
            [ffmpeg_path(), '-y', '-i', str(path), '-map', '0', '-c', 'copy',
             '-metadata', f'creation_time={dt_iso}', '-metadata', f'date={dt_iso}', str(temp)],
            capture_output=True, encoding='utf-8', errors='replace', timeout=600,
        )
        if result.returncode:
            return False, f'FFmpeg exit {result.returncode}: {result.stderr[-500:]}'
        if not temp.exists() or temp.stat().st_size == 0:
            return False, 'FFmpeg produced no output'
        temp.replace(path)
        return True, ''
    except Exception as exc:
        return False, str(exc)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
