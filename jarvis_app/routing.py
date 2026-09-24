from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path("ws/events/", consumers.EventsConsumer.as_asgi()),
    path("ws/agent/", consumers.AgentConsumer.as_asgi()),
    path("ws/live/", consumers.LiveConsumer.as_asgi()),
]
