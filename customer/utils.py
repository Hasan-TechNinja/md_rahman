import logging
from datetime import datetime

import stripe
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from stripe import CardError, InvalidRequestError, StripeError

from accounts.models import LaundrymartStore
from common_utils.distance_utils import calculate_distance_sql
from customer_push_notification.utils import customer_receive_no_laundrymart_available_notification
logger = logging.getLogger('auto_assign')

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
    #.filter(q_open)  # only open stores
    .annotate(distance=calculate_distance_sql(lat, lng))
    .filter(distance__lte=10)
    #.exclude(store_id=excluded_mart_id)
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

def create_validation_payment_intent(
    quote,
    payment_method_id: str,
    amount_cents: int,
    is_auto_assign: bool = False,
    idempotency_suffix: str = ""
) -> dict:
    """
    Creates a new off-session PaymentIntent for card validation (authorization hold).
    Updates quote with PI details.
    Designed to be called right before creating an Uber quote.

    Returns dict with:
    - success: bool
    - requires_action: bool
    - message: str
    - error: str (if failed)
    - payment_intent_id: str (if created)
    """
    user = quote.customer

    if not user.stripe_customer_id:
      return {"success": False, "error": "User has no Stripe customer ID"}

    if not payment_method_id:
      return {"success": False, "error": "No payment method ID provided"}

    idempotency_key = f"validate_quote_{quote.id}_{user.id}"
    if is_auto_assign:
      idempotency_key += "_autoassign"
    if idempotency_suffix:
      idempotency_key += f"_{idempotency_suffix}"

    try:
      with transaction.atomic():
        # Optional: small safety check
        quote = quote.__class__.objects.select_for_update().get(pk=quote.pk)

        pi = stripe.PaymentIntent.create(
          amount=amount_cents,
          currency="usd",
          customer=user.stripe_customer_id,
          payment_method=payment_method_id,
          off_session=True,
          confirm=True,
          capture_method="manual",
          description=f"LaundryMart validation - quote {quote.id} {'(re-assign)' if is_auto_assign else ''}",
          metadata={
            "user_id": str(user.id),
            "quote_id": str(quote.id),
            "attempt": "auto_reassign" if is_auto_assign else "initial_validation",
          },
          idempotency_key=idempotency_key,
        )

        quote.validation_pi_id = pi.id
        quote.validation_amount_cents = amount_cents
        quote.payment_method_id = payment_method_id  # ensure it's set / updated

        if pi.status == "requires_capture":
          quote.validation_status = "authorized"
          msg = "Authorization hold placed"
        elif pi.status == "requires_action":
          quote.validation_status = "requires_action"
          msg = "3D Secure authentication required (rare off-session)"
        elif pi.status == "succeeded":
          quote.validation_status = "succeeded"
          msg = "Instant confirmation succeeded (unusual for hold)"
        else:
          quote.validation_status = "failed"
          msg = f"Unexpected PaymentIntent status: {pi.status}"

        quote.save(update_fields=[
          'validation_pi_id',
          'validation_amount_cents',
          'payment_method_id',
          'validation_status'
        ])

        result = {
          "success": pi.status in ("requires_capture", "succeeded"),
          "requires_action": pi.status == "requires_action",
          "message": msg,
          "payment_intent_id": pi.id,
        }

        if pi.status == "requires_action":
          result["client_secret"] = pi.client_secret  # only useful if you want to handle in background somehow

        logger.info(f"Validation PI created: {pi.id} | status={pi.status} | amount={amount_cents} | quote={quote.id}")
        return result

    except CardError as e:
      quote.validation_status = "failed"
      quote.save(update_fields=['validation_status'])
      logger.warning(
        f"Card error during validation: {e.user_message} (decline_code={e.error.get('decline_code') if e.error else 'none'})")
      return {
        "success": False,
        "error": e.user_message or "Card was declined",
        "decline_code": e.error.get("decline_code") if hasattr(e, 'error') else None
      }

    except (StripeError, InvalidRequestError) as e:
      logger.exception("Stripe error during validation PI creation")
      quote.validation_status = "failed"
      quote.save(update_fields=['validation_status'])
      return {"success": False, "error": str(e)}

    except Exception as e:
      logger.exception("Unexpected error in create_validation_payment_intent")
      return {"success": False, "error": "Internal server error during payment validation"}