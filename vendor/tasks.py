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


def _handle_full_service_return(order: int, platform_charge: float, customer_stripe_charge_percentage, customer_stripe_charge_added_cents,
                                                           payout_transaction_charge_in_percentage, payout_transaction_added_cents) -> tuple[bool, str]:
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
  logger.info(f'Quote data: {quote_data}')
  manifest_items = ManifestItemSerializer(order.manifest_items.all(), many=True).data
  print('calling the create delivery quote function from util')
  quote = create_uber_delivery_quote(quote_data, manifest_items)
  if not quote:
    return False, "Failed to create return quote"

  print(f"during delivery quote: fee={quote.fee}, manifest_total_value={quote.manifest_total_value}, insurance_amount={quote.insurance_amount}, validation_amount_cents={quote.validation_amount_cents}")

  # Link quote early (safe even if later steps fail)
  order.uber_return_quote_id = quote.quote_id

  delivery = create_uber_delivery_from_quote(
    quote=quote,
    user=order.user,
    order=order,
    is_return_leg=True,
    parent_delivery=order.pickup_delivery,
    idempotency_key=f"{order.uuid}_return"
  )
  order.delivery_fee_cents += delivery.fee
  order.save(update_fields=['uber_return_quote_id', 'delivery_fee_cents'])
  print(f"after conversion to order: estimated_value={order.estimated_value}, service_charge_cents={order.service_charge_cents}, delivery_fee_cents={order.delivery_fee_cents}, final_total_cents={order.final_total_cents}, insurance_amount={order.insurance_amount}")

  if not delivery:
    return False, "Failed to create return delivery"

  # Attempt to charge the customer
  charge_success, charge_message = _attempt_charge_customer(order, platform_charge,
                                                            customer_stripe_charge_percentage,
                                                            customer_stripe_charge_added_cents,
                                                            payout_transaction_charge_in_percentage,
                                                            payout_transaction_added_cents)

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

#_handle_drop_off_completion
def _handle_drop_off_completion(order: int, platform_fee:float, customer_stripe_charge_percentage, customer_stripe_charge_added_cents,
                                                           payout_transaction_charge_in_percentage, payout_transaction_added_cents) -> tuple[bool, str]:
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
    "pickup_phone_number": store.phone_number,

    "dropoff_address": order.dropoff_address,
    "dropoff_latitude": order.dropoff_latitude,
    "dropoff_longitude": order.dropoff_longitude,
    "dropoff_phone_number": order.user.phone_number,

    "manifest_total_value": float(order.service_charge_cents or 0) / 100,
    "external_store_id": str(store.store_id),
    "customer_note": order.customer_note or "",
    "service_type": "pickup",  # your internal flag
    "customer": order.user,
  }
  logger.info(f'pickup delivery quote data:{quote_data}')

  quote = create_uber_delivery_quote(quote_data)
  if not quote:
    return False, "Failed to create delivery quote"

  print(f"during delivery quote: fee={quote.fee}, manifest_total_value={quote.manifest_total_value}, insurance_amount={quote.insurance_amount}, validation_amount_cents={quote.validation_amount_cents}")

  delivery = create_uber_delivery_from_quote(
    quote=quote,
    user=order.user,
    order=order,
    is_return_leg=False,
    parent_delivery=None,
    idempotency_key=f"{order.uuid}_pickup"
  )

  if not delivery:
    return False, "Failed to create delivery"

  # Attempt real charge
  order.delivery_fee_cents=delivery.fee
  order.save(update_fields=['delivery_fee_cents'])
  print(f"after conversion to order: estimated_value={order.estimated_value}, service_charge_cents={order.service_charge_cents}, delivery_fee_cents={order.delivery_fee_cents}, final_total_cents={order.final_total_cents}, insurance_amount={order.insurance_amount}")
  success, msg = _attempt_charge_customer(order, platform_fee,
                                                            customer_stripe_charge_percentage,
                                                            customer_stripe_charge_added_cents,
                                                            payout_transaction_charge_in_percentage,
                                                            payout_transaction_added_cents)

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

#pickup_delivery_and_charge
def _handle_pickup_delivery_and_charge(order: int, platform_fee:float, customer_stripe_charge_percentage, customer_stripe_charge_added_cents,
                                                           payout_transaction_charge_in_percentage, payout_transaction_added_cents) -> tuple[bool, str]:
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
  charge_success, charge_message = _attempt_charge_customer(order, platform_fee,
                                                            customer_stripe_charge_percentage,
                                                            customer_stripe_charge_added_cents,
                                                            payout_transaction_charge_in_percentage,
                                                            payout_transaction_added_cents
                                                            )

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
def _attempt_charge_customer(order: Order, platform_fee: float, customer_stripe_charge_percentage, customer_stripe_charge_added_cents,
                                                           payout_transaction_charge_in_percentage, payout_transaction_added_cents) -> tuple[bool, str]:
  from admin_panel.models import NotificationText
  import hashlib
  payment_failed_message = NotificationText.get_cached_notification_text().payment_failed

  logger.info('_attempt_charge_customer triggered')
  logger.info(f"Order ID: {order.id} | UUID: {order.uuid}")
  logger.info(f"stripe_customer_id: {order.stripe_customer_id}")
  logger.info(f"stripe_default_pm_id: {order.stripe_default_pm_id}")
  logger.info(f"service_provider: {order.service_provider}")
  logger.info(f"final_total_cents: {order.final_total_cents}")
  logger.info(f"platform_fee received: {platform_fee}")
  logger.info(f"delivery_fee_cents: {order.delivery_fee_cents}")
  logger.info(f"service_charge_cents: {order.service_charge_cents}")
  logger.info(f"insurance_amount: {order.insurance_amount}")
  logger.info(f"customer_stripe_charge_percentage: {customer_stripe_charge_percentage}")
  logger.info(f"customer_stripe_charge_added_cents: {customer_stripe_charge_added_cents}")
  logger.info(f"payout_transaction_charge_in_percentage: {payout_transaction_charge_in_percentage}")
  logger.info(f"payout_transaction_added_cents: {payout_transaction_added_cents}")

  if not order.stripe_customer_id or not order.stripe_default_pm_id:
    logger.error("Missing Stripe customer or default payment method")
    return False, payment_failed_message

  if not order.service_provider or not order.service_provider.admin.stripe_connect_account_id:
    logger.error("Missing Stripe connect account ID of the vendor")
    return False, ""

  if order.final_total_cents is None or order.final_total_cents <= 0:
    logger.error(
      f"CRITICAL: Order {order.uuid} has final_total_cents = {order.final_total_cents}. Cannot proceed with charge.")
    logger.error("This usually means pricing was not saved before marking order as ready.")
    return False, "Final total not calculated. Please complete order pricing first."

  connected_account_id = order.service_provider.admin.stripe_connect_account_id
  logger.info(f"Connected account ID: {connected_account_id}")

  try:
    base_platform_fee_cents = int(platform_fee * order.final_total_cents)

    # Extra amount you're adding specifically for payout / transaction handling
    payout_handling_fee_cents = int(
      base_platform_fee_cents * (payout_transaction_charge_in_percentage / 100)
    ) + payout_transaction_added_cents



    # Final amount to send as application_fee_amount to Stripe
    final_application_fee_amount = base_platform_fee_cents + payout_handling_fee_cents+ order.delivery_fee_cents
    logger.info(f"Calculated application_fee_amount: {final_application_fee_amount} cents")
  except Exception as calc_err:
    logger.error(f"Error calculating application fee: {calc_err}")
    return False, "Error calculating platform fee"
  idempotency_string = f"charge_order_{order.uuid}_{order.final_total_cents}"

  idempotency_key = idempotency_string
  customer_extra_fee = int(order.final_total_cents * (customer_stripe_charge_percentage / 100)
                           + customer_stripe_charge_added_cents)

  total_amount_to_charge = order.final_total_cents + customer_extra_fee
  logger.info(f"Stripe charged amount for customer: {customer_extra_fee}")

  try:
    logger.info("Creating Stripe PaymentIntent...")
    intent = stripe.PaymentIntent.create(
      amount=total_amount_to_charge,
      currency="usd",
      customer=order.stripe_customer_id,
      payment_method=order.stripe_default_pm_id,
      off_session=True,
      confirm=True,
      description=f"Laundry service + delivery - Order {order.uuid}",
      metadata={"order_uuid": str(order.uuid)},
      transfer_data={
        "destination": connected_account_id,
      },
      application_fee_amount=final_application_fee_amount,
      idempotency_key=idempotency_key,
    )

    logger.info(f'PaymentIntent created successfully. ID: {intent.id} | Status: {intent.status}')

    if intent.status == 'succeeded':
      logger.info("Payment succeeded. Creating VendorPayout record...")
      from payment.models import VendorPayout
      VendorPayout.objects.get_or_create(
        payment_intent_id=intent.id,
        vendor_admin=order.service_provider.admin,
        associated_store=order.service_provider,
        order=order,
        amount=order.final_total_cents / 100.0,
        currency="USD",
        status="pending",
        is_instant=False,
        platform_fee=base_platform_fee_cents/100,
        added_stripe_fee = payout_handling_fee_cents/100,
        initiated_by=None,
        idempotency_key=idempotency_key,

      )
      logger.info("VendorPayout record created successfully")
      return True, "succeeded"

    logger.warning(f"PaymentIntent did not succeed. Status: {intent.status}")
    return False, f"PaymentIntent in state: {intent.status}"

  except stripe.error.CardError as e:
    logger.error(f"CardError: {e.user_message or str(e)}")
    return False, f"Card declined: {e.user_message or str(e)}"
  except stripe.error.StripeError as e:
    # Important: If Stripe returns "idempotency_key" error, it means the request is a duplicate
    if "idempotency" in str(e).lower() or getattr(e, 'code', None) == 'idempotency_key_in_use':
      logger.info(f"Idempotent request detected for order {order.uuid}. Checking existing PaymentIntent...")

      # Optional: You can retrieve the existing PaymentIntent here if needed
      # But for now, we treat it as already attempted
      return False, "Payment already attempted (idempotent)"

    logger.error(f"StripeError for order {order.uuid}: {str(e)}")
    return False, f"Stripe error: {str(e)}"
  except Exception as e:
    logger.error(f"Unexpected exception during charge: {type(e).__name__} - {str(e)}")
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
    print('task process_order_completion triggered')
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
    global_config=GlobalManifest.get_vendor_cached_config()
    notifications= NotificationText.get_cached_notification_text()
    platform_fee = float(global_config.get('service_fee', '5.00')) / 100
    customer_stripe_charge_percentage = float(global_config.get('customer_stripe_charge_in_percentage', '0.25'))
    customer_stripe_charge_added_cents = int(global_config.get('customer_stripe_charge_added_cents', 99))

    payout_transaction_charge_in_percentage = float(global_config.get('payout_transaction_charge_in_percentage', '0.25'))
    payout_transaction_added_cents = int(global_config.get('payout_transaction_added_cents', 99))


    with transaction.atomic():
        try:
            if service_type == 'Full service':
                success, msg = _handle_full_service_return(order.id, platform_fee, customer_stripe_charge_percentage, customer_stripe_charge_added_cents,
                                                           payout_transaction_charge_in_percentage, payout_transaction_added_cents)
            elif service_type == 'Pick up':
                success, msg = _handle_pickup_delivery_and_charge(order.id, platform_fee, customer_stripe_charge_percentage, customer_stripe_charge_added_cents,
                                                           payout_transaction_charge_in_percentage, payout_transaction_added_cents)
            elif service_type == 'Drop off':
                success, msg = _handle_drop_off_completion(order.id, platform_fee, customer_stripe_charge_percentage, customer_stripe_charge_added_cents,
                                                           payout_transaction_charge_in_percentage, payout_transaction_added_cents)
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