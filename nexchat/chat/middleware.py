"""
JWTAuthMiddleware
-----------------
Validates a JWT access token supplied as a query parameter on the WebSocket
handshake URL:

    ws://host/ws/chat/<room_id>/?token=<access_token>

On success, sets scope["user"] to the authenticated Django user.
On failure, closes the connection with code 4001.

This is a pure ASGI middleware — it does not touch HTTP.
"""

from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken

from accounts.models import User


@database_sync_to_async
def get_user_from_token(token_str: str):
    """
    Validate the JWT and return the corresponding User, or AnonymousUser
    if the token is invalid / expired.
    """
    try:
        token = AccessToken(token_str)
        user_id = token["user_id"]
        return User.objects.get(pk=user_id)
    except (TokenError, InvalidToken, User.DoesNotExist, KeyError):
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    """
    Wraps the inner ASGI app and injects an authenticated user into scope.
    """

    async def __call__(self, scope, receive, send):
        # Extract token from query string: ?token=<jwt>
        query_params = parse_qs(scope.get("query_string", b"").decode())
        token_list = query_params.get("token", [])
        token_str = token_list[0] if token_list else ""

        scope["user"] = await get_user_from_token(token_str)
        return await super().__call__(scope, receive, send)