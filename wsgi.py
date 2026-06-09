"""WSGI-Einstiegspunkt für Gunicorn (Render.com)."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
from server.app import application

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5789))
    application.run(host="0.0.0.0", port=port, debug=False)
