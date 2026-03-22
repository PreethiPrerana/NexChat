"""
ASGI config for NexChat.

Daphne routes:
  - HTTP  → Django ASGI app
  - WS    → Django Channels (ChatConsumer)
"""

import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nexchat.settings")

# Initialise Django before importing app-level modules.
django_asgi_app = get_asgi_application()

from chat.middleware import JWTAuthMiddleware  # noqa: E402 — must be after Django init
from chat.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            JWTAuthMiddleware(
                URLRouter(websocket_urlpatterns)
            )
        ),
    }
)