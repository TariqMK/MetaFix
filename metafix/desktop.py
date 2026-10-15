"""Native desktop window, server lifecycle, and drag-and-drop bridge."""
import json
import threading
from pathlib import Path
import webview
from webview.dom import DOMEventHandler
from . import create_app
from .fields import MEDIA_EXTS
from .files import _add_paths, _file_list

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



def start_server(app):
    app.run(port=5050, debug=False, use_reloader=False)


def main():
    app = create_app()
    t = threading.Thread(target=start_server, args=(app,), daemon=True)
    t.start()
    win = webview.create_window(
        "MetaFix", "http://127.0.0.1:5050",
        width=1200, height=820, resizable=True, background_color="#0f0f0f",
    )
    webview.start(bind, win, gui="qt")
