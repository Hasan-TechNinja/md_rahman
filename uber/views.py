import json
import os

import requests
import stripe
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from laundrymart import settings
from laundrymart.permissions import IsCustomer, IsStaff
from payment.models import Order
from uber.cache_access_token import UBER_BASE_URL, uber_headers
from uber.models import Delivery, DeliveryQuote, ManifestItem
from uber.serializers import CreateDeliverySerializer, UberCreateQuoteSerializer
from uber.utils import create_dropoff_quote, create_full_service_quotes, create_pickup_quote, \
  save_delivery_quote


# Create your views here.
class UberCreateQuoteAPIView(APIView):
  permission_classes = [IsCustomer]

  @extend_schema(
    request=UberCreateQuoteSerializer,
    responses={
      200: OpenApiResponse(
        description="Uber delivery quote created",
        response={
          "type": "object",
          "properties": {

          }
        }
      )
    }
  )
  def post(self, request):
    serializer = UberCreateQuoteSerializer(data=request.data, context={'request': request})
    if not serializer.is_valid():
      errors = serializer.errors
      field, messages = next(iter(errors.items()))
      readable_field = field.replace('_', ' ').capitalize()
      first_message = messages[0] if isinstance(messages, list) else messages
      error_message = f"{readable_field}: {first_message}"
      return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)

    customer_id = settings.UBER_CUSTOMER_ID
    service_type = serializer.validated_data.get("service_type")

    payload = serializer.to_uber_payload()
    result = {}

    if service_type == "drop_off":
      uber_data = create_dropoff_quote(customer_id, payload)
      result = {
        "service_type":service_type,
        "pickup_address":serializer.validated_data["pickup_address"],
        "dropoff_address":serializer.validated_data["dropoff_address"],
        "pickup_latitude":serializer.validated_data["pickup_latitude"],
        "pickup_longitude":serializer.validated_data["pickup_longitude"],
        "dropoff_latitude":serializer.validated_data["dropoff_latitude"],
        "dropoff_longitude":serializer.validated_data["dropoff_longitude"],
        "pickup_phone_number":serializer.validated_data["pickup_phone_number"],
        "dropoff_phone_number":serializer.validated_data["dropoff_phone_number"],
        "pickup_ready_dt": serializer.validated_data.get("pickup_ready_dt"),


        "quote_id": uber_data["id"],
        "fee": uber_data["fee"],
        "currency": uber_data["currency"],
        "currency_type": uber_data.get("currency_type"),
        "expires": uber_data["expires"],
        "dropoff_eta": uber_data.get("dropoff_eta"),
        "duration": uber_data.get("duration"),
        "pickup_duration": uber_data.get("pickup_duration"),
        "dropoff_deadline": uber_data.get("dropoff_deadline"),
        "external_store_id":uber_data["external_store_id"]
      }

    elif service_type == "pickup":
      uber_data = create_pickup_quote(customer_id, payload)
      result = {
        "service_type": service_type,
        "pickup_address": serializer.validated_data["pickup_address"],
        "dropoff_address": serializer.validated_data["dropoff_address"],
        "pickup_latitude": serializer.validated_data["pickup_latitude"],
        "pickup_longitude": serializer.validated_data["pickup_longitude"],
        "dropoff_latitude": serializer.validated_data["dropoff_latitude"],
        "dropoff_longitude": serializer.validated_data["dropoff_longitude"],
        "pickup_phone_number": serializer.validated_data["pickup_phone_number"],
        "dropoff_phone_number": serializer.validated_data["dropoff_phone_number"],
        "pickup_ready_dt": serializer.validated_data.get("pickup_ready_dt"),

        "quote_id": uber_data["id"],
        "fee": uber_data["fee"],
        "currency": uber_data["currency"],
        "currency_type": uber_data.get("currency_type"),
        "expires": uber_data["expires"],
        "dropoff_eta": uber_data.get("dropoff_eta"),
        "duration": uber_data.get("duration"),
        "pickup_duration": uber_data.get("pickup_duration"),
        "dropoff_deadline": uber_data.get("dropoff_deadline"),
        "external_store_id":uber_data["external_store_id"]
      }

    elif service_type == "full_service":
      # Generate payloads for each leg
      payload_to_vendor = serializer.to_uber_payload(destination="vendor")
      payload_to_customer = serializer.to_uber_payload(destination="customer")

      full_service_result = create_full_service_quotes(customer_id, payload_to_vendor, payload_to_customer)

      result = {
        "service_type": service_type,
        "pickup_address": serializer.validated_data["pickup_address"],
        "dropoff_address": serializer.validated_data["dropoff_address"],
        "pickup_latitude": serializer.validated_data["pickup_latitude"],
        "pickup_longitude": serializer.validated_data["pickup_longitude"],
        "dropoff_latitude": serializer.validated_data["dropoff_latitude"],
        "dropoff_longitude": serializer.validated_data["dropoff_longitude"],
        "pickup_phone_number": serializer.validated_data["pickup_phone_number"],
        "dropoff_phone_number": serializer.validated_data["dropoff_phone_number"],
        "pickup_ready_dt": serializer.validated_data.get("pickup_ready_dt"),
        "external_store_id": serializer.validated_data.get("external_store_id"),

        "first_quote": full_service_result["first_quote"],
        "second_quote": full_service_result["second_quote"],
        "combined_fee": full_service_result["combined_fee"]
      }

    return Response(result)


@require_POST
@csrf_exempt
def uber_delivery_status_webhook(request):
    """
    Handles Uber Direct 'event.delivery_status' webhook.
    Supports pickup + return deliveries per Order.
    """
    try:
        payload = json.loads(request.body)
        event_type = payload.get("event_type")

        if event_type != "event.delivery_status":
            print(f"Ignoring non-delivery-status event: {event_type}")
            return HttpResponse(status=200)

        delivery_id = payload.get("delivery_id")
        if not delivery_id:
            print("Webhook missing delivery_id")
            return HttpResponse(status=200)

        new_status = payload.get("status")
        courier_imminent = payload.get("courier_imminent", False)
        updated_at = payload.get("updated_at")
        data = payload.get("data", {})

        print(f"Uber webhook | delivery_id={delivery_id} → status={new_status} | imminent={courier_imminent}")

        with transaction.atomic():
            # 1. Get the Uber Delivery record (select_for_update to prevent race)
            try:
                uber_delivery = Delivery.objects.select_for_update().get(delivery_uid=delivery_id)
            except Delivery.DoesNotExist:
                print(f"Delivery not found for webhook: {delivery_id}")
                return HttpResponse(status=200)

            # 2. Update Uber Delivery fields
            uber_delivery.status = new_status
            uber_delivery.courier_imminent = courier_imminent
            uber_delivery.updated_at_uber = updated_at
            uber_delivery.uber_raw_response = payload

            # Optional useful fields from data
            if "dropoff_eta" in data:
                uber_delivery.dropoff_eta = data["dropoff_eta"]
            if courier_data := data.get("courier"):
                uber_delivery.courier_name = courier_data.get("name")
                uber_delivery.courier_phone = courier_data.get("phone_number")

            # Batch awareness (good to store even if not using right now)
            if batch_id := data.get("batch_id"):
                uber_delivery.batch_id = batch_id

            uber_delivery.save(update_fields=[
                "status", "courier_imminent", "dropoff_eta", "courier_name",
                "courier_phone", "updated_at_uber", "uber_raw_response",
                "batch_id"   # ← add this field to model if you want to store it
            ])

            # 3. Find the related Order and determine WHICH leg this is
            order = _find_related_order(uber_delivery)
            if not order:
                print(f"No Order found for delivery {delivery_id}")
                return HttpResponse(status=200)

            # 4. Update Order status depending on which delivery changed
            _update_order_status_based_on_delivery(order, uber_delivery, new_status, courier_imminent)

            # 5. Sync Stripe PaymentIntent (if exists)
            _sync_stripe_payment(order)

        return HttpResponse(status=200)

    except json.JSONDecodeError:
        print("Invalid JSON in Uber webhook")
        return HttpResponse(status=200)
    except Exception as e:
        print(f"Uber webhook unexpected error: {str(e)}")
        return HttpResponse(status=200)  # Uber requires 200 OK


def _find_related_order(uber_delivery: Delivery) -> Order | None:
    """Optimized lookup - try object relations first, fallback to IDs"""
    # Preferred: use direct relations (after adding the fields above)
    if hasattr(uber_delivery, "order_as_pickup") and uber_delivery.order_as_pickup:
        return uber_delivery.order_as_pickup

    if hasattr(uber_delivery, "order_as_return") and uber_delivery.order_as_return:
        return uber_delivery.order_as_return

    # Fallback: old string ID fields (you can remove this later)
    try:
        if uber_delivery.delivery_uid == uber_delivery.order_as_pickup.uber_pickup_delivery_id:
            return uber_delivery.order_as_pickup
    except (AttributeError, Order.DoesNotExist):
        pass

    try:
        if uber_delivery.delivery_uid == uber_delivery.order_as_return.uber_return_delivery_id:
            return uber_delivery.order_as_return
    except (AttributeError, Order.DoesNotExist):
        pass

    return None


def _update_order_status_based_on_delivery(
    order: Order,
    delivery: Delivery,
    new_status: str,
    courier_imminent: bool
):
    """Business-specific status mapping — customize per your needs"""

    is_pickup = delivery == order.pickup_delivery
    is_return = delivery == order.return_delivery

    prefix = "Pickup" if is_pickup else "Return" if is_return else "Delivery"

    status_map = {
        "pending": f"{prefix} – Processing",
        "pickup": f"{prefix} – En route" if courier_imminent else f"{prefix} – Arrived",
        "pickup_complete": f"{prefix} – Picked up",
        "dropoff": f"{prefix} – En route" if courier_imminent else f"{prefix} – Arriving soon",
        "delivered": "Completed" if is_return else "Ready for Return",
        "canceled": "Canceled",
        # ... add more Uber statuses you care about
    }

    new_order_status = status_map.get(new_status)
    if new_order_status and order.status != new_order_status:
        order.status = new_order_status
        print(f"Order {order.uuid} → {new_order_status} (from {prefix} delivery {delivery.delivery_uid})")
        order.save(update_fields=["status"])





def _sync_stripe_payment(order):
  """
  Sync Stripe PaymentIntent status with delivery progress
  Only if PaymentIntent exists (post-paid flow)
  """
  # Check if we have a Stripe PaymentIntent (created after weighing)
  if not hasattr(order, 'payment') or not order.payment:
    return  # No payment yet - normal for early delivery stages

  payment_intent_id = order.payment.stripe_payment_intent_id
  if not payment_intent_id:
    return

  try:
    # Fetch current PaymentIntent status from Stripe (optimized: single API call)
    pi = stripe.PaymentIntent.retrieve(
      payment_intent_id,
      expand=['payment_method']
    )

    current_pi_status = pi.status
    our_payment_status = order.payment.status

    # Update our Payment model if Stripe status changed
    if current_pi_status != our_payment_status:
      order.payment.status = current_pi_status
      order.payment.save(update_fields=['status'])

      print(
        f"Order {order.uuid} Stripe sync | PI {payment_intent_id} → {current_pi_status}"
      )

      # Optional: Trigger business actions based on payment status + delivery status
      _handle_payment_delivery_sync(order, current_pi_status)

  except stripe.error.StripeError as e:
    print(f"Stripe sync failed for PI {payment_intent_id}: {str(e)}")
  except Exception as e:
    print(f"Payment sync error for order {order.uuid}: {str(e)}")


def _handle_payment_delivery_sync(order, pi_status):
  """
  Handle any necessary business logic when delivery status updates
  and a PaymentIntent already exists.

  IMPORTANT: In your current flow, PaymentIntent is usually created LATE,
  so this function will be mostly a no-op during pickup/early return phases.
  """
  # Early return - most common case in your flow
  if not hasattr(order, 'payment') or not order.payment:
    return

  payment = order.payment
  pi_id = payment.stripe_payment_intent_id

  # Only meaningful case in your post-paid flow:
  # Return delivery completed + PaymentIntent is ready to capture
  if order.status == 'completed' and pi_status == 'requires_capture':
    try:
      stripe.PaymentIntent.capture(pi_id)
      print(f"Auto-captured PaymentIntent {pi_id} for completed order {order.uuid}")

      # Optional: update your Payment model status
      payment.status = 'succeeded'
      payment.save(update_fields=['status'])

    except stripe.error.StripeError as e:
      print(f"Failed to capture PI {pi_id} for order {order.uuid}: {str(e)}")
      # → Here you should probably create an admin notification / task
      # to manually handle the failed capture

  # Very rare safety net: if somehow order was cancelled but PI is still capturable
  elif order.status == 'canceled' and pi_status == 'requires_capture':
    try:
      stripe.PaymentIntent.cancel(
        pi_id,
        cancellation_reason='order_canceled'
      )
      print(f"Auto-cancelled PaymentIntent {pi_id} for cancelled order {order.uuid}")
    except stripe.error.StripeError as e:
      print(f"Cancel failed for PI {pi_id}: {str(e)}")
      # Again - better to notify admin than silently fail

  # Any other combination → just log, no automatic action
  else:
    if pi_status not in ['succeeded', 'canceled', 'requires_capture']:
      print(f"Note: PaymentIntent {pi_id} in unexpected status {pi_status} "
            f"for order {order.uuid} (status: {order.status})")
