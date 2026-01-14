from datetime import timedelta
from decimal import Decimal

import humanize
import stripe
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import LaundrymartStore
from customer.serializers import CustomerOrderReportSerializer
from customer_push_notification.utils import customer_receive_accept_notification, \
  customer_receive_delivery_picked_up_notification, customer_receive_order_weighed_notification, \
  customer_receive_payment_failed_notification, customer_receive_payment_success_notification, \
  customer_receive_reject_notification
from laundrymart.permissions import IsStaff
from payment.models import Order, SavedPaymentMethod
from uber.models import DeliveryQuote, ManifestItem
from uber.serializers import CreateDeliverySerializer, ManifestItemSerializer
from uber.utils import cancel_uber_delivery, create_and_save_delivery
from vendor.models import OrderReportImage
from vendor.serializers import DashboardSerializer, OrderDetailSerializer, OrderWeightSerializer, \
  VendorOrderReportSerializer
from .tasks import process_order_completion

class AcceptQuoteAPIView(APIView):
  permission_classes = [IsStaff]  # ← use your real permission

  @transaction.atomic
  def patch(self, request, quote_id):
    quote = get_object_or_404(DeliveryQuote, pk=quote_id)

    if not hasattr(request.user, 'laundrymart_store') or \
        str(request.user.laundrymart_store.store_id) != str(quote.external_store_id):
      return Response({"error": "Unauthorized for this quote"}, status=403)

    if quote.status != 'pending':
      raise ValidationError(
        f"Quote must be in pending status to accept (current: {quote.status})"
      )

    store = get_object_or_404(LaundrymartStore, store_id=quote.external_store_id)

    pickup_delivery = None
    uber_pickup_quote_id = None
    uber_pickup_delivery_id = None

    # ────────────────────────────────────────────────
    # Create immediate pickup delivery ONLY for drop_off & full_service
    # ────────────────────────────────────────────────
    if quote.service_type in ['drop_off', 'full_service']:
      quote_data = {
        "quote_id": quote.quote_id,
        "pickup_name": store.laundrymart_name,
        "pickup_address": quote.pickup_address,
        "pickup_phone_number": quote.pickup_phone_number,
        "pickup_latitude": quote.pickup_latitude,
        "pickup_longitude": quote.pickup_longitude,
        "dropoff_name": quote.customer.full_name or quote.customer.phone_number or "Customer",
        "dropoff_address": quote.dropoff_address,
        "dropoff_phone_number": quote.dropoff_phone_number,
        "dropoff_latitude": quote.dropoff_latitude,
        "dropoff_longitude": quote.dropoff_longitude,
        "deliverable_action": "deliverable_action_meet_at_door",  # or take from quote if you store it
        "external_store_id": quote.external_store_id,
        "manifest_total_value": int(quote.manifest_total_value or 0) * 100,  # cents if Uber expects cents
        "manifest_items": [],
      }

      manifest_items = ManifestItem.objects.filter(delivery_quote=quote)
      quote_data["manifest_items"] = ManifestItemSerializer(manifest_items, many=True).data

      serializer = CreateDeliverySerializer(data=quote_data)
      serializer.is_valid(raise_exception=True)

      pickup_delivery = create_and_save_delivery(  # ← your existing function
        user=quote.customer,
        validated_data=serializer.validated_data,
        payload=serializer.validated_data,
        is_return_leg=False
      )

      # Re-link manifest items to the real delivery
      manifest_items.update(delivery=pickup_delivery)

      # Final touches on delivery object
      pickup_delivery.quote = quote
      pickup_delivery.quote_uid = quote.quote_id
      pickup_delivery.pickup_ready = quote.pickup_ready_dt
      pickup_delivery.pickup_name = store.laundrymart_name
      pickup_delivery.save(update_fields=[
        'quote', 'quote_uid', 'pickup_ready', 'pickup_name'
      ])

      uber_pickup_quote_id = quote.quote_id
      uber_pickup_delivery_id = pickup_delivery.delivery_uid

    # ────────────────────────────────────────────────
    # Always create the Order
    # ────────────────────────────────────────────────
    order = Order.objects.create(
      user=quote.customer,
      service_provider=store,
      pickup_address=quote.pickup_address,
      dropoff_address=quote.dropoff_address,
      pickup_latitude=quote.pickup_latitude,
      pickup_longitude=quote.pickup_longitude,
      dropoff_latitude=quote.dropoff_latitude,
      dropoff_longitude=quote.dropoff_longitude,
      customer_note=quote.customer_note or "",
      uber_pickup_quote_id=uber_pickup_quote_id,
      uber_pickup_delivery_id=uber_pickup_delivery_id,
      pickup_deivery=pickup_delivery,  # will be None for pickup type
      stripe_customer_id=quote.customer.stripe_customer_id,
      stripe_default_pm_id=quote.payment_method_id,  # usually updated later
      status='card_saved',  # adjust to your preferred initial status
    )

    # Accept quote
    quote.status = 'accepted'
    quote.save(update_fields=['status'])

    # Optional: send notification
    # customer_receive_accept_notification(order, quote.customer)

    response_data = {
      "success": True,
      "quote_id": quote.quote_id,
      "order_uuid": str(order.uuid),
      "order_status": order.status,
      "service_type": quote.service_type,
      "pickup_delivery_created": pickup_delivery is not None,
    }

    if pickup_delivery:
      response_data.update({
        "pickup_delivery_uid": pickup_delivery.delivery_uid,
        "tracking_url": pickup_delivery.tracking_url,
        "fee": str(pickup_delivery.fee) if pickup_delivery.fee else None,
      })

    return Response(response_data, status=status.HTTP_200_OK)

class RejectQuoteAPIView(APIView):
  permission_classes = [IsStaff]
  def patch(self, request, quote_id):
    quote = get_object_or_404(DeliveryQuote, pk=quote_id)

    # Permission check
    if not hasattr(request.user, 'laundrymart_store') or str(request.user.laundrymart_store.store_id) != str(quote.external_store_id):
      return Response({"error": "Unauthorized for this quote"}, status=403)

    if quote.status != 'pending':
      raise ValidationError(f"Quote must be pending to accept (current: {quote.get_status_display()})")
    quote.status = 'rejected'
    quote.save(update_fields=['status'])
    customer_receive_reject_notification(quote, quote.customer.full_name)


    return Response({
      "success": True,
      "quote_id": quote.quote_id,
      "message": "Quote rejected successfully"
    }, status=status.HTTP_200_OK)



class DashboardAPIView(APIView):
  permission_classes = [IsStaff]

  def get(self, request):
    user = request.user
    print ("User:", user.email)
    associated_laundrymart = user.laundrymart_store
    current_month = timezone.now().month
    current_year = timezone.now().year
    today = timezone.now().date()
    seven_days_ago = today - timedelta(days=6)

    print("Associated Laundrymart:", associated_laundrymart)
    if not associated_laundrymart:
      return Response({"error": "No associated Laundrymart store found."}, status=status.HTTP_404_NOT_FOUND)
    store_uuid=associated_laundrymart.store_id
    context = {
      'request': request,
      'store_uuid': store_uuid,
      'associated_laundrymart': associated_laundrymart,
      'current_month': current_month,
      'current_year': current_year,
      'last_seven_days_start': seven_days_ago,
      'last_seven_days_end': today,
      }
    serializer = DashboardSerializer(user,context=context)
    print("Serialized Data:", serializer.data)
    return Response(serializer.data, status=status.HTTP_200_OK)

class StandardResultsSetPagination(PageNumberPagination):
  page_size = 10
  page_size_query_param = 'page_size'
  max_page_size = 100

class VendorOrdersListAPIView(APIView):
  permission_classes = [IsStaff]
  pagination_class = StandardResultsSetPagination
  @extend_schema(
    parameters=[
      OpenApiParameter(
        name='filter',
        description='Filter orders by status: pending, active, delivered',
        required=False,
        type=str
      )
    ]
  )

  def get(self, request):
    filter_type = request.query_params.get('filter', 'pending').lower()

    user = request.user
    print(user)

    try:

      store = user.laundrymart_store
      print(store)
      external_store_id = store.store_id
      print(external_store_id)
    except AttributeError:
      return Response({"error": "Laundrymart store not linked to this user"}, status=400)

    # We'll collect unified results with a creation timestamp for sorting
    results = []

    if filter_type == 'pending':
      quotes_qs = DeliveryQuote.objects.filter(
        external_store_id=external_store_id,
        status='pending'
      ).select_related('customer').prefetch_related('manifest_items').order_by('-saved_at')

      paginator = self.pagination_class()
      page = paginator.paginate_queryset(quotes_qs, request)
      if page is None:
        return Response({"error": "Pagination error"}, status=400)

      for quote in page:
        time_ago = humanize.naturaltime(timezone.now() - quote.saved_at)

        results.append({
          "id": None,
          "uuid": None,  # no UUID for quotes
          "order_id": None,  # frontend uses this as identifier
          "phone_number": quote.customer.phone_number,
          "email": quote.customer.email,
          "time_ago": time_ago,
          "customer_note": quote.customer_note,
          "status": quote.get_status_display(),
          "vendor_report":VendorOrderReportSerializer(quote.vendor_filed_report, context={'request':request}).data if hasattr(quote, 'vendor_filed_report') else None,
          "customer_report":CustomerOrderReportSerializer(quote.customer_filed_report, context={'request':request}).data if hasattr(quote, 'customer_filed_report') else None,

          "user": quote.customer.full_name or quote.customer.phone_number or quote.customer.email,
          # "service_provider": store.laundrymart_name or user.full_name,  # if needed
          "manifest_items": ManifestItemSerializer(quote.manifest_items.all(), many=True).data,
          "service": quote.get_service_type_display(),
          "total_cost": None,
          "vendor_fee": quote.fee / Decimal('100') if quote.fee else None,
          "address": quote.dropoff_address or quote.pickup_address,
          "is_quote": True,
          "uber_quote_id": quote.quote_id,
          "estimated_delivery_time": quote.dropoff_eta.isoformat() if quote.dropoff_eta else None,
          "duration": quote.duration,

          "quote_id":quote.id,
          "expires": quote.expires.isoformat() if quote.expires else None,
          "created_at": quote.saved_at.isoformat(),
        })

    elif filter_type in ['active', 'delivered']:
      status_list = (
        ['card_saved', 'picked_up', 'weighed', 'charged', 'return_scheduled']
        if filter_type == 'active'
        else ['completed']
      )

      orders_qs = Order.objects.filter(
        service_provider=store,
        status__in=status_list
      ).select_related('user', 'service_provider').prefetch_related('manifest_items') \
        .order_by('-created_at')

      paginator = self.pagination_class()
      page = paginator.paginate_queryset(orders_qs, request)
      if page is None:
        return Response({"error": "Pagination error"}, status=400)

      for order in page:
        time_ago = humanize.naturaltime(timezone.now() - order.created_at)

        results.append({
          "id": order.id,
          "uuid": str(order.uuid),
          "order_id": str(order.uuid),  # consistent with frontend expectation
          "phone_number": order.user.phone_number or order.user.email,
          "customer_note": order.customer_note,
          "email": order.user.email,
          "time_ago": time_ago,
          "status": order.get_status_display(),
          "user": str(order.user),  # or order.user.full_name / email if you prefer
          "vendor_report":VendorOrderReportSerializer(order.vendor_filed_report, context={'request':request}).data if hasattr(order, 'vendor_filed_report') else None,
          "customer_report":CustomerOrderReportSerializer(order.customer_filed_report, context={'request':request}).data if hasattr(order, 'customer_filed_report') else None,
          # "service_provider": store.laundrymart_name,
          "manifest_items": ManifestItemSerializer(order.manifest_items.all(), many=True).data,
          # "service": order.q,  # or add a field later if needed
          "total_cost": order.final_total_cents / Decimal('100') if order.final_total_cents else None,
          "vendor_fee": order.delivery_fee_cents / Decimal('100') if order.delivery_fee_cents else None,
          "address": order.dropoff_address or order.pickup_address,
          "is_quote": False,
          "uber_quote_id": None,
          "quote_id": None,
          "expires": None,
          "created_at": order.created_at.isoformat(),
        })

    else:
      return Response({"error": "Invalid filter. Use: pending, active, delivered"}, status=400)

    return paginator.get_paginated_response({
      "closes_today":store.closes_at,
      "results": results,
      "filter": filter_type,
    })


class VendorOrderReportAPIView(APIView):
  permission_classes = [IsStaff]  # Ensure the user is authenticated and a staff member

  def post(self, request):
    try:
      # Extract the data from the request
      data = request.data

      # Deserialize the order report data (including images)
      serializer = VendorOrderReportSerializer(data=data)

      # Validate the serializer and create the OrderReport if valid
      if serializer.is_valid():

        order_report = serializer.save()

        # Return the created order report details along with images
        return Response(serializer.data, status=status.HTTP_201_CREATED)
      else:
        # If validation fails, return validation errors
        errors = serializer.errors
        field, messages = next(iter(errors.items()))
        readable_field = field.replace('_', ' ').capitalize()
        first_message = messages[0] if isinstance(messages, list) else messages
        error_message = f"{readable_field}: {first_message}"
        return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)

    except ValidationError as e:
      # Handle any validation errors or other issues
      return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

@permission_classes([IsStaff])  # IsStaff is not standard; we'll check manually
@api_view(['PATCH'])
def mark_order_as_received(request, order_id):
    """
    Vendor marks laundry as picked up from customer.
    Only allowed when status is 'card_saved' (pickup delivery completed, items at store).
    """
    order = get_object_or_404(Order, pk=order_id)

    user = request.user

    # Permission: must belong to the store that received this order
    if not hasattr(user, 'laundrymart_store') or \
       str(user.laundrymart_store.store_id) != str(order.service_provider.store_id):
        return Response(
            {"error": "You are not authorized to modify this order."},
            status=status.HTTP_403_FORBIDDEN
        )
    service_type = order.get_service_type()

    # Status validation
    if service_type not in ['drop_off', 'full_service'] and order.pickup_delivery.status != 'delivered':
        return Response(
            {
                "error": "Cannot mark as picked up",
                "detail": f"Order is in '{order.get_status_display()}' status. "
                          f"Must be 'Card Saved – Awaiting Pickup' to proceed."
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    if service_type == 'pickup' and order.status != 'card_saved':
      return Response({'error':'Cannot mark as picked up',
                       "detail":f"Order is in '{order.get_status_display()}' status. Must be 'Card Saved – Awaiting Pickup' to proceed."
                       })


    # Atomic update
    with transaction.atomic():
        order.status = 'picked_up'
        order.save(update_fields=['status'])
    customer_receive_delivery_picked_up_notification(order, order.user)

    return Response(
        {
            "success": True,
            "order_id": str(order.uuid),
            "new_status": order.get_status_display(),
            "message": "Laundry marked as picked up. You can now weigh and price the items."
        },
        status=status.HTTP_200_OK
    )

@permission_classes([IsStaff])
@api_view(['PATCH'])
def save_final_order_weight(request, order_id):
    """
    Vendor saves the final weighed weight and calculates charges.
    Only allowed when order is in 'picked_up' status.
    """
    order = get_object_or_404(Order, pk=order_id)

    user = request.user

    # Permission: must belong to the store that received this order
    if not hasattr(user, 'laundrymart_store') or \
       str(user.laundrymart_store.store_id) != str(order.service_provider.store_id):
        return Response(
            {"error": "You are not authorized to modify this order."},
            status=status.HTTP_403_FORBIDDEN
        )

    # Status check
    if order.status != 'picked_up':
        return Response(
            {
                "error": "Cannot save weight yet",
                "detail": f"Order is in '{order.get_status_display()}' status. "
                          f"Must be 'Picked Up' to weigh and price."
            },
            status=status.HTTP_400_BAD_REQUEST
        )

    serializer = OrderWeightSerializer(order, data=request.data, partial=True)

    if not serializer.is_valid():
        errors = serializer.errors
        field, messages = next(iter(errors.items()))
        readable_field = field.replace('_', ' ').capitalize()
        first_message = messages[0] if isinstance(messages, list) else messages
        error_message = f"{readable_field}: {first_message}"
        return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)


    with transaction.atomic():
        # Save the validated fields
        serializer.save()

        # # Recalculate final_total_cents if needed
        # # Assuming delivery_fee_cents is already set from Uber quote
        # service_cents = order.service_charge_cents or 0
        # delivery_cents = order.delivery_fee_cents or 0
        #
        # order.save(update_fields=['final_total_cents'])

        # Optional: move to next logical status
        # You can decide whether to do this here or in a separate endpoint
        order.status = 'weighed'
        order.save(update_fields=['status'])

        customer_receive_order_weighed_notification(order, order.user)


    # Return updated order data
    return Response(
        {
            "success": True,
            "order_id": str(order.uuid),
            "weight_in_pounds": str(order.weight_in_pounds) if order.weight_in_pounds else None,
            "service_charge_cents": order.service_charge_cents,
            "delivery_fee_cents": order.delivery_fee_cents,
            "final_total_cents": order.final_total_cents,
            "message": "Weight and charges saved successfully."
        },
        status=status.HTTP_200_OK
    )

@api_view(['PATCH'])
@permission_classes([IsStaff])  # adjust as needed
def mark_order_as_completed(request, order_id):
    order = get_object_or_404(Order, pk=order_id)

    # Authorization
    if not hasattr(request.user, 'laundrymart_store') or \
       request.user.laundrymart_store != order.service_provider:
        return Response({"error": "Not authorized for this store's order"}, status=403)

    if order.status != 'weighed':
        return Response({
            "error": f"Cannot complete from status '{order.get_status_display()}'"
        }, status=400)

    # Transitional state — gives visual feedback
    order.status = 'processing_completion'
    order.save(update_fields=['status'])

    # Fire & forget
    process_order_completion.delay(str(order.id))   # better to pass uuid than pk

    return Response({
        "success": True,
        "message": "Order completion started. We'll notify you when finished.",
        "order_status": order.status,
        "order_uuid": str(order.uuid)
    }, status=202)   # 202 Accepted is semantically nice here
