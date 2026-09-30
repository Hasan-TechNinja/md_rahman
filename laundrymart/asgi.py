"""
ASGI config for laundrymart project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'laundrymart.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from django.core.asgi import get_asgi_application

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from messaging import routings
from messaging.middleware import JWTAuthMiddleware



django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": JWTAuthMiddleware(
        AuthMiddlewareStack(
            URLRouter(
                routings.websocket_urlpatterns
            )
        )
    )
})
