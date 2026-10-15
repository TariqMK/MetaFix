"""Owned, individually tracked backups; never remove arbitrary BACKUPS contents."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

OWNER = 'MetaFix-backup-v1'


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
    backup_root = _backup_dir(source)
    owned = backup_root / '.metafix'
    if backup_root.is_symlink() or owned.is_symlink():
        raise ValueError('Backup directory must not be a symbolic link')
    folder = owned / uuid.uuid4().hex
    folder.mkdir(parents=True)
    backup = folder / source.name
    try:
        source_hash = fingerprint(source)
        shutil.copy2(source, backup)
        if fingerprint(backup) != source_hash:
            raise ValueError('Media changed while it was being backed up; no write attempted')
        record = {'owner': OWNER, 'original': str(source), 'current': str(source),
                  'backup': str(backup), 'before_hash': source_hash}
        save_record(record)
        return record
    except Exception:
        backup.unlink(missing_ok=True)
        (folder / 'record.json').unlink(missing_ok=True)
        folder.rmdir()
        raise


def save_record(record):
    target = Path(record['backup']).parent / 'record.json'
    target.write_text(json.dumps(record, indent=2), encoding='utf-8')


def owned_records(parents):
    records = []
    for parent in set(map(Path, parents)):
        root = parent / 'BACKUPS' / '.metafix'
        if root.is_symlink() or root.parent.is_symlink() or not root.is_dir():
            continue
        for manifest in root.glob('*/record.json'):
            try:
                record = json.loads(manifest.read_text(encoding='utf-8'))
                backup = Path(record['backup'])
                if (record.get('owner') == OWNER and not manifest.parent.is_symlink()
                        and not backup.is_symlink() and backup.parent.resolve() == manifest.parent.resolve()
                        and backup.exists() and fingerprint(backup) == record['before_hash']):
                    records.append(record)
            except (OSError, ValueError, TypeError, KeyError):
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
    manifest = backup.parent / 'record.json'
    manifest.unlink()
    # Only remove empty directories, never recursively delete a directory.
    for directory in (backup.parent, backup.parent.parent, backup.parent.parent.parent):
        try:
            directory.rmdir()
        except OSError:
            break
