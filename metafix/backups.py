"""Backup placement, restoration, and cleanup."""
from pathlib import Path
from .config import state

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

