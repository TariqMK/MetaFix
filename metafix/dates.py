"""Date parsing, shifts, and Windows filesystem timestamps."""
import re
import subprocess

def _strip_tz(dt_str):
    if not dt_str or not isinstance(dt_str, str):
        return ""
    s = dt_str.strip()
    s = re.sub(r'[+-]\d{2}:\d{2}$', '', s).strip()
    s = re.sub(r'Z$', '', s).strip()
    return s


def compute_shifted_dt(original_str, years=0, months=0, days=0, hours=0, minutes=0):
    from datetime import datetime
    from dateutil.relativedelta import relativedelta
    s = original_str.strip()
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M"):
        try:
            dt = datetime.strptime(s, fmt)
            dt = dt + relativedelta(years=years, months=months, days=days,
                                     hours=hours, minutes=minutes)
            return dt.strftime("%Y:%m:%d %H:%M:%S")
        except ValueError:
            continue
    return None


def set_win_creation_time(filepath, dt_str):
    """Set Windows filesystem CreationTime and LastWriteTime via PowerShell.
    Uses -EncodedCommand (Base64 UTF-16LE) to bypass all quoting/encoding
    issues with Unicode characters in paths (e.g. curly apostrophes)."""
    import base64
    try:
        win_dt = dt_str[:10].replace(":", "-") + dt_str[10:]
        # Build the PS script with the path embedded as a here-string variable
        # to completely sidestep quoting. Encode as UTF-16LE for -EncodedCommand.
        ps_script = (
            f'$p = @"\n{filepath}\n"@\n'
            f'$p = $p.Trim()\n'
            f'$f = Get-Item -LiteralPath $p\n'
            f'$f.CreationTime = "{win_dt}"\n'
            f'$f.LastWriteTime = "{win_dt}"\n'
        )
        encoded = base64.b64encode(ps_script.encode("utf-16-le")).decode("ascii")
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-EncodedCommand", encoded],
            capture_output=True, encoding="utf-8", errors="replace"
        )
        if r.returncode != 0:
            print(f"PowerShell CreationTime error: {r.stderr.strip()}")
            return False
        return True
    except Exception as e:
        print(f"set_win_creation_time error: {e}")
        return False

