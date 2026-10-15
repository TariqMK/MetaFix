"""HTTP interface and native file-picker endpoints."""
import webview
from flask import Blueprint, request, jsonify, render_template, g
from .config import state, save_config
from .fields import ALL_DEST_FIELDS, COPY_SOURCE_FIELDS
from .metadata import read_metadata_batch
from .files import _add_paths, _file_list, collect_paths
from .session import session_lock
from . import operations, __version__

routes = Blueprint("metafix", __name__)


@routes.route("/")
def index():
    return render_template("index.html", app_version=__version__)


@routes.route("/api/config", methods=["GET"])
def get_config():
    return jsonify({
        "exiftool_path": state["config"].get("exiftool_path", ""),
        "ffmpeg_path":   state["config"].get("ffmpeg_path", ""),
        "dest_fields": ALL_DEST_FIELDS,
        "copy_source_fields": COPY_SOURCE_FIELDS
    })


@routes.route("/api/browse_exiftool", methods=["POST"])
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


@routes.route("/api/browse_ffmpeg", methods=["POST"])
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


@routes.route("/api/add_files", methods=["POST"])
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


@routes.route("/api/add_folder", methods=["POST"])
def add_folder():
    data = request.json or {}
    recursive = data.get("recursive", False)
    if not isinstance(recursive, bool):
        return jsonify({'error': 'recursive must be true or false'}), 400
    result = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
    if result:
        _add_paths(collect_paths([result[0]], recursive=recursive))
    return jsonify({"files": _file_list()})


@routes.route("/api/drop_files", methods=["POST"])
def drop_files():
    """Called by JS with paths received from the native DOM drop callback."""
    data = request.json or {}
    paths = data.get("paths", [])
    if not isinstance(paths, list) or any(not isinstance(p, str) or '\n' in p or '\r' in p for p in paths):
        return jsonify({'error': 'paths must be a list of valid paths'}), 400
    recursive = data.get("recursive", False)
    if not isinstance(recursive, bool):
        return jsonify({'error': 'recursive must be true or false'}), 400
    _add_paths(collect_paths(paths, recursive=recursive))
    return jsonify({"files": _file_list()})


@routes.route("/api/remove_files", methods=["POST"])
def remove_files():
    data = request.json or {}
    paths = data.get('paths', [])
    if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
        return jsonify({'error': 'paths must be a list of strings'}), 400
    to_remove = set(paths)
    state["files"] = [f for f in state["files"] if f not in to_remove]
    return jsonify({"files": _file_list()})


@routes.route("/api/clear_files", methods=["POST"])
def clear_files():
    state["files"] = []
    return jsonify({"files": []})


@routes.route("/api/read_metadata", methods=["POST"])
def read_metadata():
    data = request.json or {}
    files = data.get("files", state["files"])
    if not isinstance(files, list) or any(not isinstance(f, str) or f not in state['files'] for f in files):
        return jsonify({'error': 'Metadata paths must be loaded files'}), 400
    if not files:
        return jsonify({})
    meta = read_metadata_batch(files)
    return jsonify(meta)


@routes.route("/api/preview", methods=["POST"])
def preview():
    result = operations.preview(request.json or {})
    if isinstance(result, tuple):
        payload, status = result
        return jsonify(payload), status
    return jsonify(result)

@routes.route("/api/apply", methods=["POST"])
def apply_changes():
    result = operations.apply_changes(request.json or {})
    if isinstance(result, tuple):
        payload, status = result
        return jsonify(payload), status
    return jsonify(result)

@routes.route("/api/undo", methods=["POST"])
def undo():
    result = operations.undo()
    if isinstance(result, tuple):
        payload, status = result
        return jsonify(payload), status
    return jsonify(result)

@routes.route("/api/cleanup_backups", methods=["POST"])
def cleanup_backups():
    result = operations.cleanup_backups(request.json or {})
    if isinstance(result, tuple):
        payload, status = result
        return jsonify(payload), status
    return jsonify(result)


@routes.before_request
def lock_session():
    if not request.path.startswith('/api/'):
        return None
    if request.method == 'POST' and not isinstance(request.get_json(silent=True), dict):
        return jsonify({'error': 'Request must be a JSON object'}), 400
    if not session_lock.acquire(blocking=False):
        return jsonify({'error': 'Another operation is in progress'}), 409
    g.metafix_locked = True


@routes.teardown_request
def unlock_session(error):
    if getattr(g, 'metafix_locked', False):
        g.metafix_locked = False
        session_lock.release()
