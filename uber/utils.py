import uuid

import requests

from accounts.models import LaundrymartStore
from laundrymart.settings import UBER_CUSTOMER_ID
from uber.cache_access_token import UBER_BASE_URL, uber_headers
from uber.models import Delivery, DeliveryQuote, ManifestItem
from uber.serializers import CreateDeliverySerializer, ManifestItemSerializer, UberCreateQuoteSerializer


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


def create_uber_delivery_quote(quote_data, manifest_items=None):
  # Validate and serialize the incoming data using the UberCreateQuoteSerializer
  serializer = UberCreateQuoteSerializer(data=quote_data)
  if not serializer.is_valid():
    print(f"Invalid data: {serializer.errors}")
    return None

  # Extract validated data
  validated_data = serializer.validated_data
  customer_id = UBER_CUSTOMER_ID
  service_type = validated_data.get('service_type')

  if not service_type or service_type not in ['drop_off', 'pickup', 'full_service']:
    print(f"Invalid service_type: {service_type}")
    return None

  # Handle the Uber API call for different service types
  try:

    uber_data = create_dropoff_quote(customer_id, validated_data)
    result = {
      "service_type": service_type,
      "pickup_address": validated_data["pickup_address"],
      "dropoff_address": validated_data["dropoff_address"],
      "pickup_latitude": validated_data["pickup_latitude"],
      "pickup_longitude": validated_data["pickup_longitude"],
      "dropoff_latitude": validated_data["dropoff_latitude"],
      "dropoff_longitude": validated_data["dropoff_longitude"],
      "pickup_phone_number": validated_data["pickup_phone_number"],
      "dropoff_phone_number": validated_data["dropoff_phone_number"],
      "pickup_ready_dt": validated_data.get("pickup_ready_dt"),

      # Uber response data
      "quote_id": uber_data["id"],
      "fee": uber_data["fee"],
      "currency": uber_data["currency"],
      "currency_type": uber_data.get("currency_type"),
      "expires": uber_data["expires"],
      "dropoff_eta": uber_data.get("dropoff_eta"),
      "duration": uber_data.get("duration"),
      "pickup_duration": uber_data.get("pickup_duration"),
      "dropoff_deadline": uber_data.get("dropoff_deadline"),
    }

    quote_obj = DeliveryQuote.objects.create(
      service_type=service_type,
      quote_id=result["quote_id"],
      customer=validated_data.get("customer"),
      pickup_address=result["pickup_address"],
      dropoff_address=result["dropoff_address"],
      pickup_latitude=result["pickup_latitude"],
      pickup_longitude=result["pickup_longitude"],
      dropoff_latitude=result["dropoff_latitude"],
      dropoff_longitude=result["dropoff_longitude"],
      pickup_phone_number=result["pickup_phone_number"],
      dropoff_phone_number=result["dropoff_phone_number"],
      pickup_ready_dt=result.get("pickup_ready_dt"),
      fee=result["fee"],
      currency=result["currency"],
      currency_type=result.get("currency_type"),
      expires=result["expires"],
      dropoff_eta=result.get("dropoff_eta"),
      duration=result.get("duration"),
      pickup_duration=result.get("pickup_duration"),
      dropoff_deadline=result.get("dropoff_deadline"),
    )
    if manifest_items:
      for item_data in manifest_items:
        # Assuming `item_data` is a dictionary representing the manifest item
        manifest_item = ManifestItem.objects.create(
          delivery_quote=quote_obj,  # Associate with the created DeliveryQuote
          **item_data  # Unpack the manifest item data
        )
        print(f"Created manifest item with ID: {manifest_item.id}")

    return quote_obj

  except requests.exceptions.RequestException as e:
    print(f"Uber quote creation failed: {str(e)}")
    return None
  except Exception as e:
    print(f"Unexpected error creating quote: {str(e)}")
    return None

def create_uber_delivery_from_quote(
    *,
    quote: DeliveryQuote,
    user,
    order=None,
    is_return_leg=False,
    parent_delivery=None,
    idempotency_key=None,
):
    if not quote or not quote.quote_id:
      print("No valid quote_id provided")
      return None

    headers = uber_headers()

    # 1. Build payload for Uber /deliveries
    payload = {
      "quote_id": quote.quote_id,
      "pickup_name": LaundrymartStore.objects.get(store_id=quote.external_store_id).laundrymart_name,
      "pickup_address": quote.pickup_address,
      "pickup_phone_number": quote.pickup_phone_number,
      "dropoff_name": quote.customer.full_name or "Customer",
      "dropoff_address": quote.dropoff_address,
      "dropoff_phone_number": quote.dropoff_phone_number,
      "pickup_latitude": quote.pickup_latitude,
      "pickup_longitude": quote.pickup_longitude,
      "dropoff_latitude": quote.dropoff_latitude,
      "dropoff_longitude": quote.dropoff_longitude,
      "deliverable_action": "deliverable_action_meet_at_door",
      "manifest_items": [],
      "external_store_id": quote.external_store_id,
      "manifest_total_value": int(quote.manifest_total_value or 0),
    }

    # Load manifest items from quote
    manifest_qs = ManifestItem.objects.filter(delivery_quote=quote)
    payload["manifest_items"] = ManifestItemSerializer(manifest_qs, many=True).data

    # 2. Call Uber → this is intentionally using the low-level function
    serializer = CreateDeliverySerializer(data=payload)
    serializer.is_valid(raise_exception=True)
    validated_data = serializer.validated_data
    try:
      delivery = create_and_save_delivery(
        user=user,
        validated_data=validated_data,
        payload=payload,  # gives names, addresses, phones
        is_return_leg=is_return_leg,
        parent_delivery=parent_delivery,
      )
    except Exception as e:
      print(f"Uber delivery creation failed for quote {quote.quote_id}: {str(e)}")
      return None

    # 5. Add quote-specific fields that aren't handled in the shared function
    delivery.quote = quote
    delivery.quote_uid = quote.quote_id
    #delivery.idempotency_key = idempotency_key
    delivery.pickup_ready = quote.pickup_ready_dt

    # Better: set real store name (override fallback from payload)
    try:
      store = LaundrymartStore.objects.get(store_id=quote.external_store_id)
      delivery.pickup_name = store.laundrymart_name
    except LaundrymartStore.DoesNotExist:
      pass  # keep the fallback name already set by create_and_save_delivery

    delivery.save(update_fields=[
      "quote",
      "quote_uid",
      # "idempotency_key",
      "pickup_ready",
      "pickup_name",  # only if changed
    ])

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