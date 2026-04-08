import stripe
from celery import shared_task
from django.db import transaction
from rest_framework.generics import get_object_or_404
from stripe import StripeError

from admin_panel.models import NotificationText
from customer_push_notification.utils import send_completion_notification_to_customer, \
  send_order_return_scheduled_for_full_service_notification_to_customer
from laundrymart.settings import STRIPE_SECRET_KEY
from payment.models import Order
from uber.models import DeliveryQuote
from uber.serializers import ManifestItemSerializer
from uber.utils import cancel_uber_delivery, create_uber_delivery_from_quote, create_uber_delivery_quote
from vendor_push_notification.utils import send_order_return_scheduled_for_full_service_notification_to_vendor
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)


def _handle_full_service_return(order: int, platform_charge: float) -> tuple[bool, str]:
  """
  Create return delivery (store → customer) using flipped quote.
  Charges customer immediately on success using saved payment method.
  If payment fails → cancels the Uber delivery immediately.
  """
  order=get_object_or_404(Order, pk=order)
  if not order.pickup_delivery or not order.pickup_delivery.delivery_uid:
    return False, "No valid pickup delivery found for return leg"

  store = order.service_provider

  quote_data = {
    "pickup_address": order.service_provider.location,
    "pickup_latitude": order.service_provider.lat,
    "pickup_longitude": order.service_provider.lng,
    "pickup_phone_number": order.service_provider.phone_number or "+1234567890",

    "dropoff_address": DeliveryQuote.objects.get(quote_id=order.uber_pickup_quote_id).pickup_address,
    "dropoff_latitude": DeliveryQuote.objects.get(quote_id=order.uber_pickup_quote_id).pickup_latitude,
    "dropoff_longitude": DeliveryQuote.objects.get(quote_id=order.uber_pickup_quote_id).pickup_longitude,
    "dropoff_phone_number": DeliveryQuote.objects.get(quote_id=order.uber_pickup_quote_id).pickup_phone_number,

    "manifest_total_value": float(order.service_charge_cents or 0) / 100,
    "external_store_id": str(store.store_id),
    "customer_note": order.customer_note or "",
    "service_type": "full_service",
    "customer": order.user,
  }
  manifest_items = ManifestItemSerializer(order.manifest_items.all(), many=True).data

  quote = create_uber_delivery_quote(quote_data, manifest_items)
  if not quote:
    return False, "Failed to create return quote"

  # Link quote early (safe even if later steps fail)
  order.uber_return_quote_id = quote.quote_id
  order.save(update_fields=['uber_return_quote_id'])

  delivery = create_uber_delivery_from_quote(
    quote=quote,
    user=order.user,
    order=order,
    is_return_leg=True,
    parent_delivery=order.pickup_delivery,
  )

  if not delivery:
    return False, "Failed to create return delivery"

  # Attempt to charge the customer
  charge_success, charge_message = _attempt_charge_customer(order, platform_charge)

  if not charge_success:
    # Payment failed → cancel the delivery we just created
    cancel_success, cancel_msg = cancel_uber_delivery(delivery.delivery_uid)

    if not cancel_success:
      # Critical: payment failed and cancel also failed
      logger.error(
        f"CRITICAL: Payment failed ({charge_message}) "
        f"and could not cancel delivery {delivery.delivery_uid}: {cancel_msg}"
      )

    error_message = charge_message
    if not cancel_success:
      error_message += " (delivery cancellation also failed — contact support)"

    return False, error_message

  # Charge succeeded → save the PaymentIntent ID if available
  # Note: _attempt_charge_customer doesn't return the intent object,
  #       so if you need the intent.id for records, modify the helper to return it.
  # For now we assume you handle intent.id inside _attempt_charge_customer
  # or via webhook later.

  # Finalize order
  with transaction.atomic():
    order.return_delivery = delivery
    order.uber_return_delivery_id = delivery.delivery_uid
    order.status = 'return_scheduled'
    order.save(update_fields=[
      'return_delivery',
      'uber_return_delivery_id',
      'status',
      # Add 'stripe_return_payment_intent_id' if you modify helper to save it
    ])

  send_order_return_scheduled_for_full_service_notification_to_vendor(
    order, order.service_provider
  )
  send_order_return_scheduled_for_full_service_notification_to_customer(
    order, order.user
  )

  return True, "Return delivery scheduled and customer charged successfully"


def _handle_pickup_delivery_and_charge(order: int, platform_fee:float) -> tuple[bool, str]:
  """
  Create delivery (store → customer) + attempt Stripe charge
  Rollback (cancel) if payment fails
  """
  order = get_object_or_404(Order, pk=order)
  store = order.service_provider

  quote_data = {
    "pickup_address": store.location,
    "pickup_latitude": store.lat,
    "pickup_longitude": store.lng,
    "pickup_phone_number": "your-store-phone-here",

    "dropoff_address": order.dropoff_address,
    "dropoff_latitude": order.dropoff_latitude,
    "dropoff_longitude": order.dropoff_longitude,
    "dropoff_phone_number": order.user.phone_number or "+1234567890",

    "manifest_total_value": float(order.service_charge_cents or 0) / 100,
    "external_store_id": str(store.store_id),
    "customer_note": order.customer_note or "",
    "service_type": "pickup",  # your internal flag
    "customer": order.user,
  }

  quote = create_uber_delivery_quote(quote_data)
  if not quote:
    return False, "Failed to create delivery quote"

  delivery = create_uber_delivery_from_quote(
    quote=quote,
    user=order.user,
    order=order,
    is_return_leg=False,
    parent_delivery=None,
  )

  if not delivery:
    return False, "Failed to create delivery"

  # Attempt real charge
  success, msg = _attempt_charge_customer(order, platform_fee)

  if success:
    with transaction.atomic():
      order.return_delivery = delivery
      order.uber_return_delivery_id = delivery.delivery_uid
      order.status = 'charged'  # or 'return_scheduled' / 'completed'
      order.save(update_fields=[
        'return_delivery',
        'uber_return_delivery_id',
        'status'
      ])
      _notify_customer_success(order)
    return True, "Delivery created + customer charged"

  else:
    # Rollback Uber delivery
    cancel_success, cancel_msg = cancel_uber_delivery(delivery.delivery_uid)
    logger.info(f"Payment failed → cancel result: {cancel_msg}")

    order.status = 'completion_failed'
    order.save(update_fields=['status'])
    notification_message = NotificationText.get_cached_notification_text().payment_failed
    _notify_customer_failed(order, msg)
    return False, f"Charge failed: {msg}"


def _handle_drop_off_completion(order: int, platform_fee:float) -> tuple[bool, str]:
  """
  Handles completion of drop-off order:
  - Attempts to charge the customer using the saved payment method.
  - On success: sets status to 'charged' and notifies customer to pick up.
  - On failure: returns error without changing status.
  """
  order = get_object_or_404(Order, pk=order)
  if not order.stripe_customer_id or not order.stripe_default_pm_id:
    return False, "Missing Stripe customer or default payment method"

  # Attempt to charge the customer
  charge_success, charge_message = _attempt_charge_customer(order, platform_fee)

  if not charge_success:
    # Log the failure but don't change order status
    logger.error(f"Charge failed for drop-off order {order.uuid}: {charge_message}")
    return False, f"Failed to charge customer: {charge_message}"

  # Charge succeeded → finalize order
  with transaction.atomic():
    order.status = 'charged'
    order.save(update_fields=[
      'status'
    ])

  # Notify customer that laundry is ready for pickup
  _notify_customer_ready_or_completed(order)  # this should send "Your laundry is ready for pickup!"

  return True, "Drop-off order charged and marked ready for pickup"


# ---------------------------------------------------------------------------
# Stripe charge helper (same as before)
def _attempt_charge_customer(order: Order, platform_fee:float) -> tuple[bool, str]:
  from admin_panel.models import NotificationText
  payment_failed_message =  NotificationText.get_cached_notification_text().payment_failed

  logger.info('_attempt_charge_customer triggered')
  if not order.stripe_customer_id or not order.stripe_default_pm_id:
    logger.error("Missing Stripe customer or default payment method")
    return False, payment_failed_message

  if not order.service_provider or not order.service_provider.admin.stripe_connect_account_id:
    logger.error("Missing Stripe connect account ID of the vendor")
    return False, ""

  connected_account_id = order.service_provider.admin.stripe_connect_account_id
  application_fee_amount = int((platform_fee / 100) * order.final_total_cents)
  try:
    intent = stripe.PaymentIntent.create(
      amount=int(order.final_total_cents),
      currency="usd",
      customer=order.stripe_customer_id,
      payment_method=order.stripe_default_pm_id,
      off_session=True,
      confirm=True,
      description=f"Order {order.uuid} – laundry service + delivery",
      metadata={"order_uuid": str(order.uuid)},
      transfer_data={
        "destination": connected_account_id,
      },
      application_fee_amount=application_fee_amount
    )
    logger.info('Payment intent',intent.status)

    if intent.status == 'succeeded':
      from payment.models import VendorPayout
      VendorPayout.objects.create(
        vendor_admin=order.service_provider.admin,
        associated_store=order.service_provider,
        order=order,
        amount=order.final_total_cents / 100.0,
        currency="USD",
        status="pending",
        is_instant=False,
        initiated_by=None
      )
      return True, "succeeded"
    return False, f"PaymentIntent in state: {intent.status}"
  except stripe.error.CardError as e:
    return False, f"Card declined: {e.user_message or str(e)}"
  except stripe.error.StripeError as e:
    return False, f"Stripe error: {str(e)}"
  except Exception as e:
    return False, f"Unexpected: {str(e)}"


# ---------------------------------------------------------------------------
# Simple notification helpers – customize as you wish
def _notify_customer_success(order):

  logger.info('notify customer')


def _notify_customer_failed(order, reason):

  logger.info('notify customer')


def _notify_customer_ready_or_completed(order):
  logger.info('notify customer')


def get_order_service_type(order):
  pass


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,   # seconds
)
def process_order_completion(self, order_id: int):
    """
    Main background task after vendor marks order as 'weighed'.
    Handles delivery scheduling + charging depending on service type.
    """
    try:
        order = Order.objects.select_related(
            'user', 'service_provider', 'pickup_delivery', 'return_delivery'
        ).get(pk=order_id)
    except Order.DoesNotExist:
        logger.error(f"Order {order_id} not found in completion task")
        return False, "Order not found"
    from admin_panel.models import GlobalManifest, NotificationText
    service_type = order.get_service_type()
    logger.info(service_type)
    logger.info(order)
    global_config=GlobalManifest.get_cached_config()
    notifications= NotificationText.get_cached_notification_text()
    platform_fee = global_config.service_fee


    with transaction.atomic():
        try:
            if service_type == 'Full service':
                success, msg = _handle_full_service_return(order.id, platform_fee)
            elif service_type == 'Pick up':
                success, msg = _handle_pickup_delivery_and_charge(order.id, platform_fee)
            elif service_type == 'Drop off':
                success, msg = _handle_drop_off_completion(order.id, platform_fee)
            else:
                success, msg = False, f"Unsupported service type: {service_type}"

            if success:
                order.status = 'return_scheduled' if service_type != 'Drop off' else 'completed'
                order.save(update_fields=['status'])
                send_completion_notification_to_customer(order, order.user)
            else:
                # rollback-sensitive changes already avoided via atomic + careful order
                logger.error(f"Completion failed for order {order_id}: {msg}")
                # optionally set to a recovery status like 'needs_support'
                order.status = 'wait_for_support'
                order.save(update_fields=['status'])

            return success, msg

        except Exception as exc:
            logger.error(f"Critical error in order completion {order_id}")
            raise self.retry(exc=exc)  # Celery will retry