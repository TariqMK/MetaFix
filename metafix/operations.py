"""Validated, serialized media batches with exact backup records."""
from pathlib import Path
from .config import state
from .fields import ALL_DEST_FIELDS, AVI_EXTS, COPY_SOURCE_FIELDS
from .dates import format_datetime, compute_shifted_dt, set_win_creation_time
from .metadata import read_metadata_batch, read_source_datetime
from .exiftool import run_exiftool_write, exiftool_error
from .ffmpeg import ffmpeg_available, ffmpeg_write_creation_time
from .backups import create_backup, fingerprint, save_record, restore_record, owned_records, delete_record
from .files import _file_list, _rename_file, is_backup_path
from .session import exclusive


def _validate(data):
    if not isinstance(data, dict):
        raise ValueError('Request must be a JSON object')
    mode = data.get('mode', 'manual')
    if mode not in ('manual', 'copy', 'shift'):
        raise ValueError('Unknown edit mode')
    selected = data.get('selected_paths', [])
    if not isinstance(selected, list) or any(not isinstance(p, str) for p in selected):
        raise ValueError('Selected paths must be a list of strings')
    loaded = tuple(state['files'])
    if any(p not in loaded for p in selected):
        raise ValueError('Selection contains files that are no longer loaded')
    files = tuple(f for f in loaded if not selected or f in set(selected))
    if not files:
        raise ValueError('No files loaded')
    for file in files:
        if any(c in file for c in ('\n', '\r')) or is_backup_path(file) or not Path(file).is_file() or Path(file).is_symlink():
            raise ValueError(f'Unsafe or missing media path: {file}')
    dest = data.get('dest_fields', ALL_DEST_FIELDS)
    if (not isinstance(dest, list) or not dest
            or any(not isinstance(f, str) or f not in ALL_DEST_FIELDS for f in dest)):
        raise ValueError('Select valid destination fields')
    for option in ('touch_fs', 'win_creation', 'rename'):
        if option in data and not isinstance(data[option], bool):
            raise ValueError(f'{option} must be true or false')
    source = data.get('source_field', 'DateTimeOriginal')
    if not isinstance(source, str) or source not in COPY_SOURCE_FIELDS:
        raise ValueError('Invalid copy source field')
    offsets = {}
    for key in ('years', 'months', 'days', 'hours', 'minutes'):
        value = data.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int) or abs(value) > 100000:
            raise ValueError(f'{key} must be an integer between -100000 and 100000')
        offsets[key] = value
    manual = format_datetime(data.get('datetime', ''), include_offset=False) if mode == 'manual' else None
    if any(Path(f).suffix.lower() in AVI_EXTS for f in files) and not ffmpeg_available():
        raise ValueError('AVI editing requires FFmpeg')
    return files, mode, dest, source, offsets, manual


def _plan(data):
    files, mode, dest, source, offsets, manual = _validate(data)
    current = read_metadata_batch(files) if mode == 'shift' else {}
    plan, errors = {}, {}
    for file in files:
        try:
            if mode == 'manual':
                value = manual
            elif mode == 'copy':
                value = format_datetime(read_source_datetime(file, source), include_offset=False)
            else:
                value = compute_shifted_dt(current.get(file, {}).get('value', ''), **offsets)
                if value is None:
                    raise ValueError('No valid date available to shift')
            plan[file] = value
        except (ValueError, OSError, RuntimeError) as exc:
            errors[file] = str(exc)
    if errors:
        return None, {'error': 'Batch validation failed; no files changed', 'file_errors': errors}
    return (files, dest, plan), None


@exclusive
def preview(data):
    try:
        plan, error = _plan(data)
        if error:
            return error, 400
        return plan[2]
    except (ValueError, TypeError) as exc:
        return {'error': str(exc)}, 400


@exclusive
def apply_changes(data):
    try:
        planned, error = _plan(data)
        if error:
            return error, 400
    except (ValueError, TypeError) as exc:
        return {'error': str(exc)}, 400
    files, dest_fields, plan = planned
    results, renamed, records = {}, {}, []
    for file in files:
        record = None
        written = False
        try:
            record = create_backup(file)
            value = plan[file]
            if Path(file).suffix.lower() in AVI_EXTS:
                ok, message = ffmpeg_write_creation_time(file, value)
                if not ok:
                    raise RuntimeError(message)
            else:
                # A verified backup exists before every write, including filesystem-only edits.
                args = ['-overwrite_original'] + [f'-{field}={value}' for field in dest_fields]
                if data.get('touch_fs', True):
                    args.append(f'-FileModifyDate={value}')
                result = run_exiftool_write(args + [file])
                message = exiftool_error(result)
                if result.returncode or (message and 'error' in message.lower()):
                    raise RuntimeError(message or f'ExifTool exit {result.returncode}')
            written = True
            # Capture modification before optional stages so failed post-processing is undoable.
            record['after_hash'] = fingerprint(file)
            save_record(record)
            records.append(record)
            problems = []
            if data.get('win_creation', False):
                try:
                    set_win_creation_time(file, value)
                except Exception as exc:
                    problems.append(str(exc))
            if data.get('rename', False):
                try:
                    new_path = _rename_file(file, value)
                    record['current'] = new_path
                    renamed[file] = new_path
                    save_record(record)
                except Exception as exc:
                    problems.append(f'Rename failed: {exc}')
            results[file] = {'ok': not problems, 'current': record['current'], 'error': '; '.join(problems)}
        except Exception as exc:
            # A tool can return an error after a partial write. Preserve a recovery
            # record in that case; unchanged failures do not replace the undo batch.
            if record and not written and Path(file).exists():
                try:
                    record['after_hash'] = fingerprint(file)
                    if record['after_hash'] != record['before_hash']:
                        save_record(record)
                        records.append(record)
                except OSError:
                    pass
            elif record and written and record not in records:
                records.append(record)
            results[file] = {'ok': False, 'current': file, 'error': str(exc)}
    if records:
        state['last_batch'] = records
    state['files'] = [renamed.get(f, f) for f in state['files']]
    return {'ok': all(r['ok'] for r in results.values()), 'results': results,
            'errors': [f"{p}: {r['error']}" for p, r in results.items() if not r['ok']],
            'renamed': renamed, 'files': _file_list(), 'can_undo': bool(state['last_batch'])}


@exclusive
def undo():
    if not state['last_batch']:
        return {'error': 'Nothing to undo'}, 400
    pending, errors, renamed = [], {}, {}
    for record in tuple(state['last_batch']):
        try:
            restore_record(record)
            renamed[record['current']] = record['original']
        except Exception as exc:
            pending.append(record)
            errors[record['current']] = str(exc)
    state['last_batch'] = pending
    state['files'] = [renamed.get(f, f) for f in state['files']]
    return {'ok': not errors, 'file_errors': errors, 'errors': list(errors.values()),
            'renamed': renamed, 'files': _file_list(), 'can_undo': bool(pending)}


@exclusive
def cleanup_backups(data=None):
    data = data or {}
    if not isinstance(data, dict):
        return {'error': 'Request must be a JSON object'}, 400
    parents = [Path(f).parent for f in state['files']]
    parents += [Path(r['original']).parent for r in state['last_batch']]
    records = owned_records(parents)
    paths = sorted(r['backup'] for r in records)
    # Requiring the displayed list protects against backups created since confirmation.
    if data.get('confirm_paths') != paths:
        return {'backups': paths, 'count': len(paths), 'confirmation_required': True}
    errors, deleted = {}, []
    for record in records:
        try:
            delete_record(record)
            deleted.append(record['backup'])
        except Exception as exc:
            errors[record['backup']] = str(exc)
            if not Path(record['backup']).exists():
                deleted.append(record['backup'])
    state['last_batch'] = [r for r in state['last_batch'] if r['backup'] not in deleted]
    return {'ok': not errors, 'count': len(deleted), 'errors': list(errors.values()),
            'can_undo': bool(state['last_batch'])}
