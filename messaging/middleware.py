from urllib.parse import parse_qs
from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async






@database_sync_to_async
def get_user(token):
  from rest_framework_simplejwt.tokens import AccessToken
  from django.contrib.auth.models import AnonymousUser
  from accounts.models import User
  try:
    valid_token = AccessToken(token)
    user_id = valid_token['user_id']
    return User.objects.get(id=user_id)
  except Exception:
    return AnonymousUser()

class JWTAuthMiddleware(BaseMiddleware):
  async def __call__(self, scope, receive, send):
    from django.contrib.auth.models import AnonymousUser
    query_string = scope['query_string'].decode()
    query_params = parse_qs(query_string)
    token_list = query_params.get('token')
    user = AnonymousUser()

    if token_list:
      token = token_list[0]
      user = await get_user(token)

    scope['user'] = user
    return await super().__call__(scope, receive, send)