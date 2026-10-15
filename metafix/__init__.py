"""MetaFix desktop application."""
from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException
from pathlib import Path

try:
    __version__ = Path(__file__).with_name('_version.txt').read_text(encoding='utf-8').strip()
except FileNotFoundError:
    __version__ = '0.0.0+dev'


def create_app():
    app = Flask(__name__)
    from .routes import routes
    app.register_blueprint(routes)

    @app.errorhandler(Exception)
    def api_error(error):
        if isinstance(error, ValueError):
            return jsonify({'error': str(error)}), 400
        if isinstance(error, HTTPException):
            return jsonify({'error': error.description}), error.code
        app.logger.exception('Application request failed')
        return jsonify({'error': 'Operation failed; check the application log'}), 500

    return app
