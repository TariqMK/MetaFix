"""Loaded-file collection and timestamp-based renaming."""
from pathlib import Path
from .config import state
from .dates import _strip_tz
from .exiftool import run_exiftool

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

