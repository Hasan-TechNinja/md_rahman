import uuid

import requests

from accounts.models import LaundrymartStore
from laundrymart.settings import UBER_CUSTOMER_ID
from uber.cache_access_token import UBER_BASE_URL, uber_headers
from uber.models import Delivery, DeliveryQuote, ManifestItem
from uber.serializers import ManifestItemSerializer


def create_dropoff_quote(customer_id, payload):
  resp = requests.post(
    f"{UBER_BASE_URL}/customers/{customer_id}/delivery_quotes",
    headers=uber_headers(),
    json=payload,
    timeout=10
  )
  resp.raise_for_status()
  return resp.json()


def create_pickup_quote(customer_id, payload):
  resp = requests.post(
    f"{UBER_BASE_URL}/customers/{customer_id}/delivery_quotes",
    headers=uber_headers(),
    json=payload,
    timeout=10
  )
  resp.raise_for_status()
  return resp.json()


def create_full_service_quotes(customer_id, payload_to_vendor, payload_to_customer):
  # First quote: customer -> vendor
  quote1 = create_dropoff_quote(customer_id, payload_to_vendor)

  # Second quote: vendor -> customer
  quote2 = create_pickup_quote(customer_id, payload_to_customer)

  # Combine fees
  combined_fee = quote1["fee"] + quote2["fee"]

  return {
    "first_quote": quote1,
    "second_quote": quote2,
    "combined_fee": combined_fee
  }


def save_delivery_quote(*, user, service_type, serializer_data, uber_data):
  return DeliveryQuote.objects.create(
    service_type=service_type,
    quote_id=uber_data["id"],
    customer=user,
    customer_note=serializer_data.get("customer_note"),
    pickup_address=serializer_data.get("pickup_address"),
    dropoff_address=serializer_data.get("dropoff_address"),
    pickup_latitude=serializer_data.get("pickup_latitude"),
    pickup_longitude=serializer_data.get("pickup_longitude"),
    dropoff_latitude=serializer_data.get("dropoff_latitude"),
    dropoff_longitude=serializer_data.get("dropoff_longitude"),
    pickup_phone_number=serializer_data.get("pickup_phone_number"),
    dropoff_phone_number=serializer_data.get("dropoff_phone_number"),
    manifest_total_value=serializer_data.get("manifest_total_value"),
    external_store_id=serializer_data.get("external_store_id"),
    fee=uber_data.get("fee"),
    currency=uber_data.get("currency"),
    currency_type=uber_data.get("currency_type"),
    dropoff_eta=uber_data.get("dropoff_eta"),
    duration=uber_data.get("duration"),
    pickup_duration=uber_data.get("pickup_duration"),
    dropoff_deadline=uber_data.get("dropoff_deadline"),
    expires=uber_data.get("expires"),
  )

def create_uber_delivery( payload, headers):
    """
    Low-level call to Uber Direct /deliveries endpoint.
    Returns the parsed JSON response.
    """
    resp = requests.post(
      f"{UBER_BASE_URL}/customers/{UBER_CUSTOMER_ID}/deliveries",
      headers=headers,
      json=payload,
      timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def create_and_save_delivery(
    *,
    user,
    validated_data,  # from ConfirmOrderSerializer.validated_data
    payload,
    is_return_leg=False,
    parent_delivery=None
):
  """
  Creates Uber delivery and saves it + manifest items to DB.
  Reusable for both pickup and full_service legs.
  """
  customer_id = UBER_CUSTOMER_ID
  headers = uber_headers()  # your existing function

  uber_data = create_uber_delivery(payload, headers)

  # Determine which lat/lng to use for dropoff (important for return leg)
  dropoff_lat = (
    validated_data["pickup_latitude"]
    if is_return_leg
    else validated_data["dropoff_latitude"]
  )
  dropoff_lng = (
    validated_data["pickup_longitude"]
    if is_return_leg
    else validated_data["dropoff_longitude"]
  )

  delivery = Delivery.objects.create(
    customer=user,
    delivery_uid=uber_data["id"],
    pickup_name=payload.get("pickup_name"),
    pickup_address=payload["pickup_address"],
    pickup_phone_number=payload["pickup_phone_number"],
    dropoff_name=payload.get("dropoff_name"),
    dropoff_address=payload["dropoff_address"],
    dropoff_phone_number=payload["dropoff_phone_number"],
    external_id=validated_data.get("external_id"),
    external_store_id=validated_data.get("external_store_id"),
    fee=uber_data.get("fee"),
    parent_delivery=parent_delivery,
    currency=uber_data.get("currency", "USD"),
    dropoff_eta=uber_data.get("dropoff_eta"),
    dropoff_deadline=uber_data.get("dropoff_deadline"),
    deliverable_action=validated_data.get("deliverable_action"),
    tracking_url=uber_data.get("tracking_url"),
    dropoff_latitude=dropoff_lat,
    dropoff_longitude=dropoff_lng,
    uber_raw_response=uber_data,
  )

  # Save manifest items using already-validated data
  for item in validated_data.get("manifest_items", []):
    ManifestItem.objects.create(delivery=delivery, **item)

  return delivery

def _sync_order_status(order, delivery_status, courier_imminent):
    """
    Maps Uber delivery status → internal Order status
    Adjust mapping to your exact needs
    """
    status_mapping = {
      'pending': 'processing',
      'pickup': 'picked_up' if not courier_imminent else 'pickup_en_route',
      'pickup_complete': 'picked_up',
      'dropoff': 'delivery_en_route' if not courier_imminent else 'courier_near_dropoff',
      'delivered': 'completed',
      'canceled': 'canceled',
      'returned': 'return_scheduled',
    }

    new_status = status_mapping.get(delivery_status)
    if new_status and order.status != new_status:
      order.status = new_status
      print(
        f"Order {order.uuid} status updated → {new_status} "
        f"(from delivery status: {delivery_status})"
      )


def create_uber_delivery_quote(quote_data: dict) -> DeliveryQuote | None:
  """
  Creates a Uber Direct delivery quote based on the provided data.

  quote_data expected keys (minimal set):
  - pickup_address, pickup_latitude, pickup_longitude, pickup_phone_number
  - dropoff_address, dropoff_latitude, dropoff_longitude, dropoff_phone_number
  - pickup_ready_dt (datetime, optional)
  - service_type: 'drop_off' | 'pickup' | 'full_service'
  - manifest_total_value (optional, decimal)
  - external_store_id (optional)
  - customer_note (optional)

  Returns:
      DeliveryQuote instance if successful, None if failed
  """
  customer_id = UBER_CUSTOMER_ID
  service_type = quote_data.get('service_type')

  if not service_type or service_type not in ['drop_off', 'pickup', 'full_service']:
    print(f"Invalid service_type: {service_type}")
    return None

  # Build base payload (same for all types)
  payload = {
    "pickup": {
      "address": quote_data.get("pickup_address"),
      "latitude": float(quote_data.get("pickup_latitude")),
      "longitude": float(quote_data.get("pickup_longitude")),
      "phone_number": quote_data.get("pickup_phone_number"),
    },
    "dropoff": {
      "address": quote_data.get("dropoff_address"),
      "latitude": float(quote_data.get("dropoff_latitude")),
      "longitude": float(quote_data.get("dropoff_longitude")),
      "phone_number": quote_data.get("dropoff_phone_number"),
    },
    "manifest": {
      "total_value": float(quote_data.get("manifest_total_value", 0)),
    },
    # Optional fields
    "pickup_ready_dt": quote_data.get("pickup_ready_dt", None),
    "external_store_id": quote_data.get("external_store_id"),
    "customer_note": quote_data.get("customer_note"),
  }

  try:
    if service_type in ["drop_off", "pickup"]:
      # Single-leg quote
      resp = requests.post(
        f"{UBER_BASE_URL}/customers/{customer_id}/delivery_quotes",
        headers=uber_headers(),
        json=payload,
        timeout=10,
      )
      resp.raise_for_status()
      uber_quote = resp.json()

      # Save to model
      quote_obj = DeliveryQuote.objects.create(
        service_type=service_type,
        quote_id=uber_quote["id"],
        customer=quote_data.get("customer"),  # must be passed or fetched
        pickup_address=quote_data["pickup_address"],
        dropoff_address=quote_data["dropoff_address"],
        pickup_latitude=quote_data["pickup_latitude"],
        pickup_longitude=quote_data["pickup_longitude"],
        dropoff_latitude=quote_data["dropoff_latitude"],
        dropoff_longitude=quote_data["dropoff_longitude"],
        pickup_phone_number=quote_data["pickup_phone_number"],
        dropoff_phone_number=quote_data["dropoff_phone_number"],
        pickup_ready_dt=quote_data.get("pickup_ready_dt"),
        fee=uber_quote["fee"],
        currency=uber_quote["currency"],
        currency_type=uber_quote.get("currency_type"),
        expires=uber_quote["expires"],
        dropoff_eta=uber_quote.get("dropoff_eta"),
        duration=uber_quote.get("duration"),
        pickup_duration=uber_quote.get("pickup_duration"),
        dropoff_deadline=uber_quote.get("dropoff_deadline"),
        manifest_total_value=quote_data.get("manifest_total_value"),
        external_store_id=quote_data.get("external_store_id"),
      )

      return quote_obj

    elif service_type == "full_service":
      # For full_service we usually need two quotes
      # But in your current flow you seem to handle it differently
      # → we'll assume you want just ONE quote here (return leg)
      # If you need both legs → call this function twice or use create_full_service_quotes

      # Most common: return leg quote when marking complete
      # So we flip pickup/dropoff for return leg
      return_payload = payload.copy()
      return_payload["pickup"] = payload["dropoff"].copy()
      return_payload["dropoff"] = payload["pickup"].copy()

      resp = requests.post(
        f"{UBER_BASE_URL}/customers/{customer_id}/delivery_quotes",
        headers=uber_headers(),
        json=return_payload,
        timeout=10,
      )
      resp.raise_for_status()
      uber_quote = resp.json()

      quote_obj = DeliveryQuote.objects.create(
        service_type=service_type,
        quote_id=uber_quote["id"],
        customer=quote_data.get("customer"),
        pickup_address=return_payload["pickup"]["address"],
        dropoff_address=return_payload["dropoff"]["address"],
        pickup_latitude=return_payload["pickup"]["latitude"],
        pickup_longitude=return_payload["pickup"]["longitude"],
        dropoff_latitude=return_payload["dropoff"]["latitude"],
        dropoff_longitude=return_payload["dropoff"]["longitude"],
        pickup_phone_number=return_payload["pickup"]["phone_number"],
        dropoff_phone_number=return_payload["dropoff"]["phone_number"],
        fee=uber_quote["fee"],
        currency=uber_quote["currency"],
        currency_type=uber_quote.get("currency_type"),
        expires=uber_quote["expires"],
        dropoff_eta=uber_quote.get("dropoff_eta"),
        duration=uber_quote.get("duration"),
        pickup_duration=uber_quote.get("pickup_duration"),
        dropoff_deadline=uber_quote.get("dropoff_deadline"),
        manifest_total_value=quote_data.get("manifest_total_value"),
        external_store_id=quote_data.get("external_store_id"),
      )

      return quote_obj

  except requests.exceptions.RequestException as e:
    print(f"Uber quote creation failed: {str(e)} - payload: {payload}")
    return None
  except Exception as e:
    print(f"Unexpected error creating quote: {str(e)}")
    return None

def create_uber_delivery_from_quote(
    *,
    quote: DeliveryQuote,
    user,
    order=None,  # optional - for linking/reference
    is_return_leg=False,
    parent_delivery=None,
    idempotency_key=None,
):
    """
    Creates an Uber delivery using an existing quote and saves it to DB.

    Follows the same pattern as create_and_save_delivery.

    Args:
        quote:              The DeliveryQuote instance (must have quote_id)
        user:               The customer User instance
        order:              Optional Order instance (for reference/external_id)
        is_return_leg:      Whether this is the return leg (affects lat/lng logic)
        parent_delivery:    Optional parent Delivery (for batching/full_service)
        idempotency_key:    Optional custom idempotency key (auto-generated if None)

    Returns:
        Delivery instance if successful, None if failed
    """
    if not quote or not quote.quote_id:
      print("No valid quote_id provided")
      return None

    customer_id = UBER_CUSTOMER_ID
    headers = uber_headers()

    # Build payload for /deliveries endpoint
    payload = {
      "quote_id": quote.quote_id,
      # You can add more optional fields if needed:
      # "external_id": ...,
      # "deliverable_action": ...,
      # "pickup_notes": ...,
      # "dropoff_notes": ...,
    }

    # Use a strong idempotency key (very important!)
    if not idempotency_key:
      idempotency_key = f"delivery-{quote.quote_id}-{uuid.uuid4().hex[:8]}"

    headers["Idempotency-Key"] = idempotency_key

    # Call Uber API to create delivery
    try:
      uber_data = create_uber_delivery(payload, headers)  # your existing function
    except Exception as e:
      print(f"Failed to create delivery from quote {quote.quote_id}: {str(e)}")
      return None

    if not uber_data or "id" not in uber_data:
      print(f"Invalid response from Uber create delivery: {uber_data}")
      return None

    # Decide dropoff coordinates (flip for return leg)
    dropoff_lat = quote.pickup_latitude if is_return_leg else quote.dropoff_latitude
    dropoff_lng = quote.pickup_longitude if is_return_leg else quote.dropoff_longitude

    # Create Delivery record
    delivery = Delivery.objects.create(
      customer=user,
      quote=quote,  # link to quote
      quote_uid=quote.quote_id,
      delivery_uid=uber_data["id"],
      idempotency_key=idempotency_key,

      pickup_name=LaundrymartStore.objects.get(store_id = quote.external_store_id).laundrymart_name,
      pickup_address=quote.pickup_address,
      pickup_phone_number=quote.pickup_phone_number,
      pickup_latitude=quote.pickup_latitude,
      pickup_longitude=quote.pickup_longitude,

      dropoff_name=quote.customer.full_name,
      dropoff_address=quote.dropoff_address,
      dropoff_phone_number=quote.dropoff_phone_number,
      dropoff_latitude=dropoff_lat,
      dropoff_longitude=dropoff_lng,

      external_store_id=quote.external_store_id,
      external_id=order.uuid.hex[:20] if order else None,

      fee=uber_data.get("fee"),
      total_fee=uber_data.get("total_fee"),  # if present
      currency=uber_data.get("currency", "usd"),
      dropoff_eta=uber_data.get("dropoff_eta"),
      dropoff_deadline=uber_data.get("dropoff_deadline"),
      tracking_url=uber_data.get("tracking_url"),

      deliverable_action="deliverable_action_meet_at_door",

      parent_delivery=parent_delivery,
      uber_raw_response=uber_data,

      # Optional - if you want to copy more from quote
      pickup_ready=quote.pickup_ready_dt,
    )

    # Inside create_uber_delivery_from_quote, after creating delivery:

    manifest_serializer = ManifestItemSerializer(
      data=quote.manifest_items.values(
        'name', 'quantity', 'size', 'dimensions', 'weight', 'price', 'vat_percentage'
      ),
      many=True
    )

    if manifest_serializer.is_valid():
      for item_data in manifest_serializer.validated_data:
        ManifestItem.objects.create(
          delivery=delivery,
          **item_data
        )
    else:
      print("Manifest items validation failed:", manifest_serializer.errors)
      # decide what to do — maybe continue anyway or rollback

    print(f"Created delivery {delivery.delivery_uid} from quote {quote.quote_id}")
    return delivery


def cancel_uber_delivery(delivery_uid: str) -> tuple[bool, str]:
  """
  Cancels a delivery using the Uber Direct API.

  Endpoint: POST /customers/{customer_id}/deliveries/{delivery_id}/cancel

  Usage example (exactly as you wrote):
      success, message = cancel_uber_delivery(new_delivery.delivery_uid)

  Returns:
      (True, "Delivery cancelled successfully")    on success
      (False, "error message or description")       on failure
  """
  customer_id = UBER_CUSTOMER_ID

  if not delivery_uid or not delivery_uid.startswith("del_"):
    return False, "Invalid delivery_uid format"

  payload = {
    "cancelation_reason": "other",
    "additional_description": "Not enough money in card"
  }

  url = f"{UBER_BASE_URL}/customers/{customer_id}/deliveries/{delivery_uid}/cancel"

  try:
    response = requests.post(
      url,
      headers=uber_headers(),
      json=payload,
      timeout=10,
    )

    if response.status_code in (200, 204):
      return True, "Delivery cancelled successfully"

    # Try to parse error
    try:
      error_data = response.json()
      error_msg = error_data.get("message", response.text)
    except ValueError:
      error_msg = response.text or f"HTTP {response.status_code}"

    return False, f"Cancel failed: {error_msg}"

  except requests.exceptions.RequestException as e:
    return False, f"Request error: {str(e)}"
  except Exception as e:
    return False, f"Unexpected error: {str(e)}"