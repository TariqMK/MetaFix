"""Launch MetaFix using the existing desktop shortcut or batch file."""
import sys
from metafix.desktop import main


if __name__ == "__main__":
    if '--smoke-test' in sys.argv:
        from metafix import create_app, __version__
        client = create_app().test_client()
        for url in ('/', '/api/config', '/static/css/app.css', '/static/js/app.js'):
            if client.get(url).status_code != 200:
                raise SystemExit(1)
        import webview.platforms.qt
        if '--expect-version' in sys.argv:
            expected = sys.argv[sys.argv.index('--expect-version') + 1]
            if __version__ != expected:
                raise SystemExit(1)
    else:
        main()
