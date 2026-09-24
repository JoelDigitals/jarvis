"""WSGI-Einstiegspunkt (nur HTTP, ohne Voice/WebSockets). Für den vollen Umfang ASGI/Daphne nutzen."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "jarvis_web.settings")
application = get_wsgi_application()
