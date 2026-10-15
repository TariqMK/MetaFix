"""HTTP interface and native file-picker endpoints."""
import os
from pathlib import Path
import webview
from flask import Blueprint, request, jsonify, render_template
from .config import state, save_config
from .fields import MEDIA_EXTS, ALL_DEST_FIELDS, COPY_SOURCE_FIELDS
from .metadata import read_metadata_batch
from .files import _add_paths, _file_list
from . import operations

routes = Blueprint("metafix", __name__)


@routes.route("/")
def index():
    return render_template("index.html")


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
    result = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
    if result:
        folder = Path(result[0])
        iterator = folder.rglob("*") if recursive else folder.glob("*")
        new_files = [str(p) for p in iterator if p.suffix.lower() in MEDIA_EXTS and p.is_file()]
        _add_paths(new_files)
    return jsonify({"files": _file_list()})


@routes.route("/api/drop_files", methods=["POST"])
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


@routes.route("/api/remove_files", methods=["POST"])
def remove_files():
    data = request.json or {}
    to_remove = set(data.get("paths", []))
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
    result = operations.cleanup_backups()
    if isinstance(result, tuple):
        payload, status = result
        return jsonify(payload), status
    return jsonify(result)
