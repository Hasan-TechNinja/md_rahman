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

    print("Uber webhook triggered")

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
            # 1. Get and lock the Delivery record
            try:
                uber_delivery = Delivery.objects.select_for_update().get(delivery_uid=delivery_id)
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

            uber_delivery.status = new_status
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
            if order:
                _update_order_status_based_on_delivery(
                    order,
                    uber_delivery,
                    new_status,
                    courier_imminent
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
    # Preferred way (if you add related_name)
    if hasattr(delivery, 'order_as_pickup') and delivery.order_as_pickup:
        return delivery.order_as_pickup

    if hasattr(delivery, 'order_as_return') and delivery.order_as_return:
        return delivery.order_as_return

    # Fallback to ID fields (temporary)
    try:
        from payment.models import Order
        return Order.objects.filter(
            Q(uber_pickup_delivery_id=delivery.delivery_uid) |
            Q(uber_return_delivery_id=delivery.delivery_uid)
        ).first()
    except Exception:
        return None


def _update_order_status_based_on_delivery(
    order: Order,
    delivery: Delivery,
    new_status: str,
    courier_imminent: bool
):
    """
    Map Uber delivery status → Order status
    Customize according to your business needs
    """
    is_pickup_leg = (order.pickup_delivery == delivery)
    is_return_leg = (order.return_delivery == delivery)

    if not (is_pickup_leg or is_return_leg):
        return  # unknown relationship

    prefix = "Pickup" if is_pickup_leg else "Return"

    status_mapping = {
        "pending":              f"{prefix} Pending",
        "pickup":               f"{prefix} En Route" if courier_imminent else f"{prefix} Arrived at Pickup",
        "pickup_complete":      f"{prefix} Complete",
        "dropoff":              f"{prefix} En Route" if courier_imminent else f"{prefix} Arriving",
        "delivered":            "Completed" if is_return_leg else "Ready for Processing",
        "canceled":             "Canceled",
        # Add more Uber statuses you care about
    }

    new_order_status = status_mapping.get(new_status)
    if new_order_status and order.status != new_order_status:
        order.status = new_order_status
        order.save(update_fields=["status"])
        print(f"Order {order.uuid} status updated to: {new_order_status}")
