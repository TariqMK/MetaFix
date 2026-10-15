"""Preview, apply, undo, and cleanup workflows, independent of HTTP."""
import json
from pathlib import Path
from .config import state
from .fields import ALL_DEST_FIELDS, AVI_EXTS
from .dates import _strip_tz, compute_shifted_dt, set_win_creation_time
from .metadata import normalise_path, read_metadata_batch
from .exiftool import run_exiftool, run_exiftool_write, exiftool_error
from .ffmpeg import ffmpeg_available, ffmpeg_read_creation_time, ffmpeg_write_creation_time
from .backups import _backup_dir, _move_to_backup
from .files import _file_list, _rename_file


def preview(data):
    mode = data.get("mode", "manual")
    selected = data.get("selected_paths", [])
    all_files = state["files"]
    # Use selected subset if provided, otherwise all
    files = [f for f in all_files if f in selected] if selected else all_files
    if not files:
        return {}

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

    return previews


def apply_changes(data):
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
        return {"error": "No files loaded"}, 400
    if not dest_fields:
        return {"error": "No destination fields selected"}, 400

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
        write_args = []
        written_dt = None

        if mode == "manual":
            dt = data.get("datetime", "")
            if not dt:
                return {"error": "No datetime provided"}, 400
            written_dt = dt
            for d in dest_fields:
                write_args.append(f"-{d}={dt}")
            if touch_fs:
                write_args.append(f"-FileModifyDate={dt}")

        elif mode == "copy":
            src = data.get("source_field", "DateTimeOriginal")
            write_args += ["-tagsFromFile", "@"]
            for d in dest_fields:
                if d != src:
                    write_args.append(f"-{d}<{src}")
            if touch_fs:
                write_args.append(f"-FileModifyDate<{src}")
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
                write_args.append(f"-{d}={new_dt}")
            if touch_fs:
                write_args.append(f"-FileModifyDate={new_dt}")

        write_args.append(f)

        print("WRITE ARGS:", write_args)
        try:
            r = run_exiftool_write(write_args)
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

    return {
        "ok": True,
        "errors": errors,
        "renamed": renamed,
        "files": _file_list()
    }


def undo():
    """Restore files from their BACKUPS folder copies."""
    if not state["last_batch"]:
        return {"error": "Nothing to undo"}, 400
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
    return {"ok": True, "errors": errors}


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
    return {
        "ok": True,
        "deleted_dirs": deleted_dirs,
        "count": len(deleted_dirs),
        "errors": errors
    }

