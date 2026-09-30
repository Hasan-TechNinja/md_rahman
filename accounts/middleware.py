from accounts.models import Employee


class DualUserMiddleware:
  def __init__(self, get_response):
    self.get_response = get_response

  def __call__(self, request):
    # Initialize attributes
    if not hasattr(request, 'employee'):
      request.employee = None

    # If the user is an Employee (authenticated via our backend)
    # ensure request.employee is set even if accessed outside DRF views
    if isinstance(getattr(request, 'user', None), Employee):
      request.employee = request.user

    return self.get_response(request)