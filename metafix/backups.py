"""Owned, individually tracked backups; never remove arbitrary BACKUPS contents."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from .config import APP_DIR

OWNER = 'MetaFix-backup-v2'
LEGACY_OWNER = 'MetaFix-backup-v1'
RECORDS_DIR = APP_DIR / 'data' / 'backup-records'


def fingerprint(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _backup_dir(filepath):
    return Path(filepath).parent / 'BACKUPS'


def create_backup(filepath):
    source = Path(filepath).resolve()
    folder = _backup_dir(source)
    if folder.is_symlink():
        raise ValueError('Backup directory must not be a symbolic link')
    folder.mkdir(exist_ok=True)
    source_hash = fingerprint(source)
    backup = folder / source.name
    counter = 1
    # Exclusive creation protects older backups and concurrent external files.
    while True:
        try:
            target = backup.open('xb')
            break
        except FileExistsError:
            backup = folder / f'{source.stem}({counter}){source.suffix}'
            counter += 1
    record = None
    try:
        with target, source.open('rb') as original:
            shutil.copyfileobj(original, target)
        shutil.copystat(source, backup)
        if fingerprint(backup) != source_hash:
            raise ValueError('Media changed while it was being backed up; no write attempted')
        record = {'owner': OWNER, 'record_id': uuid.uuid4().hex,
                  'original': str(source), 'current': str(source),
                  'backup': str(backup), 'before_hash': source_hash}
        save_record(record)
        return record
    except Exception:
        target.close()
        backup.unlink(missing_ok=True)
        if record:
            _record_path(record).unlink(missing_ok=True)
        raise


def _record_path(record):
    if record.get('owner') == LEGACY_OWNER:
        return Path(record['backup']).parent / 'record.json'
    identifier = record.get('record_id', '')
    if len(identifier) != 32 or any(c not in '0123456789abcdef' for c in identifier):
        raise ValueError('Invalid backup record identifier')
    return RECORDS_DIR / f'{identifier}.json'


def save_record(record):
    # Bookkeeping stays in the app's data directory, not beside backup media.
    target = _record_path(record)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix='.record-', dir=target.parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as stream:
            json.dump(record, stream, indent=2)
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)


def owned_records(parents):
    roots = {Path(parent).resolve() / 'BACKUPS' for parent in parents}
    manifests = list(RECORDS_DIR.glob('*.json')) if RECORDS_DIR.is_dir() else []
    # Keep old tracked backups usable; do not move existing media automatically.
    for root in roots:
        legacy = root / '.metafix'
        if not root.is_symlink() and not legacy.is_symlink():
            manifests.extend(legacy.glob('*/record.json'))
    records = []
    for manifest in manifests:
        try:
            record = json.loads(manifest.read_text(encoding='utf-8'))
            backup = Path(record['backup'])
            if record.get('owner') == OWNER:
                valid = backup.parent in roots and _record_path(record).resolve() == manifest.resolve()
                containers = (backup.parent,)
            elif record.get('owner') == LEGACY_OWNER:
                valid = (backup.parent.parent.parent in roots
                         and backup.parent.parent.name == '.metafix'
                         and backup.parent.resolve() == manifest.parent.resolve())
                containers = (backup.parent, backup.parent.parent, backup.parent.parent.parent)
            else:
                continue
            if (valid and not backup.is_symlink() and not any(p.is_symlink() for p in containers)
                    and backup.is_file() and fingerprint(backup) == record['before_hash']):
                records.append(record)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            continue
    return records


def restore_record(record):
    original, current, backup = map(Path, (record['original'], record['current'], record['backup']))
    if fingerprint(backup) != record['before_hash']:
        raise ValueError('Backup contents have changed; refusing to restore')
    if not current.exists() or fingerprint(current) != record['after_hash']:
        raise ValueError('File changed or moved after apply; refusing to overwrite it')
    if original != current:
        # Exclusive creation protects another file that now occupies the old name.
        with original.open('xb') as target:
            try:
                with backup.open('rb') as source:
                    shutil.copyfileobj(source, target)
            except Exception:
                target.close()
                original.unlink()
                raise
        try:
            shutil.copystat(backup, original)
            current.unlink()
        except Exception:
            original.unlink()
            raise
    else:
        handle, name = tempfile.mkstemp(prefix='.metafix-restore-', dir=current.parent)
        os.close(handle)
        try:
            shutil.copy2(backup, name)
            os.replace(name, current)
        finally:
            Path(name).unlink(missing_ok=True)


def delete_record(record):
    backup = Path(record['backup'])
    backup.unlink()
    _record_path(record).unlink(missing_ok=True)
    if record.get('owner') == LEGACY_OWNER:
        directories = (backup.parent, backup.parent.parent, backup.parent.parent.parent)
    else:
        directories = (backup.parent,)
    # Never recursively delete a folder, or remove the original media directory.
    for directory in directories:
        try:
            directory.rmdir()
        except OSError:
            break
