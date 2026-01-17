import logging
from datetime import datetime
from decimal import Decimal

import requests
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from accounts.models import LaundrymartStore
from common_utils.distance_utils import calculate_distance_sql
from customer.utils import get_nearby_open_vendor
from uber.models import DeliveryQuote
from uber.utils import create_dropoff_quote, create_pickup_quote

logger = logging.getLogger('auto_assign')

@shared_task()
def auto_assign_another_laundrymart(quote: DeliveryQuote, customer_id: str) -> dict:
  """
  Background process: Re-assign quote to next available laundry mart
  """
  customer = quote.customer
  logger.info(f"Starting auto-reassign for quote {quote.quote_id or '(no quote_id)'} "
              f"(customer: {customer.email or customer.phone_number or customer.pk})")

  try:
    with transaction.atomic():
      # 1. Find next suitable vendor
      selected_store, error_msg = get_nearby_open_vendor(customer, excluded_mart_id=quote.external_store_id)

      if not selected_store:
        logger.warning(f"Auto-assign failed: {error_msg}")
        return {
          "success": False,
          "error": error_msg or "No available open laundry mart",
        }

      logger.info(f"Selected new store: {selected_store.laundrymart_name} "
                  f"(store_id: {selected_store.store_id}) "
                  f"price_per_pound: {selected_store.price_per_pound}")

      # 2. Calculate updated manifest_total_value (in dollars → convert to cents)
      if not selected_store.price_per_pound:
        logger.warning(f"Store {selected_store} has no price_per_pound → using existing value")
        manifest_total_value_cents = int(quote.manifest_total_value or 0)  # already in cents
      else:
        from django.db.models import Sum, F, ExpressionWrapper, DecimalField

        total_weight = quote.manifest_items.aggregate(
          total=Sum(
            ExpressionWrapper(
              F('weight') * F('quantity'),
              output_field=DecimalField(max_digits=12, decimal_places=2)
            )
          )
        )['total'] or Decimal('0.00')

        manifest_total_value_dollars = (total_weight * selected_store.price_per_pound) + quote.insurance_amount
        manifest_total_value_cents = int(manifest_total_value_dollars * 100)  # convert dollars → cents

        logger.info(f"Recalculated manifest_total_value: {total_weight} lbs × "
                    f"{selected_store.price_per_pound} = {manifest_total_value_dollars} → {manifest_total_value_cents} cents")

      # 3. Prepare payload — manifest_total_value as INTEGER (cents)
      payload = {
        "pickup_address": quote.pickup_address,
        "dropoff_address": selected_store.location or selected_store.laundrymart_name,
        "pickup_latitude": quote.pickup_latitude,
        "pickup_longitude": quote.pickup_longitude,
        "dropoff_latitude": float(selected_store.lat),
        "dropoff_longitude": float(selected_store.lng),
        "pickup_phone_number": quote.pickup_phone_number,
        "dropoff_phone_number": quote.dropoff_phone_number or customer.phone_number,
        "customer_note": quote.customer_note,
        "manifest_total_value": int(manifest_total_value_cents),  # ensure integer cents
      }

      return_payload = {
        "pickup_address": selected_store.location,
        "dropoff_address": quote.pickup_address,
        "pickup_latitude": float(selected_store.lat),
        "pickup_longitude": float(selected_store.lng),
        "dropoff_latitude": float(quote.pickup_latitude),
        "dropoff_longitude": float(quote.pickup_longitude),
        "pickup_phone_number": quote.dropoff_phone_number,
        "dropoff_phone_number": quote.pickup_phone_number,
        "customer_note": quote.customer_note,
        "manifest_total_value": int(quote.manifest_total_value or 0),  # already cents → int
      }

      print('payload', payload)
      print('return_payload', return_payload)

      if quote.pickup_ready_dt:
        payload["pickup_ready_dt"] = quote.pickup_ready_dt.isoformat()

      # 4. Create new quote depending on service_type
      if not customer_id:
        logger.error(f"No Uber customer_id found")
        return {"success": False, "error": "Missing Uber customer ID"}

      try:
        if quote.service_type == 'drop_off':
          uber_response = create_dropoff_quote(customer_id, payload)
          print(uber_response)

        elif quote.service_type == 'pickup':
          uber_response = create_pickup_quote(customer_id, return_payload)
          print(uber_response)

        elif quote.service_type == 'full_service':
          uber_response = create_dropoff_quote(customer_id, payload)
          uber_return_response = create_pickup_quote(customer_id, return_payload)
          print('Full service: \n')
          print('uber_response:',uber_response)
          print('uber_return_response:',uber_return_response)
          final_charge_cents = int(uber_response["fee"]) + int(uber_return_response['fee']) + int(
            manifest_total_value_cents)
          uber_response["fee"] = final_charge_cents

        else:
          logger.error(f"Unsupported service_type: {quote.service_type}")
          return {"success": False, "error": f"Unsupported service type: {quote.service_type}"}

      except requests.RequestException as exc:
        logger.exception(f"Uber quote request failed for quote {quote.quote_id}")
        return {"success": False, "error": f"Uber API error: {str(exc)}"}

      except Exception as e:
        logger.exception("Unexpected error during Uber quote creation")
        return {"success": False, "error": "Internal error during quote refresh"}

      if not uber_response or "id" not in uber_response:
        logger.error(f"Invalid Uber response: {uber_response}")
        return {"success": False, "error": "Invalid response from Uber", "raw": uber_response}

      # 5. Update existing quote
      quote.quote_id = uber_response["id"]
      quote.external_store_id = str(selected_store.store_id)
      quote.manifest_total_value = manifest_total_value_cents  # now in cents

      fee_value = uber_response.get("fee")
      quote.fee = fee_value if fee_value is not None else None

      quote.dropoff_eta = uber_response.get("dropoff_eta")
      quote.duration = uber_response.get("duration")
      quote.pickup_duration = uber_response.get("pickup_duration")
      quote.dropoff_deadline = uber_response.get("dropoff_deadline")
      quote.expires = uber_response.get("expires")
      quote.created = uber_response.get("created", timezone.now())

      quote.dropoff_address = payload["dropoff_address"]
      quote.dropoff_latitude = payload["dropoff_latitude"]
      quote.dropoff_longitude = payload["dropoff_longitude"]

      quote.status = 'pending'

      quote.save(update_fields=[
        'quote_id', 'external_store_id', 'manifest_total_value', 'fee',
        'dropoff_eta', 'duration', 'pickup_duration', 'dropoff_deadline',
        'expires', 'created', 'status',
        'dropoff_address', 'dropoff_latitude', 'dropoff_longitude',
      ])

      logger.info(f"Quote {quote.quote_id} updated → "
                  f"new store: {selected_store.laundrymart_name}, "
                  f"manifest_total_value: {quote.manifest_total_value} cents, "
                  f"fee: {quote.fee}, status: {quote.status}")

      return {
        "success": True,
        "message": f"Re-assigned to {selected_store.laundrymart_name}",
        "quote_id": quote.quote_id,
        "new_store_id": str(selected_store.store_id),
        "new_store_name": selected_store.laundrymart_name,
        "fee": float(quote.fee or 0),
        "status": quote.status,
      }

  except Exception as e:
    logger.exception("Error during auto assignment process")
    return {"success": False, "error": "An error occurred during the re-assignment process."}
