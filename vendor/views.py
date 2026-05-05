import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import humanize
import stripe
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import models, transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, IntegerField, Sum, Value
from django.db.models.functions import Cast, Coalesce, ExtractHour, Floor, TruncDay, TruncMonth
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from unfold.views import UnfoldModelAdminViewMixin

from accounts.models import LaundrymartStore, User
from admin_panel.models import GlobalManifest
from customer.serializers import CustomerOrderReportSerializer, ProgressionSerializer
from customer.tasks import auto_assign_another_laundrymart
from customer_push_notification.utils import customer_receive_accept_notification, \
  customer_receive_delivery_picked_up_notification, customer_receive_order_weighed_notification, \
  customer_receive_payment_failed_notification, customer_receive_payment_success_notification, \
  customer_receive_reject_notification
from laundrymart.permissions import IsEmployee, IsStaff
from laundrymart.settings import STRIPE_PUBLISHABLE_KEY, UBER_CUSTOMER_ID
from payment.models import LaundrymartPaymentMethod, Order, SavedPaymentMethod
from uber.models import DeliveryQuote, ManifestItem
from uber.serializers import CreateDeliverySerializer, ManifestItemSerializer
from uber.utils import cancel_uber_delivery, create_and_save_delivery
from vendor.serializers import DashboardSerializer, OrderWeightSerializer, \
  VendorGlobalManifestSerializer, VendorOrderReportSerializer
from .tasks import process_order_completion
import logging
logger = logging.getLogger(__name__)

class AcceptQuoteAPIView(APIView):
  permission_classes = [IsEmployee]  # ← use your real permission

  @transaction.atomic
  def patch(self, request, quote_id):
    quote = get_object_or_404(DeliveryQuote, pk=quote_id)
    now = timezone.now()

    if not hasattr(request.employee, 'laundrymart_store') or \
        str(request.employee.laundrymart_store.store_id) != str(quote.external_store_id):
      return Response({"error": "Unauthorized for this quote"}, status=403)

    # if quote.expires < timezone.now():
    #   return Response({'error':'Order has expired.'}, status=400)
    if quote.status != 'pending':
      raise ValidationError(f"Quote must be in pending status (current: {quote.status})")
    # Check if 9 minutes have passed since the quote was saved
    if now - quote.saved_at > timedelta(minutes=9):
      # Update the quote's status to 'delayed'
      quote.status = 'delayed'
      quote.save()  # Save the changes to the database
      return Response({'error':'Quote has expired. This order has been marked as delayed'})

    store = request.employee.laundrymart_store  # already checked → safe to use

    pickup_delivery = None
    uber_pickup_quote_id = None
    uber_pickup_delivery_id = None

    # ────────────────────────────────────────────────
    # 1. Create the Order + link quote + set status (DB first)
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
      uber_pickup_quote_id=quote.quote_id,  # we plan to use it
      stripe_customer_id=quote.customer.stripe_customer_id,
      stripe_default_pm_id=quote.payment_method_id,
      estimated_value=quote.manifest_total_value,
      status='processing',  # intermediate state
    )
    logger.info('attempting to call the create progress button')
    order.create_progress_steps()

    # Accept quote in DB
    quote.status = 'accepted'
    quote.save(update_fields=['status'])
    manifest_items = ManifestItem.objects.filter(delivery_quote=quote)
    manifest_items.update(stripe_order=order)


    if quote.service_type in ['drop_off', 'full_service']:

      # Prepare payload (same as before)
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
        "deliverable_action": "deliverable_action_meet_at_door",
        "external_store_id": quote.external_store_id,
        "manifest_total_value": int(quote.manifest_total_value or 0) * 100,
        "manifest_items": [],
      }

      quote_data["manifest_items"] = ManifestItemSerializer(manifest_items, many=True).data

      serializer = CreateDeliverySerializer(data=quote_data)
      serializer.is_valid(raise_exception=True)

      try:
        # This should be outside @transaction.atomic or use on_commit
        logger.info(f'validated data:{serializer.validated_data}')
        logger.info(f'payload {serializer.validated_data}')
        pickup_delivery = create_and_save_delivery(
          user=quote.customer,
          validated_data=serializer.validated_data,
          payload=serializer.validated_data,
          is_return_leg=False
        )

        # Re-link manifest items
        manifest_items.update(delivery=pickup_delivery)

        # Update delivery & order
        pickup_delivery.quote = quote
        pickup_delivery.quote_uid = quote.quote_id
        pickup_delivery.pickup_ready = quote.pickup_ready_dt
        pickup_delivery.pickup_name = store.laundrymart_name
        pickup_delivery.save(update_fields=['quote', 'quote_uid', 'pickup_ready', 'pickup_name'])

        # Update order with delivery reference
        order.uber_pickup_delivery_id = pickup_delivery.delivery_uid
        order.pickup_delivery = pickup_delivery
        order.delivery_fee_cents = pickup_delivery.fee
        order.status = 'card_saved'  # or 'pickup_scheduled'
        order.save(update_fields=['uber_pickup_delivery_id', 'pickup_delivery','delivery_fee_cents', 'status'])

      except Exception as e:
        # Uber creation failed → order stays in 'processing' or set to failed state
        order.status = 'pickup_creation_failed'
        order.save(update_fields=['status'])

        return Response({
          "success": False,
          "message": f"Quote accepted and order created, but Uber pickup scheduling failed: {str(e)}",
          "order_uuid": str(order.uuid),
          "order_status": order.status,
        }, status=status.HTTP_202_ACCEPTED)  # 202 = accepted but processing incomplete

    # Success path
    customer_receive_accept_notification(quote, quote.customer, order)
    response_data = {
      "success": True,
      "quote_id": quote.quote_id,
      "order_uuid": str(order.uuid),
      "order_status": order.status,
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
  permission_classes = [IsEmployee]
  @transaction.atomic
  def patch(self, request, quote_id):
    quote = get_object_or_404(DeliveryQuote, pk=quote_id)

    # Permission check
    if not hasattr(request.employee, 'laundrymart_store') or str(request.employee.laundrymart_store.store_id) != str(quote.external_store_id):
      return Response({"error": "Unauthorized for this quote"}, status=403)

    if quote.status != 'pending':
      raise ValidationError(f"Quote must be pending to accept (current: {quote.get_status_display()})")
    quote.status = 'rejected'
    quote.save(update_fields=['status'])
    customer_receive_reject_notification(quote, quote.customer)
    if quote.customer.preference == 'Auto-assign another LaundryMart (fastest)':
      auto_assign_another_laundrymart.delay(quote.id, UBER_CUSTOMER_ID)

    return Response({
      "success": True,
      "quote_id": quote.quote_id,
      "message": "Quote rejected successfully"
    }, status=status.HTTP_200_OK)



class DashboardAPIView(APIView):
  permission_classes = [IsEmployee]

  def get(self, request):
    user = request.employee
    logger.info (f"User:{user.email}")
    associated_laundrymart = user.laundrymart_store
    current_month = timezone.now().month
    current_year = timezone.now().year
    today = timezone.now().date()
    seven_days_ago = today - timedelta(days=6)

    logger.info(f"Associated Laundrymart:{associated_laundrymart}")
    if not associated_laundrymart:
      return Response({"error": "No associated Laundrymart store found."}, status=status.HTTP_404_NOT_FOUND)
    store_uuid=associated_laundrymart.store_id
    logger.info(associated_laundrymart)
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
    logger.info(f"Serialized Data: {serializer.data}")
    return Response(serializer.data, status=status.HTTP_200_OK)

class StandardResultsSetPagination(PageNumberPagination):
  page_size = 10
  page_size_query_param = 'page_size'
  max_page_size = 100

class VendorOrdersListAPIView(APIView):
  permission_classes = [IsEmployee]
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

    user = request.employee
    logger.info(user)

    try:

      store = user.laundrymart_store
      logger.info(store)
      external_store_id = store.store_id
      logger.info(external_store_id)
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
          "id": quote.id,
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
          "delivery_fee": quote.fee / Decimal('100') if quote.fee else None,
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
        ['processing', 'card_saved', 'pickup_courier_scheduled', 'pickup_courier_assigned', 'pickup_arriving_soon',
         'picked_up_by_courier', 'moving_towards_laundrymart', 'moving_towards_customer', 'arrived_at_laundry',
         'received', 'weighed', 'charged', 'processing_laundry', 'picked_up_by_customer','awaiting_pickup',
         'processing_completion', 'ready_for_pickup', 'dropping_of_soon', 'picked_up_by_laundrymart',
         'return_scheduled', 'return_courier_assigned', 'return_arriving_soon']
        if filter_type == 'active'
        else ['completed', 'wait_for_support']
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
          "service": order.get_service_type(),  # or add a field later if needed
          "total_cost": order.final_total_cents / Decimal('100') if order.final_total_cents else None,
          "delivery_fee": order.delivery_fee_cents / Decimal('100') if order.delivery_fee_cents else None,
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
      "price_per_pound": store.price_per_pound,
      "results": results,
      "filter": filter_type,
    })

class VendorOrderDetailAPIView(APIView):
  permission_classes = [IsEmployee]

  def get(self, request, type, id):
    record_type = type
    record_id = id
    if type not in ['quote', 'order']:
      return Response({"error": "Invalid type. Must be 'quote' or 'order'"}, status=400)

    if not record_type or not record_id:
      return Response(
        {"error": "Both 'type' and 'id' query parameters are required"},
        status=status.HTTP_400_BAD_REQUEST
      )

    if record_type not in ('quote', 'order'):
      return Response(
        {"error": "Invalid type. Must be 'quote' or 'order'"},
        status=status.HTTP_400_BAD_REQUEST
      )

    try:
      record_id = int(record_id)
    except (ValueError, TypeError):
      return Response(
        {"error": "'id' must be a valid integer"},
        status=status.HTTP_400_BAD_REQUEST
      )

    user = request.employee

    try:
      store = user.laundrymart_store
      external_store_id = store.store_id
    except AttributeError:
      return Response(
        {"error": "Laundrymart store not linked to this employee"},
        status=status.HTTP_400_BAD_REQUEST
      )

    # ────────────────────────────────────────────────
    #  QUOTE branch
    # ────────────────────────────────────────────────
    if record_type == 'quote':
      try:
        quote = DeliveryQuote.objects.select_related(
          'customer'
        ).prefetch_related(
          'manifest_items'
        ).get(
          id=record_id,
          external_store_id=external_store_id,
          status='pending'  # usually we only show pending quotes
        )
      except DeliveryQuote.DoesNotExist:
        return Response(
          {"error": "Quote not found or not accessible"},
          status=status.HTTP_404_NOT_FOUND
        )

      time_ago = humanize.naturaltime(timezone.now() - quote.saved_at)

      data = {
        "type": "quote",
        "id": quote.id,
        "uuid": None,
        "order_id": None,
        "quote_id": quote.id,
        "uber_quote_id": quote.quote_id,
        "phone_number": quote.customer.phone_number,
        "email": quote.customer.email,
        "customer_name": quote.customer.full_name or quote.customer.phone_number or quote.customer.email,
        "time_ago": time_ago,
        "created_at": quote.saved_at.isoformat(),
        "customer_note": quote.customer_note,
        "status": quote.get_status_display(),
        "service": quote.get_service_type_display(),
        "vendor_fee": quote.fee / Decimal('100') if quote.fee else None,
        "total_cost": None,
        "address": quote.dropoff_address or quote.pickup_address,
        "estimated_delivery_time": quote.dropoff_eta.isoformat() if quote.dropoff_eta else None,
        "duration": quote.duration,
        "expires": quote.expires.isoformat() if quote.expires else None,
        "manifest_items": ManifestItemSerializer(quote.manifest_items.all(), many=True).data,
        "vendor_report": (
          VendorOrderReportSerializer(quote.vendor_filed_report, context={'request': request}).data
          if hasattr(quote, 'vendor_filed_report') and quote.vendor_filed_report
          else None
        ),
        "customer_report": (
          CustomerOrderReportSerializer(quote.customer_filed_report, context={'request': request}).data
          if hasattr(quote, 'customer_filed_report') and quote.customer_filed_report
          else None
        ),
        "order_progressions": None,
        # store info if needed
        "store_name": store.laundrymart_name,
        "closes_today": store.closes_at,
      }

    # ────────────────────────────────────────────────
    #  ORDER branch
    # ────────────────────────────────────────────────
    else:  # 'order'
      try:
        order = Order.objects.select_related(
          'user', 'service_provider'
        ).prefetch_related(
          'manifest_items'
        ).get(
          id=record_id,
          service_provider=store,
        )
      except Order.DoesNotExist:
        return Response(
          {"error": "Order not found or not accessible"},
          status=status.HTTP_404_NOT_FOUND
        )

      time_ago = humanize.naturaltime(timezone.now() - order.created_at)

      data = {
        "type": "order",
        "id": order.id,
        "uuid": str(order.uuid),
        "order_id": str(order.uuid),  # what frontend usually expects
        "quote_id": None,
        "uber_quote_id": None,
        "phone_number": order.user.phone_number or order.user.email,
        "email": order.user.email,
        "customer_name": str(order.user),  # or .full_name if you have it
        "time_ago": time_ago,
        "created_at": order.created_at.isoformat(),
        "customer_note": order.customer_note,
        "status": order.get_status_display(),
        "service": order.get_service_type(),  # adjust if you have get_service_type_display()
        "total_cost": order.final_total_cents / Decimal('100') if order.final_total_cents else None,
        "vendor_fee": order.delivery_fee_cents / Decimal('100') if order.delivery_fee_cents else None,
        "address": order.dropoff_address or order.pickup_address,
        "manifest_items": ManifestItemSerializer(order.manifest_items.all(), many=True).data,
        "vendor_report": (
          VendorOrderReportSerializer(order.vendor_filed_report, context={'request': request}).data
          if hasattr(order, 'vendor_filed_report') and order.vendor_filed_report
          else None
        ),
        "customer_report": (
          CustomerOrderReportSerializer(order.customer_filed_report, context={'request': request}).data
          if hasattr(order, 'customer_filed_report') and order.customer_filed_report
          else None
        ),
        "order_progressions": ProgressionSerializer(order.progressions.all(),many=True, context={'request': request}).data,
        "store_name": store.laundrymart_name,
        "closes_today": store.closes_at,
      }

    return Response({
      "result": data,
      "filter_type": record_type,  # quote / order
      "price_per_pound": store.price_per_pound,
    })

class VendorOrderReportAPIView(APIView):
  permission_classes = [IsEmployee]  # Ensure the user is authenticated and a staff member
  @extend_schema(
    request=VendorOrderReportSerializer,
    responses={}
  )
  def post(self, request):
    try:
      # Extract the data from the request
      data = request.data
      laundrymart = request.employee.laundrymart_store

      # Deserialize the order report data (including images)
      serializer = VendorOrderReportSerializer(data=data, context={'request':request})

      # Validate the serializer and create the OrderReport if valid
      if serializer.is_valid():

        order_report = serializer.save(laundrymart=laundrymart)

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

@permission_classes([IsEmployee])  # IsStaff is not standard; we'll check manually
@api_view(['PATCH'])
def mark_order_as_received(request, order_id):
    """
    Vendor marks laundry as picked up from customer.
    Only allowed when status is 'card_saved' (pickup delivery completed, items at store).
    """
    order = get_object_or_404(Order, pk=order_id)

    user = request.employee

    # Permission: must belong to the store that received this order
    if not hasattr(user, 'laundrymart_store') or \
       str(user.laundrymart_store.store_id) != str(order.service_provider.store_id):
        return Response(
            {"error": "You are not authorized to modify this order."},
            status=status.HTTP_403_FORBIDDEN
        )
    service_type = order.get_service_type()

    # Status validation
    if service_type not in ['Drop off', 'Full service'] and order.status != 'arrived_at_laundry':
        return Response(
            {
                "error": "Cannot mark as picked up",
                "detail": f"Order is in '{order.get_status_display()}' status. "
                          f"Must be 'Card Saved – Awaiting Pickup' to proceed."
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    if service_type == 'Pick up' and order.status != 'card_saved':
      return Response({'error':'Cannot mark as picked up',
                       "detail":f"Order is in '{order.get_status_display()}' status. Must be 'Card Saved – Awaiting Pickup' to proceed."
                       })


    # Atomic update
    with transaction.atomic():
        order.status = 'received'
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

@extend_schema(request=OrderWeightSerializer)
@permission_classes([IsEmployee])
@api_view(['PATCH'])
def save_final_order_weight(request, order_id):
    """
    Vendor saves the final weighed weight and calculates charges.
    Only allowed when order is in 'picked_up' status.
    """
    order = get_object_or_404(Order, pk=order_id)

    user = request.employee

    # Permission: must belong to the store that received this order
    if not hasattr(user, 'laundrymart_store') or \
       str(user.laundrymart_store.store_id) != str(order.service_provider.store_id):
        return Response(
            {"error": "You are not authorized to modify this order."},
            status=status.HTTP_403_FORBIDDEN
        )

    # Status check
    if order.status != 'received':
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
@permission_classes([IsEmployee])  # adjust as needed
def mark_order_as_ready(request, order_id):
    order = get_object_or_404(Order, pk=order_id)

    # Authorization
    if not hasattr(request.employee, 'laundrymart_store') or \
       request.employee.laundrymart_store != order.service_provider:
        return Response({"error": "Not authorized for this store's order"}, status=403)

    if order.status != 'weighed':
        return Response({
            "error": f"Cannot complete from status '{order.get_status_display()}'"
        }, status=400)

    order.status = 'processing_completion'
    order.save(update_fields=['status'])

    logger.info(f"Order {order.id} marked as ready for completion. Triggering background processing.")
    process_order_completion.delay(order.id)

    return Response({
        "success": True,
        "message": "Order completion started. We'll notify you when finished.",
        "order_status": order.status,
        "order_uuid": str(order.uuid)
    }, status=202)

@api_view(['PATCH'])
@permission_classes([IsEmployee])
def mark_order_as_completed(request, order_id):
  order = get_object_or_404(Order, pk=order_id)

  # Authorization
  if not hasattr(request.employee, 'laundrymart_store') or \
      request.employee.laundrymart_store != order.service_provider:
    return Response({"error": "Not authorized for this store's order"}, status=403)
  service_type=order.get_service_type()
  if service_type not in ['Pick up', 'Full service']:
    return Response({'error':'Service type has to be Pick up or Full service'})
  if order.status != 'return_scheduled':
    return Response({"error": "Order hasn't arrived yet"}, status=403)
  order.status = 'completed'
  order.save(update_fields=['status'])
  return Response({'message':'Order has been marked as completed.'}, status=200)

class PaymentMethodsView(LoginRequiredMixin, UnfoldModelAdminViewMixin, TemplateView):
  title = "Manage your payment methods"
  template_name = 'admin_panels/vendor/payment_methods.html'
  permission_required=()

  # If using TemplateView, override get_context_data to add any extra
  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    user = self.request.user
    profile = LaundrymartStore.objects.filter(admin=user).only('stripe_customer_id').first()

    if profile and profile.stripe_customer_id:
      payment_methods = LaundrymartPaymentMethod.objects.filter(
        laundrymart_admin=user
      ).only(
        'id', 'brand', 'last4', 'exp_month', 'exp_year', 'is_default', 'created_at'
      ).order_by('-is_default', '-created_at')
    else:
      payment_methods = []

    context.update({
      'payment_methods': payment_methods,
      'has_customer': bool(profile and profile.stripe_customer_id),
      'stripe_publishable_key': STRIPE_PUBLISHABLE_KEY,
    })
    return context

class DeletePaymentMethodView(LoginRequiredMixin, UnfoldModelAdminViewMixin, View):
  permission_required = ()
  def post(self, request, pk):
    payment_method = get_object_or_404(
      LaundrymartPaymentMethod,
      pk=pk,
      laundrymart_admin=request.user
    )
    try:
      # 1. Detach from Stripe (official: POST /v1/payment_methods/{pm_id}/detach)
      stripe.PaymentMethod.detach(payment_method.stripe_payment_method_id)

      # 2. If it was default, optionally clear customer default (only matters for subs/invoices)
      profile = LaundrymartStore.objects.filter(admin=request.user).first()
      if profile and profile.stripe_customer_id:
        # Check if this was the customer's default
        customer = stripe.Customer.retrieve(profile.stripe_customer_id)
        if customer.invoice_settings.default_payment_method == payment_method.stripe_payment_method_id:
          stripe.Customer.modify(
            profile.stripe_customer_id,
            invoice_settings={"default_payment_method": None}
          )

      # 3. Delete local record
      payment_method.delete()

      messages.success(request, f"{payment_method} removed successfully.")
    except stripe.error.StripeError as e:
      messages.error(request, f"Stripe error: {e.user_message or str(e)}")
    except Exception as e:
      messages.error(request, "An error occurred while removing the card.")

    return HttpResponseRedirect(reverse_lazy('admin:vendor_payment_methods'))

class SetDefaultPaymentMethodView(LoginRequiredMixin, View):
  def post(self, request, pk):
    payment_method = get_object_or_404(
      LaundrymartPaymentMethod,
      pk=pk,
      laundrymart_admin=request.user
    )

    profile = get_object_or_404(LaundrymartStore, admin=request.user)

    if not profile.stripe_customer_id:
      messages.error(request, "No Stripe customer found.")
      return HttpResponseRedirect(reverse_lazy('vendor_payment_methods'))

    try:
      # Update customer's default for invoices/subscriptions
      stripe.Customer.modify(
        profile.stripe_customer_id,
        invoice_settings={
          "default_payment_method": payment_method.stripe_payment_method_id
        }
      )

      # Update local flags (optimized bulk update)
      LaundrymartPaymentMethod.objects.filter(
        laundrymart_admin=request.user
      ).update(is_default=False)

      payment_method.is_default = True
      payment_method.save(update_fields=['is_default'])

      messages.success(request, f"{payment_method} set as default.")
    except stripe.error.StripeError as e:
      messages.error(request, f"Stripe error: {e.user_message or str(e)}")

    return HttpResponseRedirect(reverse_lazy('vendor_payment_methods'))

class VendorSalesSummaryAPI(APIView):
  """
  GET /api/vendor/sales-summary/?start=2026-01-01&end=2026-02-28
  Returns daily aggregated orders count + revenue (final or estimated)
  Only returns data for stores owned by the authenticated vendor (staff)
  """
  permission_class = [AllowAny]
  @extend_schema(
    parameters=[
      OpenApiParameter(
        name='start',
        description='Start date of the custom range (YYYY-MM-DD). Use together with "end". Cannot be used with "generic_filters".',
        required=False,
        type=str,  # ← should be str, not datetime
      ),
      OpenApiParameter(
        name='end',
        description='End date of the custom range (YYYY-MM-DD). Use together with "start". Cannot be used with "generic_filters".',
        required=False,
        type=str,
      ),
      OpenApiParameter(
        name='generic_filters',
        description='Takes today, this month, this week, this year, last 30 days, last 7 days and last 365 days only',
        required=False,
        type=str,
        enum=['today', 'this_week', 'this_month', 'this_year', 'last_7_days', 'last_30_days', 'last_365_days'],
      )
    ]

  )
  def get(self, request, user_id):
    user = get_object_or_404(User, id=user_id)

    start_str = request.GET.get('start')
    end_str = request.GET.get('end')
    generic_filter = request.GET.get('generic_filters')

    # ── 1. Check mutual exclusivity ───────────────────────────────
    if (start_str or end_str) and generic_filter:
      return Response(
        {"error": "You cannot use 'start'/'end' together with 'generic_filters'. Choose one filtering method."},
        status=status.HTTP_400_BAD_REQUEST
      )

    # ── 2. Determine date range ───────────────────────────────────
    now = timezone.now()
    today = now.date()

    if generic_filter:
      match generic_filter.lower():
        case 'today':
          start_date = today
          end_date = today

        case 'this_week':
          # Assuming week starts on Monday (ISO week)
          start_date = today - timedelta(days=today.weekday())
          end_date = today

        case 'this_month':
          start_date = today.replace(day=1)
          end_date = today

        case 'this_year':
          start_date = today.replace(month=1, day=1)
          end_date = today

        case 'last_7_days':
          start_date = today - timedelta(days=7)
          end_date = today

        case 'last_30_days':
          start_date = today - timedelta(days=30)
          end_date = today

        case 'last_365_days':
          start_date = today - timedelta(days=365)
          end_date = today

        case _:
          return Response(
            {
              "error": f"Invalid generic_filters value. Allowed: today, this_week, this_month, this_year, last_7_days, last_30_days, last_365_days"},
            status=status.HTTP_400_BAD_REQUEST
          )

    elif start_str or end_str:
      # Custom range — both should be provided in most cases
      if not start_str or not end_str:
        return Response(
          {"error": "Both 'start' and 'end' are required when using custom date range."},
          status=status.HTTP_400_BAD_REQUEST
        )

      try:
        start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_str, '%Y-%m-%d').date()
      except ValueError:
        return Response(
          {"error": "Invalid date format. Use YYYY-MM-DD"},
          status=status.HTTP_400_BAD_REQUEST
        )

      if start_date > end_date:
        return Response(
          {"error": "start date cannot be after end date"},
          status=status.HTTP_400_BAD_REQUEST
        )

    else:
      # No filter provided → default to last 30 days
      start_date = today - timedelta(days=30)
      end_date = today

    # ── 3. Base queryset ──────────────────────────────────────────
    if user.is_superuser:
      qs = Order.objects.all()
    elif user.is_staff:
      try:
        owned_store_ids = list(user.owned_stores.values_list('id', flat=True))
        if owned_store_ids:
          qs = Order.objects.filter(service_provider__id__in=owned_store_ids)
        else:
          return Response({"labels": [], "datasets": []})
      except Exception:
        return Response({"labels": [], "datasets": []})
    else:
      # non-staff → empty
      return Response({"labels": [], "datasets": []})

    # ── 4. Date range filter (with aware datetimes) ───────────────
    start_dt = timezone.make_aware(datetime.combine(start_date, time.min))
    end_dt = timezone.make_aware(datetime.combine(end_date, time.max))
    qs = qs.filter(created_at__range=(start_dt, end_dt))

    # ── 5. Determine granularity based on range ───────────────────
    days_diff = (end_date - start_date).days + 1
    if days_diff >= 7:
      granularity = 'day'
    else:
      granularity = 'hour'
      if days_diff <= 1:
        hour_step = 1
      elif days_diff == 2:
        hour_step = 2
      elif days_diff == 3:
        hour_step = 3
      else:  # 4-6 days
        hour_step = 4

    # ── 6. Aggregation (optimized for granularity) ────────────────
    revenue_expr = Sum(
      Coalesce(
        'final_total_cents',
        Cast(
          ExpressionWrapper(F('estimated_value') * Value(100), output_field=DecimalField()),
          output_field=IntegerField()
        ),
        Value(0, output_field=IntegerField())
      )
    )

    if granularity == 'day':
      aggregated = (
        qs
        .annotate(slot=TruncDay('created_at'))
        .values('slot')
        .annotate(
          order_count=Count('id'),
          revenue_cents=revenue_expr
        )
        .order_by('slot')
      )
      aggregated_dict = {row['slot']: (row['order_count'], row['revenue_cents']) for row in aggregated}

    else:  # hour with step
      aggregated = (
        qs
        .annotate(
          day=TruncDay('created_at'),
          hour=ExtractHour('created_at'),  # 0–23
          hour_group=Floor(F('hour') / hour_step),  # 0, 0, 0, 0, 1, 1, 1, 1, ...
          group_start_hour=ExpressionWrapper(
            Floor(F('hour') / hour_step) * hour_step,
            output_field=IntegerField()
          )
        )
        .values('day', 'group_start_hour')
        .annotate(
          order_count=Count('id'),
          revenue_cents=revenue_expr
        )
        .order_by('day', 'group_start_hour')
      )

      aggregated_dict = {
        (row['day'], row['group_start_hour']): (row['order_count'], row['revenue_cents'])
        for row in aggregated
      }

    # ── 7. Generate labels and data with zeros included ──────────
    labels = []
    order_counts = []
    revenues = []

    if granularity == 'day':
      current_day = start_date
      while current_day <= end_date:
        slot_key = timezone.make_aware(datetime.combine(current_day, time.min))
        count, rev_cents = aggregated_dict.get(slot_key, (0, 0))
        labels.append(current_day.strftime('%Y-%m-%d'))
        order_counts.append(count)
        revenues.append(float(rev_cents or 0) / 100)
        current_day += timedelta(days=1)

    else:  # hour
      is_single_day = (days_diff == 1)
      current_day = start_date
      while current_day <= end_date:
        for gh in range(0, 24, hour_step):
          day_key = timezone.make_aware(datetime.combine(current_day, time.min))
          slot_key = (day_key, gh)
          count, rev_cents = aggregated_dict.get(slot_key, (0, 0))

          # Format label
          hour_12 = (gh % 12) or 12
          am_pm = 'am' if gh < 12 else 'pm'
          time_str = f"{hour_12} {am_pm}"
          if hour_step > 1:
            end_gh = min(gh + hour_step, 24)
            end_hour_12 = ((end_gh - 1) % 12) or 12
            end_am_pm = 'am' if (end_gh - 1) < 12 else 'pm'
            time_str = f"{time_str} - {end_hour_12} {end_am_pm}"
          if is_single_day:
            label = time_str
          else:
            label = f"{current_day.strftime('%Y-%m-%d')} {time_str}"

          labels.append(label)
          order_counts.append(count)
          revenues.append(float(rev_cents or 0) / 100)

        current_day += timedelta(days=1)

    # ── 8. Prepare response data ──────────────────────────────────
    total_orders = sum(order_counts)
    total_revenue_usd = sum(revenues)
    total_revenue_formatted = f"${total_revenue_usd:,.2f}"
    total_revenue_cents = int(total_revenue_usd * 100)
    data = {
      "labels": labels,
      "datasets": [
        {
          "label": "Orders",
          "data": order_counts,
          "borderColor": "#3b82f6",
          "backgroundColor": "rgba(59, 130, 246, 0.15)",
          "fill": True,
          "tension": 0.3,
          "pointRadius": 4,
          "yAxisID": "y-orders",
        },
        {
          "label": "Revenue (USD)",
          "data": revenues,
          "borderColor": "#64748b",
          "backgroundColor": "rgba(100, 116, 139, 0.12)",
          "fill": True,
          "tension": 0.3,
          "pointRadius": 4,
          "yAxisID": "y-revenue",
        }
      ]
    }

    return Response({'chart_data':data, "total_orders": total_orders,
    "total_revenue_usd": total_revenue_usd,
    "total_revenue_formatted": total_revenue_formatted,
    "total_revenue_cents": total_revenue_cents,})

class ReportSalesSummaryView(LoginRequiredMixin, UnfoldModelAdminViewMixin, TemplateView):
  title = "Sales summary"
  template_name = "admin_panels/vendor/sales_summary.html"

  permission_required = ()

  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    user = self.request.user
    id = user.id

    context.update({
      'user_id':id,

    })
    return context


class VendorGlobalManifestAPIView(APIView):
  """Endpoint for vendor employees. Requires IsEmployee permission."""
  permission_classes = [AllowAny]

  def get(self, request):
    manifest = GlobalManifest.get_cached_config()
    serializer = VendorGlobalManifestSerializer(manifest, context={'request': request})
    return Response(serializer.data)