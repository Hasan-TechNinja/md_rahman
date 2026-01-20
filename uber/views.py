import json
import os

import requests
import stripe
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.db.models import Q
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
    print(request.data)
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
      print(payload)
      uber_data = create_dropoff_quote(customer_id, payload)
      if "code" in uber_data and uber_data["kind"] == "error":
        return Response({
          "error": "Uber could not create quote",
          "uber_code": uber_data.get("code"),
          "uber_message": uber_data.get("message"),
          "details": uber_data.get("metadata", {}).get("details"),
          "sent_payload": payload  # for debugging
        }, status=400)
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
        "external_store_id": serializer.validated_data.get("external_store_id"),


        "quote_id": uber_data["id"],
        "fee": uber_data["fee"],
        "currency": uber_data["currency"],
        "currency_type": uber_data.get("currency_type"),
        "expires": uber_data["expires"],
        "dropoff_eta": uber_data.get("dropoff_eta"),
        "duration": uber_data.get("duration"),
        "pickup_duration": uber_data.get("pickup_duration"),
        "dropoff_deadline": uber_data.get("dropoff_deadline")
      }

    elif service_type == "pickup":
      uber_data = create_pickup_quote(customer_id, payload)
      if "code" in uber_data and uber_data["kind"] == "error":
        return Response({
          "error": "Uber could not create quote",
          "uber_code": uber_data.get("code"),
          "uber_message": uber_data.get("message"),
          "details": uber_data.get("metadata", {}).get("details"),
          "sent_payload": payload  # for debugging
        }, status=400)
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


DELIVERY_STATUS_CHOICES = [
  ('pending', 'Pending'),
  ('pickup_true', 'Pickup True'),
  ('pickup_false', 'Pickup False'),
  ('pickup_complete', 'Pickup Complete'),
  ('dropoff_true', 'Dropoff True'),
  ('dropoff_false', 'Dropoff False'),
  ('delivered', 'Delivered'),
  ('canceled', 'Canceled'),
  ('returned', 'Returned')
]


def delivery_status_mapping(delivery_status, uber_delivery, courier_imminent):
  # Handle different states based on courier_imminent and uber_delivery flags
  if delivery_status == 'pending':
    return 'pending'

  if courier_imminent:  # If courier is imminent
    if uber_delivery == 'pickup':
      return 'pickup_true'
    elif uber_delivery == 'dropoff':
      return 'dropoff_true'

  if not courier_imminent:  # If courier is not imminent
    if uber_delivery == 'pickup':
      return 'pickup_false'
    elif uber_delivery == 'dropoff':
      return 'dropoff_false'

  # Handle delivery completion or cancellation
  if delivery_status == 'completed':
    return 'delivered'
  if delivery_status == 'canceled':
    return 'canceled'
  if delivery_status == 'returned':
    return 'returned'

  return delivery_status





@require_POST
@csrf_exempt
def uber_delivery_status_webhook(request):

    print("Uber webhook triggered")

    try:
        payload = json.loads(request.body)
        print(payload)
        event_type = payload.get("kind")

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
            # 1. Get and lock the Delivery record
            try:
                uber_delivery = Delivery.objects.select_for_update().get(delivery_uid=delivery_id)
                print(uber_delivery)
                delivery_status = delivery_status_mapping(new_status, uber_delivery,courier_imminent)
                print(delivery_status)
            except Delivery.DoesNotExist:
                print(f"Delivery not found for webhook: {delivery_id}")
                return HttpResponse(status=200)

            # 2. Update Delivery fields
            update_fields = [
                "status",
                "courier_imminent",
                "updated_at_uber",
                "uber_raw_response",
            ]

            uber_delivery.status = delivery_status
            uber_delivery.courier_imminent = courier_imminent
            uber_delivery.updated_at_uber = updated_at
            uber_delivery.uber_raw_response = payload

            # Optional useful fields
            if "dropoff_eta" in data:
                uber_delivery.dropoff_eta = data["dropoff_eta"]
                update_fields.append("dropoff_eta")

            if courier_data := data.get("courier"):
                if name := courier_data.get("name"):
                    uber_delivery.courier_name = name
                    update_fields.append("courier_name")
                if phone := courier_data.get("phone_number"):
                    uber_delivery.courier_phone = phone
                    update_fields.append("courier_phone")

            if batch_id := data.get("batch_id"):
                uber_delivery.batch_id = batch_id
                update_fields.append("batch_id")

            uber_delivery.save(update_fields=update_fields)

            # 3. Find related Order and update status
            order = _find_related_order(uber_delivery)
            service_type=order.get_service_type()
            return_leg=uber_delivery.is_return_leg
            if order:
                _update_order_status_based_on_delivery(
                    order,
                    uber_delivery,
                    new_status,
                    service_type,
                    return_leg,
                )

        return HttpResponse(status=200)

    except json.JSONDecodeError:
        print("Invalid JSON in Uber webhook")
        return HttpResponse(status=200)
    except Exception as e:
        print(f"Uber webhook unexpected error: {str(e)}")
        return HttpResponse(status=200)


def _find_related_order(delivery: Delivery) -> Order | None:
    """
    Try to find the parent Order using relations or fallback fields.
    You can improve this later by adding reverse accessors if needed.
    """

    # Fallback to ID fields (temporary)
    try:
        from payment.models import Order
        return Order.objects.filter(
            Q(uber_pickup_delivery_id=delivery.delivery_uid) |
            Q(uber_return_delivery_id=delivery.delivery_uid)
        ).first()
    except Exception:
        return None


def full_service_status_mapping(return_leg: bool):
  """
  Maps Uber Delivery internal status → Order.status for full_service flow.
  return_leg=True means this is the return delivery (laundry → customer)
  """
  status_mapping = {
    "pending": "pickup_courier_scheduled" if not return_leg else "return_scheduled",

    # pickup leg (customer → laundry)
    "pickup_false": "pickup_courier_assigned",
    "pickup_true": "pickup_arriving_soon",
    "pickup_complete": "picked_up_by_courier",  # bag arrived at laundry

    # dropoff leg (laundry → customer)
    "dropoff_false": "moving_towards_customer" if return_leg else "moving_towards_laundrymart",
    "dropoff_true": "dropping_of_soon",
    "delivered": "picked_up_by_customer" if return_leg else "picked_up_by_laundrymart",

    "canceled": "canceled",
    "returned": "wait_for_support",  # or 'canceled' — your choice
  }
  return status_mapping

def pickup_service_status_mapping():
  """Only pickup leg exists (e.g. customer pickup-only service)"""
  status_mapping = {
    "pending": "pickup_courier_scheduled",
    "pickup_false": "pickup_courier_assigned",
    "pickup_true": "pickup_arriving_soon",
    "pickup_complete": "picked_up_by_courier",
    "dropoff_false": "moving_towards_customer",
    "dropoff_true": "dropping_of_soon",
    "delivered": "picked_up_by_customer",
    "canceled": "canceled",
    "returned": "wait_for_support",
  }
  return status_mapping

def drop_off_service_status_mapping():
  """Only drop-off leg exists (e.g. laundry → customer only)"""
  status_mapping = {
    "pending": "return_scheduled",  # or pickup_courier_scheduled — depending on naming
    "pickup_false": "pickup_courier_assigned",
    "pickup_true": "pickup_arriving_soon",
    "pickup_complete": "picked_up_by_laundrymart",  # courier picked up from laundry
    "dropoff_false": "moving_towards_customer",
    "dropoff_true": "dropping_of_soon",
    "delivered": "picked_up_by_customer",
    "canceled": "canceled",
    "returned": "wait_for_support",
  }
  return status_mapping

def _update_order_status_based_on_delivery(
  order: Order,
  delivery: Delivery,
  new_status: str,
  service_type: str,
  return_leg: bool,
):
  mapping = {
    "pending": "pickup_courier_scheduled",
    "pickup_false": "pickup_courier_assigned",
    "pickup_true": "pickup_arriving_soon",
    "pickup_complete": "picked_up_by_courier",
    "dropoff_false": "moving_towards_customer" if return_leg else "moving_towards_laundrymart",
    "dropoff_true": "dropping_of_soon",
    "delivered": "picked_up_by_customer" if return_leg else "picked_up_by_laundrymart",
    "canceled": "canceled",
    "returned": "wait_for_support",
  }

  # Service-type specific overrides (rare)
  if service_type == "drop_off" and new_status == "pending":
    mapping["pending"] = "return_scheduled"
  elif service_type == "drop_off" and new_status == "pickup_complete":
    mapping["pickup_complete"] = "picked_up_by_laundrymart"

  new_status = mapping.get(new_status, order.status)  # fallback to current

  if order.status != new_status:
    order.status = new_status
    order.save(update_fields=['status', 'updated_at'])

  return order.status




