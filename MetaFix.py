import sys, os, json, subprocess, threading, re
from pathlib import Path
from flask import Flask, request, jsonify, render_template
import webview
from webview.dom import DOMEventHandler

CONFIG = "config.json"
app = Flask(__name__)

MEDIA_EXTS = {
    ".jpg", ".jpeg", ".png", ".heic", ".mov", ".mp4",
    ".avi", ".webp", ".tiff", ".gif", ".m4v", ".mkv", ".3gp"
}

AVI_EXTS = {".avi"}

PHOTO_FIELDS = ["DateTimeOriginal", "CreateDate", "ModifyDate"]
VIDEO_FIELDS = ["CreateDate", "MediaCreateDate", "TrackCreateDate", "TrackModifyDate", "ModifyDate"]
ALL_DEST_FIELDS = list(dict.fromkeys(PHOTO_FIELDS + VIDEO_FIELDS))
COPY_SOURCE_FIELDS = ["DateTimeOriginal", "CreateDate", "ModifyDate",
                       "MediaCreateDate", "TrackCreateDate", "FileModifyDate", "FileCreateDate"]

state = {
    "files": [],
    "last_batch": [],
    "config": {}
}

# ── config ─────────────────────────────────────────────────────────────────────
def load_config():
    if os.path.exists(CONFIG):
        try:
            return json.load(open(CONFIG, "r", encoding="utf-8"))
        except:
            pass
    return {}

def save_config(cfg):
    json.dump(cfg, open(CONFIG, "w", encoding="utf-8"), indent=2)

state["config"] = load_config()

# ── exiftool helpers ───────────────────────────────────────────────────────────
def exiftool_path():
    p = state["config"].get("exiftool_path", "")
    if not p:
        raise Exception("ExifTool path not set.")
    return p

def run_exiftool(args):
    cmd = [exiftool_path()] + args
    result = subprocess.run(
        cmd,
        capture_output=True,
        encoding="utf-8",
        errors="replace"
    )
    return result

def normalise_path(p):
    return str(Path(p)).replace("\\", "/")

def _strip_tz(dt_str):
    if not dt_str or not isinstance(dt_str, str):
        return ""
    s = dt_str.strip()
    s = re.sub(r'[+-]\d{2}:\d{2}$', '', s).strip()
    s = re.sub(r'Z$', '', s).strip()
    return s

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
                        val = _strip_tz(item.get(key, ""))
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
                result[f] = {"value": "—", "field": ""}

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

def set_win_creation_time(filepath, dt_str):
    """Set Windows filesystem CreationTime via PowerShell.
    dt_str: ExifTool format '2024:06:01 14:32:09'
    Works for all file formats — no extra tools needed."""
    try:
        # Convert "2024:06:01 14:32:09" → "2024-06-01 14:32:09"
        win_dt = dt_str[:10].replace(":", "-") + dt_str[10:]
        ps_cmd = (
            f'$f = Get-Item -LiteralPath \'{filepath}\'; '
            f'$f.CreationTime = \'{win_dt}\'; '
            f'$f.LastWriteTime = \'{win_dt}\''
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True, encoding="utf-8", errors="replace"
        )
        if r.returncode != 0:
            print(f"PowerShell CreationTime error: {r.stderr.strip()}")
            return False
        return True
    except Exception as e:
        print(f"set_win_creation_time error: {e}")
        return False

# ── ffmpeg helpers ─────────────────────────────────────────────────────────────
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

# ── routes ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify({
        "exiftool_path": state["config"].get("exiftool_path", ""),
        "ffmpeg_path":   state["config"].get("ffmpeg_path", ""),
        "dest_fields": ALL_DEST_FIELDS,
        "copy_source_fields": COPY_SOURCE_FIELDS
    })

@app.route("/api/browse_exiftool", methods=["POST"])
def browse_exiftool():
    result = webview.windows[0].create_file_dialog(
        webview.OPEN_DIALOG,
        allow_multiple=False,
        file_types=("Executable files (*.exe)", "All files (*.*)")
    )
    if result:
        path = result[0]
        state["config"]["exiftool_path"] = path
        save_config(state["config"])
        return jsonify({"ok": True, "path": path})
    return jsonify({"ok": False})

@app.route("/api/browse_ffmpeg", methods=["POST"])
def browse_ffmpeg():
    result = webview.windows[0].create_file_dialog(
        webview.OPEN_DIALOG,
        allow_multiple=False,
        file_types=("Executable files (*.exe)", "All files (*.*)")
    )
    if result:
        path = result[0]
        state["config"]["ffmpeg_path"] = path
        save_config(state["config"])
        return jsonify({"ok": True, "path": path})
    return jsonify({"ok": False})

@app.route("/api/add_files", methods=["POST"])
def add_files():
    result = webview.windows[0].create_file_dialog(
        webview.OPEN_DIALOG,
        allow_multiple=True,
        file_types=(
            "Media files (*.jpg;*.jpeg;*.png;*.heic;*.mov;*.mp4;*.avi;*.webp;*.tiff;*.gif;*.m4v;*.mkv;*.3gp)",
            "All files (*.*)"
        )
    )
    if result:
        _add_paths(list(result))
    return jsonify({"files": _file_list()})

@app.route("/api/add_folder", methods=["POST"])
def add_folder():
    data = request.json or {}
    recursive = data.get("recursive", False)
    result = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
    if result:
        folder = Path(result[0])
        iterator = folder.rglob("*") if recursive else folder.glob("*")
        new_files = [str(p) for p in iterator if p.suffix.lower() in MEDIA_EXTS and p.is_file()]
        _add_paths(new_files)
    return jsonify({"files": _file_list()})

@app.route("/api/drop_files", methods=["POST"])
def drop_files():
    """Called by JS with paths gathered via the pywebview expose() bridge."""
    data = request.json or {}
    paths = data.get("paths", [])
    recursive = data.get("recursive", False)
    new_files = []
    for p in paths:
        if p.startswith("file:///"):
            p = p[8:].replace("/", os.sep)
        pp = Path(p)
        if pp.is_file() and pp.suffix.lower() in MEDIA_EXTS:
            new_files.append(str(pp))
        elif pp.is_dir():
            iterator = pp.rglob("*") if recursive else pp.glob("*")
            new_files.extend([str(f) for f in iterator
                               if f.suffix.lower() in MEDIA_EXTS and f.is_file()])
    _add_paths(new_files)
    return jsonify({"files": _file_list()})

@app.route("/api/remove_files", methods=["POST"])
def remove_files():
    data = request.json or {}
    to_remove = set(data.get("paths", []))
    state["files"] = [f for f in state["files"] if f not in to_remove]
    return jsonify({"files": _file_list()})

@app.route("/api/clear_files", methods=["POST"])
def clear_files():
    state["files"] = []
    return jsonify({"files": []})

@app.route("/api/read_metadata", methods=["POST"])
def read_metadata():
    data = request.json or {}
    files = data.get("files", state["files"])
    if not files:
        return jsonify({})
    meta = read_metadata_batch(files)
    return jsonify(meta)

@app.route("/api/preview", methods=["POST"])
def preview():
    data = request.json or {}
    mode = data.get("mode", "manual")
    selected = data.get("selected_paths", [])
    all_files = state["files"]
    # Use selected subset if provided, otherwise all
    files = [f for f in all_files if f in selected] if selected else all_files
    if not files:
        return jsonify({})

    previews = {}

    if mode == "manual":
        dt = data.get("datetime", "")
        for f in files:
            previews[f] = dt

    elif mode == "copy":
        src_field = data.get("source_field", "DateTimeOriginal")
        args = ["-j", f"-{src_field}"] + files
        try:
            r = run_exiftool(args)
            items = json.loads(r.stdout)
            norm_to_orig = {normalise_path(f): f for f in files}
            for item in items:
                src_raw = item.get("SourceFile", "")
                orig = (norm_to_orig.get(src_raw)
                        or norm_to_orig.get(normalise_path(src_raw))
                        or src_raw)
                val = _strip_tz(item.get(src_field, ""))
                previews[orig] = val or "— (field empty)"
        except Exception as e:
            print("preview copy error:", e)
            for f in files:
                previews[f] = "error"

    elif mode == "shift":
        years   = int(data.get("years",   0))
        months  = int(data.get("months",  0))
        days    = int(data.get("days",    0))
        hours   = int(data.get("hours",   0))
        minutes = int(data.get("minutes", 0))
        current = read_metadata_batch(files)
        for f in files:
            entry = current.get(f, {})
            cur = entry.get("value", "") if isinstance(entry, dict) else entry
            if cur and cur != "—":
                shifted = compute_shifted_dt(cur, years, months, days, hours, minutes)
                previews[f] = shifted or "parse error"
            else:
                previews[f] = "no date found"

    return jsonify(previews)

def _backup_dir(filepath):
    """Returns the BACKUPS folder path for a given file's directory."""
    return Path(filepath).parent / "BACKUPS"

def _move_to_backup(filepath):
    """Move ExifTool's _original sidecar into the BACKUPS folder."""
    sidecar = Path(str(filepath) + "_original")
    if not sidecar.exists():
        return None
    backup_dir = _backup_dir(filepath)
    backup_dir.mkdir(exist_ok=True)
    dest = backup_dir / Path(filepath).name
    # Avoid overwriting an older backup — add counter suffix
    counter = 1
    while dest.exists():
        dest = backup_dir / f"{Path(filepath).stem}({counter}){Path(filepath).suffix}"
        counter += 1
    sidecar.rename(dest)
    return str(dest)

@app.route("/api/apply", methods=["POST"])
def apply_changes():
    data = request.json or {}
    mode         = data.get("mode", "manual")
    dest_fields  = data.get("dest_fields", ALL_DEST_FIELDS)
    touch_fs     = data.get("touch_fs", True)
    win_creation = data.get("win_creation", False)
    do_rename    = data.get("rename", False)
    selected     = data.get("selected_paths", [])
    all_files    = state["files"]
    files = [f for f in all_files if f in set(selected)] if selected else all_files
    print(f"APPLY: {len(all_files)} total, {len(selected)} selected, {len(files)} to process")

    if not files:
        return jsonify({"error": "No files loaded"}), 400
    if not dest_fields:
        return jsonify({"error": "No destination fields selected"}), 400

    errors = []
    renamed = {}
    state["last_batch"] = list(files)

    for f in files:
        is_avi = Path(f).suffix.lower() in AVI_EXTS

        # ── AVI: use FFmpeg ───────────────────────────────────────────────────
        if is_avi:
            if not ffmpeg_available():
                errors.append(f"{Path(f).name}: AVI file requires FFmpeg — click 'set ffmpeg' in the titlebar")
                continue

            # Determine the datetime to write
            avi_dt = None
            if mode == "manual":
                avi_dt = data.get("datetime", "").strip()
                print(f"AVI manual dt: {repr(avi_dt)}")

            elif mode == "copy":
                # AVI has no EXIF fields — read whatever date is available via ffprobe
                # (the ExifTool source field selector is irrelevant for AVI)
                avi_dt = ffmpeg_read_creation_time(f)
                print(f"AVI copy: ffprobe returned {repr(avi_dt)}")
                if not avi_dt:
                    # last resort: try ExifTool read-only on the source field
                    src = data.get("source_field", "DateTimeOriginal")
                    try:
                        r = run_exiftool(["-j", f"-{src}", f])
                        items = json.loads(r.stdout)
                        if items:
                            avi_dt = _strip_tz(items[0].get(src, ""))
                            print(f"AVI copy: exiftool {src} returned {repr(avi_dt)}")
                    except Exception as e:
                        print(f"AVI copy exiftool fallback error: {e}")
                if not avi_dt:
                    errors.append(f"{Path(f).name}: no date found in AVI file to copy from — use Manual mode to set a specific date")
                    continue

            elif mode == "shift":
                years   = int(data.get("years",   0))
                months  = int(data.get("months",  0))
                days    = int(data.get("days",    0))
                hours   = int(data.get("hours",   0))
                minutes = int(data.get("minutes", 0))
                # Try ffprobe first for AVIs, then ExifTool batch
                cur_dt = ffmpeg_read_creation_time(f)
                print(f"AVI shift: ffprobe returned {repr(cur_dt)}")
                if not cur_dt:
                    cur_meta = read_metadata_batch([f])
                    entry = cur_meta.get(f, {})
                    cur_dt = entry.get("value", "") if isinstance(entry, dict) else entry
                    print(f"AVI shift: exiftool batch returned {repr(cur_dt)}")
                if not cur_dt or cur_dt == "—":
                    errors.append(f"{Path(f).name}: no date found in AVI to shift — use Manual mode")
                    continue
                avi_dt = compute_shifted_dt(cur_dt, years, months, days, hours, minutes)
                print(f"AVI shift: computed new dt {repr(avi_dt)}")
                if not avi_dt:
                    errors.append(f"{Path(f).name}: could not parse AVI date '{cur_dt}'")
                    continue

            if not avi_dt or not avi_dt.strip():
                errors.append(f"{Path(f).name}: no datetime to write (got empty value)")
                continue

            print(f"AVI writing dt={repr(avi_dt)} to {Path(f).name}")
            ok, err_msg = ffmpeg_write_creation_time(f, avi_dt)
            if not ok:
                errors.append(f"{Path(f).name}: {err_msg}")
            else:
                if win_creation:
                    set_win_creation_time(f, avi_dt)
                if do_rename:
                    new_path = _rename_file(f)
                    if new_path:
                        renamed[f] = new_path
            continue

        # ── All other formats: use ExifTool ──────────────────────────────────
        cmd = [exiftool_path(), "-m"]
        written_dt = None  # track the date we're writing for PowerShell

        if mode == "manual":
            dt = data.get("datetime", "")
            if not dt:
                return jsonify({"error": "No datetime provided"}), 400
            written_dt = dt
            for d in dest_fields:
                cmd.append(f"-{d}={dt}")
            if touch_fs:
                cmd.append(f"-FileModifyDate={dt}")

        elif mode == "copy":
            src = data.get("source_field", "DateTimeOriginal")
            cmd += ["-tagsFromFile", "@"]
            for d in dest_fields:
                if d != src:
                    cmd.append(f"-{d}<{src}")
            if touch_fs:
                cmd.append(f"-FileModifyDate<{src}")
            # Read the source value so we can pass it to PowerShell
            if win_creation:
                try:
                    r2 = run_exiftool(["-j", f"-{src}", f])
                    items2 = json.loads(r2.stdout)
                    if items2:
                        written_dt = _strip_tz(items2[0].get(src, ""))
                except Exception:
                    pass

        elif mode == "shift":
            years   = int(data.get("years",   0))
            months  = int(data.get("months",  0))
            days    = int(data.get("days",    0))
            hours   = int(data.get("hours",   0))
            minutes = int(data.get("minutes", 0))
            cur_meta = read_metadata_batch([f])
            entry = cur_meta.get(f, {})
            cur_dt = entry.get("value", "") if isinstance(entry, dict) else entry
            if not cur_dt or cur_dt == "—":
                errors.append(f"{Path(f).name}: no date found to shift")
                continue
            new_dt = compute_shifted_dt(cur_dt, years, months, days, hours, minutes)
            if not new_dt:
                errors.append(f"{Path(f).name}: could not parse date '{cur_dt}'")
                continue
            written_dt = new_dt
            for d in dest_fields:
                cmd.append(f"-{d}={new_dt}")
            if touch_fs:
                cmd.append(f"-FileModifyDate={new_dt}")

        cmd.append(f)

        print("CMD:", cmd)
        try:
            r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
            print("STDOUT:", r.stdout.strip())
            print("STDERR:", r.stderr.strip())
            err_text = exiftool_error(r)
            if r.returncode != 0 or (err_text and "error" in err_text.lower()):
                msg = err_text or f"exit code {r.returncode}"
                errors.append(f"{Path(f).name}: {msg}")
            else:
                _move_to_backup(f)
                if win_creation and written_dt:
                    set_win_creation_time(f, written_dt)
        except Exception as e:
            errors.append(f"{Path(f).name}: {str(e)}")

        if do_rename:
            new_path = _rename_file(f)
            if new_path:
                renamed[f] = new_path

    if renamed:
        state["files"] = [renamed.get(f, f) for f in state["files"]]

    return jsonify({
        "ok": True,
        "errors": errors,
        "renamed": renamed,
        "files": _file_list()
    })

@app.route("/api/undo", methods=["POST"])
def undo():
    """Restore files from their BACKUPS folder copies."""
    if not state["last_batch"]:
        return jsonify({"error": "Nothing to undo"}), 400
    errors = []
    for f in state["last_batch"]:
        backup_dir = _backup_dir(f)
        backup_copy = backup_dir / Path(f).name
        if backup_copy.exists():
            try:
                import shutil
                shutil.copy2(str(backup_copy), f)
            except Exception as e:
                errors.append(f"{Path(f).name}: {e}")
        else:
            errors.append(f"{Path(f).name}: no backup found in BACKUPS folder")
    state["last_batch"] = []
    return jsonify({"ok": True, "errors": errors})

@app.route("/api/cleanup_backups", methods=["POST"])
def cleanup_backups():
    """Delete BACKUPS folders for all directories containing loaded files."""
    import shutil
    deleted_dirs = []
    errors = []
    # Collect unique parent directories
    dirs = set(Path(f).parent for f in (state["files"] + state["last_batch"]))
    for d in dirs:
        backup_dir = d / "BACKUPS"
        if backup_dir.exists() and backup_dir.is_dir():
            try:
                shutil.rmtree(str(backup_dir))
                deleted_dirs.append(str(backup_dir))
            except Exception as e:
                errors.append(f"{backup_dir}: {e}")
    state["last_batch"] = []
    return jsonify({
        "ok": True,
        "deleted_dirs": deleted_dirs,
        "count": len(deleted_dirs),
        "errors": errors
    })

# ── helpers ────────────────────────────────────────────────────────────────────
def _add_paths(new_files):
    existing = set(state["files"])
    for f in new_files:
        if f not in existing:
            state["files"].append(f)
            existing.add(f)

def _file_list():
    return [{"path": f, "name": Path(f).name} for f in state["files"]]

def _rename_file(filepath):
    try:
        r = run_exiftool(["-s3", "-DateTimeOriginal", filepath])
        value = r.stdout.strip()
        if not value:
            r = run_exiftool(["-s3", "-CreateDate", filepath])
            value = r.stdout.strip()
        if not value:
            return None
        value = _strip_tz(value)
        stamp = value[:10].replace(":", "-") + "_" + value[11:19].replace(":", "-")
        p = Path(filepath)
        new = p.parent / f"{stamp}_{p.name}"
        counter = 1
        while new.exists():
            new = p.parent / f"{stamp}_{p.stem}({counter}){p.suffix}"
            counter += 1
        p.rename(new)
        return str(new)
    except:
        return None

# ── drag/drop ──────────────────────────────────────────────────────────────────
# pywebviewFullPath is ONLY available on the Python side inside DOMEventHandler.
# It is never exposed to JS File objects. Two key names exist across versions:
#   pywebview >= 5.0 : event['dataTransfer']['files'][i]['pywebviewFullPath']
#   pywebview  < 5.0 : event['domTransfer']['files'][i]['pywebviewFullPath']
_window = None

def on_drop(e):
    try:
        print("DROP EVENT keys:", list(e.keys()))
        # Try both key names across pywebview versions
        files = (e.get("dataTransfer") or e.get("domTransfer") or {}).get("files", [])
        print(f"DROP files count: {len(files)}")
        if not files:
            print("DROP: no files in event")
            return
        print("DROP first file keys:", list(files[0].keys()) if files else "none")
        paths = [f.get("pywebviewFullPath", "") for f in files]
        paths = [p for p in paths if p]
        # pywebview Qt on Windows returns "/D:/path/file" — strip the leading slash
        # Detect: starts with /X: where X is a drive letter
        paths = [p[1:] if (len(p) >= 3 and p[0] == "/" and p[2] == ":") else p for p in paths]
        print("DROP paths:", paths)
        if not paths:
            return
        new_files = []
        for p in paths:
            pp = Path(p)
            if pp.is_file() and pp.suffix.lower() in MEDIA_EXTS:
                new_files.append(str(pp))
            elif pp.is_dir():
                new_files.extend([str(f) for f in pp.glob("*")
                                   if f.suffix.lower() in MEDIA_EXTS and f.is_file()])
        _add_paths(new_files)
        safe = json.dumps(_file_list())
        _window.evaluate_js(f"window.receiveDropResult({safe})")
    except Exception as ex:
        print("DROP ERROR:", ex)
        import traceback; traceback.print_exc()

def bind(window):
    global _window
    _window = window
    try:
        window.dom.document.events.dragover  += DOMEventHandler(lambda e: None, True, True, debounce=50)
        window.dom.document.events.dragenter += DOMEventHandler(
            lambda e: _window.evaluate_js("window.showDropOverlay()"), True, True)
        window.dom.document.events.dragleave += DOMEventHandler(
            lambda e: _window.evaluate_js("window.hideDropOverlay()"), True, True)
        window.dom.document.events.drop      += DOMEventHandler(on_drop, True, True)
        print("pywebview DOM drop handlers registered OK")
    except Exception as ex:
        print(f"WARNING: Could not register DOM drop handlers: {ex}")

def start_server():
    app.run(port=5050, debug=False, use_reloader=False)

if __name__ == "__main__":
    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    win = webview.create_window(
        "MetaFix",
        "http://127.0.0.1:5050",
        width=1200,
        height=820,
        resizable=True,
        background_color="#0f0f0f",
    )
    webview.start(bind, win, gui="qt")
