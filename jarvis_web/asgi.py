"""ASGI-Einstiegspunkt (Daphne): HTTP + WebSockets (Voice, Events, Desktop-Agent)."""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "jarvis_web.settings")

from django.core.asgi import get_asgi_application  # noqa: E402

django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from jarvis_app import startup  # noqa: E402
from jarvis_app.routing import websocket_urlpatterns  # noqa: E402

startup.run()

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter(websocket_urlpatterns))),
})
