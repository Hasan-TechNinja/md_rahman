# laundrymart/authentication.py

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework import exceptions
from rest_framework_simplejwt.settings import api_settings

from .models import Employee
import logging
logger = logging.getLogger(__name__)

class DualAuthBackend(JWTAuthentication):
  def authenticate(self, request):
    logger.info('dual triggered')
    header = self.get_header(request)
    if header is None:
      return None

    raw_token = self.get_raw_token(header)
    if raw_token is None:
      return None
    print(raw_token)

    validated_token = self.get_validated_token(raw_token)
    print('validated token', validated_token)

    # 1. Determine User Type
    user_type = validated_token.get('user_type')
    logger.info(user_type)

    if user_type == 'employee':
      return self.get_employee(validated_token, request)

    # 2. Default fallback to standard User
    return super().get_user(validated_token), validated_token

  def get_employee(self, validated_token, request):
    user_id = validated_token.get(api_settings.USER_ID_CLAIM)
    try:
      employee = Employee.objects.get(id=user_id)
      # We attach it to request right here for easy access
      request.employee = employee

      # DRF still requires a 'user' object to be returned
      # to consider the request 'authenticated'.
      # You can return the employee as the 'user' as well.
      return employee, validated_token
    except Employee.DoesNotExist:
      raise exceptions.AuthenticationFailed('Employee not found')