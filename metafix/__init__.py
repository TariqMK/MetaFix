"""MetaFix desktop application."""
from flask import Flask
from pathlib import Path

try:
    __version__ = Path(__file__).with_name('_version.txt').read_text(encoding='utf-8').strip()
except FileNotFoundError:
    __version__ = '0.0.0+dev'


def create_app():
    app = Flask(__name__)
    from .routes import routes
    app.register_blueprint(routes)
    return app
