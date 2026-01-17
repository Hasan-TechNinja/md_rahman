from datetime import datetime

from accounts.models import LaundrymartStore
from common_utils.distance_utils import calculate_distance_sql


def get_nearby_open_vendor(customer, excluded_mart_id=None):
  """
  This function takes a customer and returns the best vendor (LaundryMart store)
  that is open and within a certain distance based on customer location.
  """
  # Use customer's saved coordinates directly
  if not customer.lat or not customer.lng:
    return None, "Customer location (lat/lng) is not saved in profile."

  try:
    lat = float(customer.lat)
    lng = float(customer.lng)
  except (ValueError, TypeError):
    return None, "Invalid latitude or longitude in customer profile."

  # Optimized single query using your existing calculate_distance_sql
  candidates = (
    LaundrymartStore.objects.filter(
      price_per_pound__isnull=False,
      lat__isnull=False,
      lng__isnull=False,
    )
    .annotate(distance=calculate_distance_sql(lat, lng))
    .filter(distance__lte=10).exclude(store_id=excluded_mart_id)  # within 10 miles
    .order_by('price_per_pound')  # lowest price first
  )

  if not candidates.exists():
    return None, "No LaundryMart found within 10 miles with available pricing."

  # Get the current day of the week
  weekday = datetime.now().weekday()
  day_map = {
    0: 'monday',
    1: 'tuesday',
    2: 'wednesday',
    3: 'thursday',
    4: 'friday',
    5: 'saturday',
    6: 'sunday',
  }
  day_name = day_map[weekday]

  # Filter out stores that are closed based on their operating hours
  open_stores = []
  for store in candidates:
    is_closed_field = f'is_closed_{day_name}'
    if getattr(store, is_closed_field):
      continue  # Skip closed stores

    # Get the end time for the current day
    end_field = f'operating_hours_end_{day_name}'
    end_time = getattr(store, end_field)

    # Check if the store is open now (before the closing time)
    current_time = datetime.now().time()
    if current_time < end_time:
      open_stores.append(store)

  # If no stores are open, return None
  if not open_stores:
    return None, "No LaundryMart stores are open right now."

  # Return the first open store (the one with the lowest price per pound)
  return open_stores[0], None