"""Native desktop window, server lifecycle, and drag-and-drop bridge."""
import json
from pathlib import Path
import threading
import webview
from webview.dom import DOMEventHandler
from . import create_app
from werkzeug.serving import make_server

_window = None

def on_drop(e):
    try:
        if _window.evaluate_js("window.metafixBusy === true"):
            _window.evaluate_js("window.hideDropOverlay()")
            return
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
        # Let the guarded UI action submit paths through the serialized API.
        # Native callbacks never mutate session state independently of the UI.
        safe = json.dumps(paths)
        _window.evaluate_js(f"window.receiveNativeDrop({safe})")
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



def start_server(server):
    server.serve_forever()


def main():
    app = create_app()
    # Bind before opening the window, with a separate port for each instance.
    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=start_server, args=(server,), daemon=True)
    thread.start()
    try:
        win = webview.create_window(
            'MetaFix', f'http://127.0.0.1:{server.server_port}',
            width=1200, height=820, resizable=True, background_color='#0f0f0f',
        )
        icon = Path(__file__).resolve().parent / 'assets/icon.png'
        if not icon.is_file():
            icon = Path(__file__).resolve().parent.parent / 'docs/assets/icon.png'
        webview.start(bind, win, gui='qt', icon=str(icon))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
