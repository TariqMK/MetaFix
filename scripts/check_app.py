"""Non-destructive application smoke checks for every build platform."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from metafix import create_app
import metafix.desktop

client = create_app().test_client()
for url in ('/', '/api/config', '/static/css/app.css', '/static/js/app.js'):
    response = client.get(url)
    assert response.status_code == 200, (url, response.status_code)
print('Application imports and UI resources passed.')
