# utils/uber.py or services/uber_client.py
import requests
from laundrymart import settings
from django.core.cache import cache
from django.utils import timezone
import logging
logger = logging.getLogger(__name__)

UBER_TOKEN_CACHE_KEY = 'uber_direct:access_token'  # prefixed for clarity
UBER_TOKEN_EXPIRES_MARGIN = 86400  # Refresh 1 day before expiry (safe for 30-day tokens)
UBER_BASE_URL='https://api.uber.com/v1'

UBER_CLIENT_ID=settings.UBER_CLIENT_ID
UBER_CLIENT_SECRET=settings.UBER_CLIENT_SECRET

def get_uber_access_token():
  """
  Get cached Uber Direct access token, refresh if missing or about to expire.
  Works perfectly with Redis cache across all workers.
  """
  token_data = cache.get(UBER_TOKEN_CACHE_KEY)

  if token_data and token_data.get('expires_at', timezone.now()) > timezone.now():
    return token_data['access_token']
  print(UBER_CLIENT_ID, UBER_CLIENT_SECRET)

  # Fetch new token from Uber
  response = requests.post(
    'https://auth.uber.com/oauth/v2/token',
    headers={
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    data={
      'client_id': UBER_CLIENT_ID,
      'client_secret': UBER_CLIENT_SECRET,
      'grant_type': 'client_credentials',
      'scope': 'eats.deliveries',
    },
    timeout=10
  )

  # ADD THIS: Check for HTTP errors and parse error response
  if response.status_code != 200:
    error_detail = response.text  # Usually JSON like {"error": "...", "error_description": "..."}
    raise Exception(f"Uber OAuth failed ({response.status_code}): {error_detail}")

  try:
    data = response.json()
  except ValueError:
    raise Exception(f"Invalid JSON from Uber OAuth: {response.text}")

  if 'access_token' not in data:
    raise Exception(f"Missing access_token in Uber response: {data}")

  # Store with expiry info
  expires_at = timezone.now() + timezone.timedelta(seconds=data.get('expires_in', 2592000))
  cached_data = {
    'access_token': data['access_token'],
    'expires_at': expires_at,
  }

  # Cache for slightly less than actual expiry
  cache_ttl = data.get('expires_in', 2592000) - UBER_TOKEN_EXPIRES_MARGIN
  cache.set(UBER_TOKEN_CACHE_KEY, cached_data, timeout=cache_ttl)

  return data['access_token']

def uber_headers():
  return {
    'Authorization': f'Bearer {get_uber_access_token()}',
    'Content-Type': 'application/json',
    'Accept': 'application/json',
  }
