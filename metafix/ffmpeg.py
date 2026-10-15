"""AVI metadata reading and lossless remuxing."""
import json
import subprocess
from pathlib import Path
from .config import state
from .backups import _backup_dir
from .dates import _strip_tz

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
        r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
        data = json.loads(r.stdout)
        tags = data.get("format", {}).get("tags", {})
        raw = tags.get("creation_time", "") or tags.get("date", "")
        if not raw:
            return ""
        # "2024-06-01T14:32:09.000000Z" → "2024:06:01 14:32:09"
        clean = _strip_tz(raw.replace("T", " ").replace("-", ":", 2))
        return clean
    except Exception as e:
        print("ffprobe error:", e)
        return ""


def ffmpeg_write_creation_time(filepath, dt_str):
    """
    Remux AVI with updated creation_time. No re-encoding.
    dt_str: ExifTool format "2024:06:01 14:32:09"
    Returns (True, "") or (False, error_message).
    """
    import shutil
    # "2024:06:01 14:32:09" → "2024-06-01T14:32:09"
    try:
        # Pad missing seconds: "2024:06:01 14:32" → "2024:06:01 14:32:00"
        if dt_str.count(':') == 3:
            dt_str = dt_str + ':00'
        dt_iso = dt_str[:10].replace(":", "-") + "T" + dt_str[11:]
    except Exception:
        return False, f"Could not convert datetime: {dt_str}"

    p = Path(filepath)
    tmp = p.parent / (p.stem + "_metafix_tmp" + p.suffix)

    cmd = [
        ffmpeg_path(), "-y",
        "-i", str(p),
        "-map", "0",
        "-c", "copy",
        "-metadata", f"creation_time={dt_iso}",
        "-metadata", f"date={dt_iso}",
        str(tmp)
    ]
    print("FFMPEG CMD:", cmd)
    try:
        r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
        print("FFMPEG STDERR:", r.stderr[-500:] if r.stderr else "")
        if r.returncode != 0:
            if tmp.exists(): tmp.unlink()
            return False, f"FFmpeg exit {r.returncode}: {r.stderr[-200:]}"
        if not tmp.exists() or tmp.stat().st_size == 0:
            return False, "FFmpeg produced no output"
        bd = _backup_dir(filepath)
        bd.mkdir(exist_ok=True)
        dest = bd / p.name
        counter = 1
        while dest.exists():
            dest = bd / f"{p.stem}({counter}){p.suffix}"
            counter += 1
        shutil.copy2(str(p), str(dest))
        tmp.replace(p)
        return True, ""
    except Exception as e:
        if tmp.exists():
            try: tmp.unlink()
            except: pass
        return False, str(e)

