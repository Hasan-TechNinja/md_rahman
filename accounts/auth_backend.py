from django.contrib.auth.backends import ModelBackend
from django.db import models

from accounts.models import User


class EmailOrPhoneBackend(ModelBackend):
  def authenticate(self, request, username=None, password=None, **kwargs):
    if username is None:
      username = kwargs.get(User.USERNAME_FIELD)

    # Try email OR phone_number
    try:
      user = User.objects.filter(
        models.Q(email=username) | models.Q(phone_number=username)
      ).first()
    except Exception:
      return None

    if user and user.check_password(password):
      return user
    return None
