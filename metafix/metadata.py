"""Read media timestamps with format-specific fallbacks."""
import json
from pathlib import Path
from .fields import AVI_EXTS
from .dates import _strip_tz, format_datetime
from .exiftool import run_exiftool
from .ffmpeg import ffmpeg_available, ffmpeg_read_creation_time

def normalise_path(p):
    return str(Path(p)).replace("\\", "/")


def read_metadata_batch(files):
    """Returns dict: path -> {"value": "2026:06:06 21:34:15", "field": "CreateDate"}
    For AVI files with no EXIF data, falls back to ffprobe creation_time."""
    if not files:
        return {}

    avi_files  = [f for f in files if Path(f).suffix.lower() in AVI_EXTS]
    other_files = [f for f in files if Path(f).suffix.lower() not in AVI_EXTS]

    result = {}

    # ── Non-AVI: ExifTool batch ───────────────────────────────────────────────
    if other_files:
        norm_to_orig = {normalise_path(f): f for f in other_files}
        fields = [
            "-DateTimeOriginal", "-CreateDate", "-MediaCreateDate",
            "-TrackCreateDate", "-TrackModifyDate", "-ModifyDate",
            "-ContentCreateDate", "-FileModifyDate", "-FileCreateDate",
        ]
        args = ["-j"] + fields + list(other_files)
        try:
            r = run_exiftool(args)
            if r.returncode:
                raise RuntimeError(r.stderr.strip() or 'ExifTool metadata read failed')
            raw = r.stdout.strip()
            if raw:
                data = json.loads(raw)
                for item in data:
                    src_raw = item.get("SourceFile", "")
                    orig = norm_to_orig.get(src_raw) or norm_to_orig.get(normalise_path(src_raw)) or src_raw
                    for key in (
                        "DateTimeOriginal", "ContentCreateDate", "CreateDate",
                        "MediaCreateDate", "TrackCreateDate", "TrackModifyDate",
                        "ModifyDate", "FileCreateDate", "FileModifyDate"
                    ):
                        val = item.get(key, "")
                        if val and val not in ("0000:00:00 00:00:00", ""):
                            result[orig] = {"value": val, "field": key}
                            break
                    else:
                        result[orig] = {"value": "—", "field": ""}
            else:
                for f in other_files:
                    result[f] = {"value": "—", "field": ""}
        except Exception as e:
            print("read_metadata_batch error:", e)
            for f in other_files:
                result[f] = {"value": "—", "field": "", "error": str(e)}

    # ── AVI: ffprobe (if available), else ExifTool read ───────────────────────
    for f in avi_files:
        val = ""
        field = ""
        if ffmpeg_available():
            val = ffmpeg_read_creation_time(f)
            if val:
                field = "creation_time"
        if not val:
            # Try ExifTool read-only as last resort
            try:
                r = run_exiftool(["-j", "-CreateDate", "-FileModifyDate", f])
                items = json.loads(r.stdout)
                if items:
                    for key in ("CreateDate", "FileModifyDate"):
                        v = _strip_tz(items[0].get(key, ""))
                        if v and v not in ("0000:00:00 00:00:00", ""):
                            val, field = v, key
                            break
            except Exception:
                pass
        result[f] = {"value": val or "—", "field": field}

    return result



def read_source_datetime(filepath, source_field):
    """One source resolver shared by preview and apply, including AVI fallback."""
    if Path(filepath).suffix.lower() in AVI_EXTS and ffmpeg_available():
        value = ffmpeg_read_creation_time(filepath)
        if value:
            return format_datetime(value)
    if source_field == 'creation_time':
        raise ValueError('No AVI creation_time available')
    result = run_exiftool(['-j', f'-{source_field}', filepath])
    if result.returncode:
        raise ValueError(result.stderr.strip() or 'Metadata read failed')
    items = json.loads(result.stdout)
    value = items[0].get(source_field, '') if items else ''
    if not value:
        raise ValueError(f'Source field {source_field} is empty')
    return format_datetime(value)
