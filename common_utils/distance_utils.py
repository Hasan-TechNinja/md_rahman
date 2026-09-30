from math import radians, sin, cos, sqrt, atan2
from typing import Optional

from django.db.models import ExpressionWrapper, FloatField
from django.db.models.expressions import RawSQL
from django.db.models.functions import ACos, Cos, Radians, Sin

EARTH_RADIUS_MILES = 3959.0
def calculate_distance_km(
    lat1: Optional[float],
    lng1: Optional[float],
    lat2: Optional[float],
    lng2: Optional[float],
) -> Optional[float]:
  """
  Calculate great-circle distance between two points on Earth using Haversine formula.

  Args:
      lat1, lng1: Latitude and longitude of point 1 (user)
      lat2, lng2: Latitude and longitude of point 2 (vendor)

  Returns:
      Distance in kilometers (rounded to 1 decimal place), or None if any coord is missing/invalid.
  """
  # Validate inputs
  if None in (lat1, lng1, lat2, lng2):
    return None

  try:
    lat1 = float(lat1)
    lng1 = float(lng1)
    lat2 = float(lat2)
    lng2 = float(lng2)
  except (ValueError, TypeError):
    return None

  # Earth radius in kilometers
  R = 6371.0

  lat1_rad = radians(lat1)
  lng1_rad = radians(lng1)
  lat2_rad = radians(lat2)
  lng2_rad = radians(lng2)

  dlat = lat2_rad - lat1_rad
  dlon = lng2_rad - lng1_rad

  a = sin(dlat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2) ** 2
  c = 2 * atan2(sqrt(a), sqrt(1 - a))

  distance = R * c

  # Round to 1 decimal place for clean display
  return round(distance, 1)

def get_best_location(user) -> tuple[Optional[float], Optional[float]]:
  """
  Returns (lat, lng) using primary location first, then secondary.
  """
  lat = user.lat or user.secondary_lat
  lng = user.lng or user.secondary_lng

  if lat and lng:
      try:
          return float(lat), float(lng)
      except (ValueError, TypeError):
          pass
  return None, None

def calculate_distance_miles(
    lat1: Optional[float],
    lng1: Optional[float],
    lat2: Optional[float],
    lng2: Optional[float],
) -> Optional[float]:
  """
  Calculate great-circle distance between two points on Earth using Haversine formula.

  Returns:
      Distance in miles (rounded to 1 decimal place), or None if coordinates are missing/invalid.
  """
  if None in (lat1, lng1, lat2, lng2):
    return None

  try:
    lat1 = float(lat1)
    lng1 = float(lng1)
    lat2 = float(lat2)
    lng2 = float(lng2)
  except (ValueError, TypeError):
    return None

  # Earth radius in miles

  lat1_rad = radians(lat1)
  lng1_rad = radians(lng1)
  lat2_rad = radians(lat2)
  lng2_rad = radians(lng2)

  dlat = lat2_rad - lat1_rad
  dlon = lng2_rad - lng1_rad

  a = sin(dlat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2) ** 2
  c = 2 * atan2(sqrt(a), sqrt(1 - a))

  distance = EARTH_RADIUS_MILES * c

  return round(distance, 1)


def calculate_distance_sql(user_lat, user_lng):
  return RawSQL(
    """
    %s * acos(
      cos(radians(%s)) *
      cos(radians(lat)) *
      cos(radians(lng) - radians(%s)) +
      sin(radians(%s)) *
      sin(radians(lat))
    )
    """,
    (EARTH_RADIUS_MILES, user_lat, user_lng, user_lat),
    output_field=FloatField()
  )