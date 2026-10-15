"""Validated media collection and timestamp renaming."""
import os
from pathlib import Path
from .config import state
from .fields import MEDIA_EXTS
from .dates import format_datetime


def is_backup_path(path):
    return any(part.casefold() == 'backups' for part in Path(path).parts)


def collect_paths(paths, recursive=False):
    found = []
    for value in paths:
        if not isinstance(value, (str, Path)) or any(c in str(value) for c in ('\n', '\r')):
            raise ValueError('Invalid media path')
        path = Path(value).expanduser().resolve()
        if is_backup_path(path):
            continue
        if path.is_file() and path.suffix.lower() in MEDIA_EXTS:
            found.append(str(path))
        elif path.is_dir():
            for directory, folders, filenames in os.walk(path, followlinks=False):
                folders[:] = [name for name in folders if name.casefold() != 'backups'
                              and not (Path(directory) / name).is_symlink()]
                for name in filenames:
                    file = Path(directory) / name
                    if file.suffix.lower() in MEDIA_EXTS and not file.is_symlink():
                        found.append(str(file.resolve()))
                if not recursive:
                    break
    return found


def _add_paths(new_files):
    existing = {os.path.normcase(str(Path(f).resolve())) for f in state['files']}
    for file in collect_paths(new_files):
        key = os.path.normcase(file)
        if key not in existing:
            state['files'].append(file)
            existing.add(key)


def _file_list():
    return [{'path': f, 'name': Path(f).name} for f in state['files']]


def _rename_file(filepath, datetime_value):
    stamp = format_datetime(datetime_value, include_offset=False).replace(':', '-', 2)
    stamp = stamp.replace(' ', '_').replace(':', '-')
    path = Path(filepath)
    target = path.with_name(f'{stamp}_{path.name}')
    counter = 1
    while target.exists():
        target = path.with_name(f'{stamp}_{path.stem}({counter}){path.suffix}')
        counter += 1
    # Exclusive hard-link creation avoids overwriting a file that appears after
    # the existence check. Both paths are on the same filesystem/directory.
    os.link(path, target)
    try:
        path.unlink()
    except Exception:
        target.unlink()
        raise
    return str(target)
