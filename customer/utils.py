from datetime import datetime

from django.db.models import Q
from django.utils import timezone

from accounts.models import LaundrymartStore
from common_utils.distance_utils import calculate_distance_sql
from customer_push_notification.utils import customer_receive_no_laundrymart_available_notification


def get_nearby_open_vendor(customer, excluded_mart_id=None):
  """
  Returns the best (cheapest) currently open vendor within range,
  or (None, error_message)
  """
  if not customer.lat or not customer.lng:
    return None, "Customer location (lat/lng) is not saved."

  try:
    lat = float(customer.lat)
    lng = float(customer.lng)
  except (ValueError, TypeError):
    return None, "Invalid customer coordinates."

  now = timezone.localtime()
  weekday = now.weekday()
  current_time = now.time()

  day_map = {
    0: 'monday', 1: 'tuesday', 2: 'wednesday', 3: 'thursday',
    4: 'friday', 5: 'saturday', 6: 'sunday'
  }
  day_name = day_map[weekday]

  # Build dynamic Q for open stores today
  q_open = Q(**{
    f'is_closed_{day_name}': False,
    f'operating_hours_start_{day_name}__lte': current_time,
    f'operating_hours_end_{day_name}__gt': current_time,
  })

  candidates = (
    LaundrymartStore.objects
    .filter(
      price_per_pound__isnull=False,
      lat__isnull=False,
      lng__isnull=False,
    )
    .filter(q_open)  # only open stores
    .annotate(distance=calculate_distance_sql(lat, lng))
    .filter(distance__lte=10)
    .exclude(store_id=excluded_mart_id)
    .order_by('price_per_pound')
  )

  # We only need the first one
  best_store = candidates.first()
  print(best_store)

  if best_store is None:
    if not LaundrymartStore.objects.filter(q_open).exists():
      customer_receive_no_laundrymart_available_notification(customer)

      return None, "No LaundryMart stores are open right now."
    else:
      return None, "No open LaundryMart found within 10 units."

  return best_store, None