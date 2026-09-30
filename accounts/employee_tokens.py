from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken  # make sure to import this


class EmployeeRefreshToken(RefreshToken):
  @classmethod
  def for_employee(cls, employee):
    token = cls()
    token[api_settings.USER_ID_CLAIM] = employee.pk
    token['user_type'] = 'employee'
    token['store_id'] = employee.laundrymart_store_id  # nice addition!
    return token

  @property
  def access_token(self):
    # Create a fresh AccessToken instance (this sets token_type='access' automatically)
    access = AccessToken()

    # Copy the custom claims you care about
    access[api_settings.USER_ID_CLAIM] = self[api_settings.USER_ID_CLAIM]
    access['user_type'] = self['user_type']
    access['store_id'] = self.get('store_id')  # safe get if not always present

    # Optional: copy other standard claims if needed (exp/iat/jti are handled by AccessToken)
    # Do NOT copy token_type or jti blindly

    return access