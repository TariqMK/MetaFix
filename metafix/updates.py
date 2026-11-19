"""Manual update check: asks GitHub for the latest MetaFix release when the user clicks the button."""
import json
import re
import urllib.request
import webbrowser

LATEST_URL = "https://api.github.com/repos/TariqMK/MetaFix/releases/latest"
RELEASES_PREFIX = "https://github.com/TariqMK/MetaFix/releases/"
TIMEOUT_SECONDS = 8

# The release page found by the last check. Only this URL can be opened.
_last_release_url = None


def parse_version(text):
    """Return (major, minor, patch) from 'v1.2.3' or '1.2.3+dev', or None."""
    match = re.match(r"v?(\d+)\.(\d+)\.(\d+)", (text or "").strip())
    return tuple(int(part) for part in match.groups()) if match else None


def fetch_latest():
    """Send one GET to GitHub. Nothing about the user or their files is sent."""
    request = urllib.request.Request(LATEST_URL, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "MetaFix",
    })
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.load(response)


def check(current_version, fetch=None):
    global _last_release_url
    _last_release_url = None
    try:
        # Look up fetch_latest at call time, so tests can replace it and stay offline.
        release = (fetch or fetch_latest)()
    except Exception as error:
        raise ValueError("Could not reach GitHub to check for updates. Check your connection and try again.") from error
    latest = parse_version(release.get("tag_name"))
    url = release.get("html_url") or ""
    if latest is None or not url.startswith(RELEASES_PREFIX):
        raise ValueError("GitHub returned release information MetaFix could not read.")
    current = parse_version(current_version) or (0, 0, 0)
    newer = latest > current
    if newer:
        _last_release_url = url
    return {"current": current_version, "latest": ".".join(map(str, latest)), "newer": newer}


def open_release_page():
    if not _last_release_url:
        raise ValueError("Check for updates first.")
    webbrowser.open(_last_release_url)
