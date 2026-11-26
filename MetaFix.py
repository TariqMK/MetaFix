"""Start MetaFix. With --self-test, check the app's files and Qt load, print the version and exit."""
import sys


def _say(text):
    # A windowed Windows build has no console, so sys.stdout can be None.
    if sys.stdout:
        print(text, flush=True)


def self_test():
    """Check everything a build could be missing, without showing a window or writing files.

    Prints 'MetaFix vX.Y.Z' as the last line and exits 0, or prints what failed and exits 1.
    --expect-version X.Y.Z also fails when the built-in version is different.
    """
    problems = []
    try:
        from metafix import create_app, __version__
        client = create_app().test_client()
        for url in ('/', '/api/config', '/static/css/app.css', '/static/js/app.js'):
            status = client.get(url).status_code
            if status != 200:
                problems.append(f'{url} returned {status}')
    except Exception as exc:
        problems.append(f'App files: {exc}')
        __version__ = '?'
    try:
        import webview.platforms.qt  # Loads Qt and Qt WebEngine with their native libraries.
    except Exception as exc:
        problems.append(f'Qt WebEngine: {exc}')
    if '--expect-version' in sys.argv:
        expected = sys.argv[sys.argv.index('--expect-version') + 1]
        if __version__ != expected:
            problems.append(f'Version is {__version__}, expected {expected}')
    for problem in problems:
        _say(f'Self-test failed: {problem}')
    _say(f'MetaFix v{__version__}')
    return 1 if problems else 0


if __name__ == '__main__':
    # --smoke-test is the old name, kept so existing scripts still work.
    if '--self-test' in sys.argv or '--smoke-test' in sys.argv:
        raise SystemExit(self_test())
    from metafix.desktop import main
    main()
