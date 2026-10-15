"""Local wall-clock timestamps, offset-aware parsing, and Windows file dates."""
from datetime import datetime
import os
import subprocess
from dateutil.relativedelta import relativedelta


def parse_datetime(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A valid datetime is required")
    text = value.strip()
    text = text[:10].replace(":", "-") + text[10:]
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def local_datetime(value):
    dt = parse_datetime(value) if isinstance(value, str) else value
    return dt.astimezone() if dt.tzinfo is not None else dt


def format_datetime(value, include_offset=True):
    dt = local_datetime(value)
    result = dt.strftime("%Y:%m:%d %H:%M:%S")
    if include_offset and dt.tzinfo is not None:
        offset = dt.strftime("%z")
        result += offset[:3] + ":" + offset[3:]
    return result


def _strip_tz(value):
    """Compatibility helper for display/legacy callers; convert before stripping."""
    try:
        return format_datetime(value, include_offset=False)
    except (ValueError, TypeError, OverflowError):
        return ""


def compute_shifted_dt(original_str, years=0, months=0, days=0, hours=0, minutes=0):
    try:
        # Shift local wall-clock time, allowing QuickTimeUTC to apply the target
        # date's timezone/DST offset when it writes integer QuickTime fields.
        dt = local_datetime(original_str).replace(tzinfo=None)
        dt += relativedelta(years=years, months=months, days=days, hours=hours, minutes=minutes)
        return format_datetime(dt, include_offset=False)
    except (ValueError, TypeError, OverflowError):
        return None


def set_win_creation_time(filepath, dt_str):
    """Pass paths as environment data, never as interpolated PowerShell code."""
    script = (
        "$ErrorActionPreference = 'Stop'; "
        "$f = Get-Item -LiteralPath $env:METAFIX_FILE; "
        "$d = [datetime]::ParseExact($env:METAFIX_DATE, 'yyyy-MM-dd HH:mm:ss', "
        "[System.Globalization.CultureInfo]::InvariantCulture); "
        "$f.CreationTime = $d; $f.LastWriteTime = $d"
    )
    env = dict(os.environ)
    env['METAFIX_FILE'] = str(filepath)
    env['METAFIX_DATE'] = local_datetime(dt_str).strftime('%Y-%m-%d %H:%M:%S')
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
            env=env, capture_output=True, encoding='utf-8', errors='replace', timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Windows timestamp update failed: {exc}") from exc
    if result.returncode:
        raise RuntimeError(f"Windows timestamp update failed: {result.stderr.strip()}")
    return True
