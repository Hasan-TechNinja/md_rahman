from datetime import datetime
from decimal import Decimal

import humanize
from django.db.models import Avg, Case, FloatField, IntegerField, Q, Value, When

from django.db.models.functions import Coalesce
from django.utils import timezone

from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.generics import ListAPIView, get_object_or_404
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import LaundrymartStore, User
from admin_panel.models import GlobalManifest, SlideImage
from common_utils.distance_utils import calculate_distance_miles, calculate_distance_sql, get_best_location
from customer.models import OutOfServiceCustomers
from customer.serializers import CustomerGlobalManifestSerializer, CustomerOrderReportSerializer, ProgressionSerializer, \
  ReviewSerializer, \
  VendorSerializer
from laundrymart.permissions import IsCustomer
from payment.models import Order, OrderProgression
from uber.models import Delivery, DeliveryQuote
from uber.serializers import DeliveryQuoteCreateSerializer, ManifestItemSerializer
from vendor.serializers import OrderDetailSerializer, VendorOrderReportSerializer
from vendor.views import StandardResultsSetPagination
import logging
logger = logging.getLogger(__name__)


class VendorPagination(PageNumberPagination):
  page_size = 10
  page_size_query_param = 'page_size'
  max_page_size = 50

# Create your views here.
class VendorAPIView(ListAPIView):
  serializer_class = VendorSerializer
  permission_classes = [IsCustomer]
  pagination_class = VendorPagination
  filter_backends = [SearchFilter, OrderingFilter]

  search_fields = ['laundrymart_name','location']

  ordering_fields = ['google_rating','price_per_pound','distance']

  ordering = ['distance']  # default

  @extend_schema(
    parameters=[
      OpenApiParameter(
        name='lat',
        description='Latitude to calculate distance',
        required=False,
        type=float
      ),
      OpenApiParameter(
        name='lng',
        description='Longitude to calculate distance',
        required=False,
        type=float

      ),
      OpenApiParameter(
        name='ordering',
        description='distance, google_rating and price_per_pound. if descending order then add a - before them(example:-distance',
        required=False,
        type=str

      ),
    ]
  )
  def get(self, request, *args, **kwargs):
    queryset = self.get_queryset()

    if not queryset.exists():
      return Response({
        "detail": "No vendors found in your area. We have included your location in our system for future service availability."
      }, status=status.HTTP_404_NOT_FOUND)

    serializer = self.get_serializer(queryset, many=True)

    return Response(serializer.data)

  def get_serializer_context(self):
    context = super().get_serializer_context()
    context["request"] = self.request
    return context

  def get_queryset(self):
    user = self.request.user
    lat_param = self.request.query_params.get('lat')
    lng_param = self.request.query_params.get('lng')

    if lat_param and lng_param:
      try:
        lat = float(lat_param)
        lng = float(lng_param)
      except (TypeError, ValueError):
        raise ValidationError({"error": "Invalid latitude or longitude format."})
    else:
      if not user.lat or not user.lng:
        raise ValidationError({
          "error": "Please add your location first."
        })
      try:
        lat = float(user.lat)
        lng = float(user.lng)
      except (TypeError, ValueError):
        raise ValidationError({
          "error": "Your saved location is invalid. Please update it."
        })

    qs = LaundrymartStore.objects.annotate(
      has_no_location=Case(
        When(lat__isnull=True, then=Value(1)),
        When(lng__isnull=True, then=Value(1)),
        default=Value(0),
        output_field=IntegerField()
      )
    ).filter(stripe_connect_status=True)

    logger.info(f"Stripe connected vendors {qs}")

    if lat is not None and lng is not None:
      qs = qs.annotate(
        distance=Case(
          When(
            lat__isnull=False,
            lng__isnull=False,
            then=calculate_distance_sql(lat, lng)  # Placeholder for actual distance calculation logic
          ),
          default=Value(None),
          output_field=FloatField()
        )
      )
      logger.info(f"canditates: {qs}")
      qs = qs.filter(distance__lte=10)    

    if not qs.exists():
      # Save the user in OutOfServiceCustomers table
      out_of_service_cus = get_object_or_404(OutOfServiceCustomers, user=user)
      if out_of_service_cus:
        out_of_service_cus.lat = lat
        out_of_service_cus.lng = lng
        out_of_service_cus.save()
        return qs.none()  # Return empty queryset, to allow proper response handling
      OutOfServiceCustomers.objects.create(user = user, lat = lat, lng = lng)
      return qs.none()

    # Apply ordering based on query parameters
    ordering_param = self.request.query_params.get('ordering', '')
    if ordering_param:
      ordering_fields = ordering_param.split(',')
      qs = qs.order_by(*ordering_fields)

    return qs

class ChooseForCustomer(APIView):
  """
  API endpoint that automatically selects the cheapest LaundryMart (vendor)
  within a 10-mile radius of the customer's saved location (user.lat / user.lng).

  - Uses the customer's saved lat/lng directly (no query params needed)
  - Uses your existing calculate_distance_sql function for distance calculation
  - Prioritizes lowest price_per_pound among vendors with valid price and coordinates
  - Returns 404 if no vendor found within 10 miles
  """
  permission_classes = [IsCustomer]

  def get(self, request):
    customer = request.user

    # Use customer's saved coordinates directly
    if not customer.lat or not customer.lng:
      return Response(
        {"detail": "Customer location (lat/lng) is not saved in profile."},
        status=status.HTTP_400_BAD_REQUEST
      )

    try:
      lat = float(customer.lat)
      lng = float(customer.lng)
    except (ValueError, TypeError):
      return Response(
        {"detail": "Invalid latitude or longitude in customer profile."},
        status=status.HTTP_400_BAD_REQUEST
      )

    # Optimized single query using your existing calculate_distance_sql
    candidates = (
      LaundrymartStore.objects.filter(
        price_per_pound__isnull=False,
        lat__isnull=False,
        lng__isnull=False,
        stripe_connect_status=True
      )
      # Exclude stores with missing operating hours for the current day
      .exclude(
        Q(operating_hours_start_sunday__isnull=True) | Q(operating_hours_end_sunday__isnull=True) |
        Q(operating_hours_start_monday__isnull=True) | Q(operating_hours_end_monday__isnull=True) |
        Q(operating_hours_start_tuesday__isnull=True) | Q(operating_hours_end_tuesday__isnull=True) |
        Q(operating_hours_start_wednesday__isnull=True) | Q(operating_hours_end_wednesday__isnull=True) |
        Q(operating_hours_start_thursday__isnull=True) | Q(operating_hours_end_thursday__isnull=True) |
        Q(operating_hours_start_friday__isnull=True) | Q(operating_hours_end_friday__isnull=True) |
        Q(operating_hours_start_saturday__isnull=True) | Q(operating_hours_end_saturday__isnull=True)
      )
      .annotate(distance=calculate_distance_sql(lat, lng))
      .filter(distance__lte=10)  # within 10 miles
      .order_by('price_per_pound')  # lowest price first
    )
    logger.info(f"candidates: {candidates}")
    if not candidates.exists():
      return Response(
        {"error": "No open LaundryMart found within serviceable area."},
        status=status.HTTP_404_NOT_FOUND
      )
    weekday = datetime.now().weekday()
    day_map = {
      0: 'monday',
      1: 'tuesday',
      2: 'wednesday',
      3: 'thursday',
      4: 'friday',
      5: 'saturday',
      6: 'sunday',
    }
    day_name = day_map[weekday]

    # Filter out stores that are closed based on their operating hours
    open_stores = []
    for store in candidates:
      is_closed_field = f'is_closed_{day_name}'
      if getattr(store, is_closed_field):
        continue  # Skip closed stores

      # Get the end time for the current day
      end_field = f'operating_hours_end_{day_name}'
      end_time = getattr(store, end_field)

      start_field = f'operating_hours_start_{day_name}'
      start_time = getattr(store, start_field)

      # Check if the store is open now (before the closing time - 60 mins)
      if not start_time or not end_time:
        continue
        
      current_time = datetime.now().time()
      logger.info(f"current_time: {current_time}")
      logger.info(f"end_time: {end_time}")

      end_dt = datetime.combine(datetime.today(), end_time)
      from datetime import timedelta
      cutoff_dt = end_dt - timedelta(minutes=60)
      logger.info(f"cutoff_dt: {cutoff_dt.time()}")
      
      if start_time <= current_time < cutoff_dt.time():
        open_stores.append(store)



    if not open_stores:
      return Response(
        {"error": "No open LaundryMart found within serviceable area."},
        status=status.HTTP_404_NOT_FOUND
      )

    selected_vendor = open_stores[0]
    logger.info(f"open:{open_stores}")
    serializer = VendorSerializer(selected_vendor, context={'request': request})
    logger.info(f"selected_vendor: {serializer.data}")

    return Response(serializer.data, status=status.HTTP_200_OK)

class ReviewAPIView(APIView):
  permission_classes = [IsCustomer]

  @extend_schema(
    request=ReviewSerializer,
    responses={201: None, 400: 'Validation Error'}
  )
  def post(self, request, pk):
    user = request.user
    vendor=User.objects.get(pk=pk)
    serializer = ReviewSerializer(data=request.data)
    try:
      if serializer.is_valid():
        serializer.save(user=user, vendor=vendor)
        return Response({'message':'Review has been given'}, status=status.HTTP_201_CREATED)
      errors = serializer.errors
      field, messages = next(iter(errors.items()))
      readable_field = field.replace('_', ' ').capitalize()
      first_message = messages[0] if isinstance(messages, list) else messages
      error_message = f"{readable_field}: {first_message}"
      return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
      return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


# @api_view(['GET'])
# @permission_classes([IsAuthenticated])
# def list_saved_cards(request):
#   """List all saved payment methods for this user"""
#   try:
#     payment_methods = SavedPaymentMethod.objects.filter(user=request.user)
#
#     cards = [{
#       'id': pm.stripe_payment_method_id,
#       'brand': pm.card_brand,
#       'last4': pm.last4,
#       'exp_month': pm.exp_month,
#       'exp_year': pm.exp_year,
#       'is_default': pm.is_default
#     } for pm in payment_methods]
#
#     return Response({
#       'success': True,
#       'has_cards': len(cards) > 0,
#       'cards': cards
#     })
#
#   except Exception as e:
#     return Response({
#       'success': False,
#       'error': str(e)
#     }, status=400)

class CustomerOrdersListAPIView(APIView):
  permission_classes = [IsCustomer]
  pagination_class = StandardResultsSetPagination
  @extend_schema(
    parameters=[
      OpenApiParameter(
        name='filter',
        description='Filter orders by status: pending, active, completed',
        required=False,
        type=str
      )
    ]
  )
  def get_real_status(self,status):
    if status == "completed":
      return "completed"

    if status in ["processing","card_saved","pickup_courier_scheduled","pickup_courier_assigned",
                  "pickup_arriving_soon","picked_up_by_courier","moving_towards_laundrymart",
                  "moving_towards_customer","arrived_at_laundry","received","weighed","charged",
                  "processing_laundry","picked_up_by_customer","processing_completion",
                  "ready_for_pickup","dropping_of_soon","picked_up_by_laundrymart",
                  "return_scheduled","return_courier_assigned","return_arriving_soon",
    ]:
      return "active"
    if status in ["failed","cancelled","rejected"]:
      return status

    return "pending"

  def get(self, request):
    filter_type = request.query_params.get('filter', '').lower()

    user = request.user
    if not user:
      return Response({"error": "Please try to login again. Your token is invalid"}, status=status.HTTP_400_BAD_REQUEST)


    # We'll collect unified results with a creation timestamp for sorting
    results = []

    if filter_type == '':

      # 1. Pending Delivery Quotes
      quotes = DeliveryQuote.objects.filter(
        customer=user,
        status='pending'  # adjust if you use other pending-like statuses
      ).select_related('customer').prefetch_related('manifest_items')

      # 2. All Orders
      orders = Order.objects.filter(
        user=user,
      ).select_related('user', 'service_provider').prefetch_related('manifest_items') \
        .order_by('-created_at')

      # Combine into list of (timestamp, is_quote, instance)
      combined = []

      for quote in quotes:
        combined.append((
          quote.saved_at,
          True,  # is_quote
          quote
        ))

      for order in orders:
        combined.append((
          order.created_at,
          False,
          order
        ))

      # Sort by timestamp descending
      combined.sort(key=lambda x: x[0], reverse=True)

      # Apply pagination to the combined list
      paginator = self.pagination_class()
      page = paginator.paginate_queryset(combined, request)

      if page is None:
        return Response({"error": "Pagination error"}, status=400)

      # Build final serialized results
      for timestamp, is_quote, item in page:
        time_ago = humanize.naturaltime(timezone.now() - timestamp)

        if is_quote:
          quote = item
          tracking_url = None  # quotes usually don't have tracking yet       

          results.append({
            "id": quote.id,
            "order_id": None,
            "phone_number": quote.customer.phone_number,
            "service_provider":get_object_or_404(

                LaundrymartStore,

                store_id=quote.external_store_id

            ).laundrymart_name,
            "email": quote.customer.email,
            "time_ago": time_ago,
            "customer_note": quote.customer_note,
            "status": quote.get_status_display(),
            "progress_list": [],
            "user": quote.customer.full_name or quote.customer.phone_number or quote.customer.email,
            "vendor_report": None,  # add logic if needed
            "customer_report": None,  # add logic if needed
            "manifest_items": ManifestItemSerializer(quote.manifest_items.all(), many=True).data,
            "service": quote.get_service_type_display(),
            "total_cost": (
                (quote.validation_amount_cents / Decimal('100'))
                if quote.validation_amount_cents is not None else
                ((quote.fee or Decimal('0.00')) / Decimal('100') +
                 (quote.manifest_total_value or Decimal('0.00')) / Decimal('100') +
                 (quote.insurance_amount or Decimal('0.00')))
            ),
            "vendor_fee": quote.manifest_total_value / Decimal('100') if quote.manifest_total_value else Decimal('0.00'),
            "insurance_amount": quote.insurance_amount,
            "service_and_delivery": quote.fee / Decimal('100') if quote.fee else Decimal('0.00'),
            "address": (
                quote.dropoff_address or quote.pickup_address if quote.service_type == 'drop_off'
                else quote.pickup_address or quote.dropoff_address
            ),
            "is_quote": True,
            "quote_id": quote.quote_id,
            "expires": quote.expires.isoformat() if quote.expires else None,
            "scheduled_for": timezone.localtime(quote.pickup_ready_dt).strftime("%B %d, %Y at %-I:%M %p") if quote.pickup_ready_dt else None,
            "created_at": timezone.localtime(quote.saved_at).strftime("%B %d, %Y at %-I:%M %p") if quote.saved_at else None,
            "completed_at": None,
            "tracking_url": tracking_url,
          })

          logger.info(results)

        else:
          order = item

          # Safely get tracking url (most reliable is pickup delivery)
          tracking_url = None
          if order.uber_pickup_delivery_id:
            try:
              delivery = Delivery.objects.get(delivery_uid=order.uber_pickup_delivery_id)
              tracking_url = delivery.tracking_url
            except Delivery.DoesNotExist:
              pass

          quote_id = (
            order.uber_pickup_quote_id
            if not order.parent_delivery
            else order.parent_delivery.quote_uid
          )
          print(f"order.created_at: {order.created_at}")
          created_at = timezone.localtime(order.created_at).strftime("%B %d, %Y at %-I:%M %p")
          
          print(f"created_at: {created_at}")
          print(f"order.completed_at: {order.completed_at}")

          order_service = order.get_service_type()
          results.append({
            "id": order.id,
            "order_id": str(order.uuid),
            "phone_number": order.user.phone_number or order.user.email,
            "service_provider":order.service_provider.laundrymart_name,
            "customer_note": order.customer_note,
            "email": order.user.email,
            "time_ago": time_ago,
            "status": self.get_real_status(order.status),
            "real_status": order.get_status_display(),
            "progress_list": ProgressionSerializer(OrderProgression.objects.filter(order=order).order_by('sequence_no'), many=True).data,
            "user": order.user.full_name or str(order.user),
            "manifest_items": ManifestItemSerializer(order.manifest_items.all(), many=True).data,
            "service": order_service,
            "total_cost": order.final_total_cents / Decimal('100') if order.final_total_cents else None,
            "vendor_fee": order.service_charge_cents / Decimal('100') if order.service_charge_cents else (order.estimated_value / Decimal('100') if order.estimated_value else None),
            "insurance_amount": order.insurance_amount,
            "service_and_delivery": order.delivery_fee_cents / Decimal('100') if order.delivery_fee_cents else None,
            "address": (
                order.dropoff_address or order.pickup_address if order_service in ["Drop off", "drop_off"]
                else order.pickup_address or order.dropoff_address
            ),
            "is_quote": False,
            "quote_id": quote_id,
            "expires": None,
            "scheduled_for": timezone.localtime(order.get_parent_quote_schedule).strftime("%B %d, %Y at %-I:%M %p"),
            "created_at": timezone.localtime(order.created_at).strftime("%B %d, %Y at %-I:%M %p"),
            "completed_at": timezone.localtime(order.completed_at).strftime("%B %d, %Y at %-I:%M %p") if order.completed_at else None,
            "tracking_url": tracking_url,
          })
          
          # logger.info(results)

    elif filter_type in ['active', 'completed']:
      status_list = (
        ['processing','card_saved','pickup_courier_scheduled','pickup_courier_assigned','pickup_arriving_soon',
         'picked_up_by_courier','moving_towards_laundrymart','moving_towards_customer','arrived_at_laundry',
         'received','weighed','charged','processing_laundry','picked_up_by_customer',
         'processing_completion','ready_for_pickup','dropping_of_soon','picked_up_by_laundrymart',
         'return_scheduled','return_courier_assigned','return_arriving_soon']
        if filter_type == 'active'
        else ['completed']
      )

      orders_qs = Order.objects.filter(
        user=user,
        status__in=status_list
      ).select_related('user', 'service_provider').prefetch_related('manifest_items') \
        .order_by('-created_at')

      paginator = self.pagination_class()
      page = paginator.paginate_queryset(orders_qs, request)
      if page is None:
        return Response({"error": "Pagination error"}, status=400)

      for order in page:
        time_ago = humanize.naturaltime(timezone.now() - order.created_at)

        tracking_url = None
        print(f"order.completed_at: {order.completed_at}")

        order_service = order.get_service_type()
        results.append({
          "id": order.id,
          "order_id": str(order.uuid),  # consistent with frontend expectation
          "phone_number": order.user.phone_number or order.user.email,
          "customer_note": order.customer_note,
          "service_provider":order.service_provider.laundrymart_name,
          "email": order.user.email,
          "time_ago": time_ago,
          "status": self.get_real_status(order.status),
          "real_status": order.get_status_display(),
          "progress_list": ProgressionSerializer(OrderProgression.objects.filter(order=order).order_by('sequence_no'), many=True).data,
          "user": str(order.user),  # or order.user.full_name / email if you prefer
          # "service_provider": store.laundrymart_name,
          "tracking_url": Delivery.objects.get(delivery_uid=order.uber_pickup_delivery_id).tracking_url if order.uber_pickup_delivery_id else None,
          "manifest_items": ManifestItemSerializer(order.manifest_items.all(), many=True).data,
          "service": order_service,
          "total_cost": order.final_total_cents / Decimal('100') if order.final_total_cents else None,
          "vendor_fee": order.service_charge_cents / Decimal('100') if order.service_charge_cents else (order.estimated_value / Decimal('100') if order.estimated_value else None),
          "service_and_delivery": order.delivery_fee_cents / Decimal('100') if order.delivery_fee_cents else None,
          "address": (
                order.dropoff_address or order.pickup_address if order_service in ["Drop off", "drop_off"]
                else order.pickup_address or order.dropoff_address
          ),
          "is_quote": False,
          "quote_id": order.uber_pickup_quote_id if order.parent_delivery is None else order.parent_delivery.quote_uid,
          "expires": None,
          "schedule_for":timezone.localtime(order.pickup_delivery.pickup_ready).strftime("%B %d, %Y at %-I:%M %p") if order.pickup_delivery else None,
          "created_at": timezone.localtime(order.created_at).strftime("%B %d, %Y at %-I:%M %p") if order.created_at else None,
          "completed_at": timezone.localtime(order.completed_at).strftime("%B %d, %Y at %-I:%M %p") if order.completed_at else None,
        })

    else:
      return Response({"error": "Invalid filter. Use: pending, active, delivered"}, status=400)

    return paginator.get_paginated_response(results)
    
@extend_schema(
  parameters=[
    OpenApiParameter(
      name='is_pending',
      description='Filter orders by status: True or false',
      required=False,
      type=bool
    )
  ]
)
@api_view(['GET'])
@permission_classes([IsCustomer])
def customer_order_detail(request, id, is_pending=False):
    user = request.user
    is_pending = request.query_params.get('is_pending', 'false').lower() in ('true', '1', 'yes')

    if is_pending:
        quote = get_object_or_404(DeliveryQuote,id=id,customer=user)

        if quote.expires and quote.expires < timezone.now():
            return Response({"error": "This quote has expired"}, status=410)  # 410 Gone is semantic here

        time_ago = humanize.naturaltime(timezone.now() - quote.saved_at)

        data = {
            "id": quote.id,
            "order_id": None,
            "phone_number": quote.customer.phone_number,
            "email": quote.customer.email,
            "time_ago": time_ago,
            "customer_note": quote.customer_note,
            "status": quote.get_status_display(),
            "user": quote.customer.full_name or quote.customer.phone_number or quote.customer.email,
            # Reports — keep same logic as list
            "vendor_report": None,    # add real logic if you actually have reverse accessor or related_name
            "customer_report": None,  # same
            "manifest_items": ManifestItemSerializer(
                quote.manifest_items.all(), many=True
            ).data,
            "service": quote.get_service_type_display(),
            "total_cost": (
                (quote.validation_amount_cents / Decimal('100'))
                if quote.validation_amount_cents is not None else
                ((quote.fee or Decimal('0.00')) / Decimal('100') +
                 (quote.manifest_total_value or Decimal('0.00')) / Decimal('100') +
                 (quote.insurance_amount or Decimal('0.00')))
            ),
            "vendor_fee": quote.fee / Decimal('100') if quote.fee else None,
            "address": (
                quote.dropoff_address or quote.pickup_address if quote.service_type == 'drop_off'
                else quote.pickup_address or quote.dropoff_address
            ),
            "pickup_address": quote.pickup_address,
            "dropoff_address": quote.dropoff_address,
            "pickup_latitude": quote.pickup_latitude,
            "pickup_longitude": quote.pickup_longitude,
            "dropoff_latitude": quote.dropoff_latitude,
            "dropoff_longitude": quote.dropoff_longitude,
            "is_pending": True,
            "quote_id": quote.quote_id,
            "expires": quote.expires.isoformat() if quote.expires else None,
            "created_at": quote.saved_at.isoformat(),
            "tracking_url": None,  # not applicable for quotes
        }

    else:
        # ── Active / Completed / Order flow ─────────────────────────────
        order = get_object_or_404(
            Order,
            id=id,
            user=user
        )

        time_ago = humanize.naturaltime(timezone.now() - order.created_at)

        # You might want to improve this later (from return_delivery or parent_delivery)
        tracking_url = None
        # Example: if order.return_delivery and order.return_delivery.tracking_url:
        #     tracking_url = order.return_delivery.tracking_url

        try:
            order_service = order.get_service_type()
        except Exception:
            order_service = None

        data = {
            "id": order.id,
            "order_id": str(order.uuid),
            "phone_number": order.user.phone_number or order.user.email,
            "email": order.user.email,
            "time_ago": time_ago,
            "customer_note": order.customer_note,
            "status": order.get_status_display(),
            "user": str(order.user),  # or order.user.full_name if preferred
            "manifest_items": ManifestItemSerializer(
                order.manifest_items.all(), many=True
            ).data,
            "service": order_service,
            "total_cost": (
                order.final_total_cents / Decimal('100')
                if order.final_total_cents else None
            ),
            "vendor_fee": (
                order.service_charge_cents / Decimal('100')
                if order.service_charge_cents else (order.estimated_value / Decimal('100') if order.estimated_value else None)
            ),
            "service_and_delivery": (
                order.delivery_fee_cents / Decimal('100')
                if order.delivery_fee_cents else None
            ),
            "address": (
                order.dropoff_address or order.pickup_address if order_service in ["Drop off", "drop_off"]
                else order.pickup_address or order.dropoff_address
            ),
            "pickup_address": order.pickup_address,
            "dropoff_address": order.dropoff_address,
            "pickup_latitude": order.pickup_latitude,
            "pickup_longitude": order.pickup_longitude,
            "dropoff_latitude": order.dropoff_latitude,
            "dropoff_longitude": order.dropoff_longitude,

            "is_pending": False,
            "quote_id": (
                order.uber_pickup_quote_id
                if order.parent_delivery is None
                else order.parent_delivery.quote_uid
            ),
            "expires": None,
            "created_at": order.created_at.isoformat(),
            "tracking_url": tracking_url,
            "weight_in_pounds": order.weight_in_pounds,
            "service_provider": (
                order.service_provider.laundrymart_name
                if order.service_provider else None
            ),
        }

    return Response({
        "is_pending": is_pending,
        "data": data
    })

class CustomerOrderReportAPIView(APIView):
  permission_classes = [IsCustomer]  # Ensure the user is authenticated and a staff member

  @extend_schema(
    request=CustomerOrderReportSerializer,
    responses={201: CustomerOrderReportSerializer, 400: 'Validation Error'}
  )
  def post(self, request):
    try:
      # Extract the data from the request
      data = request.data

      # Deserialize the order report data (including images)
      serializer = CustomerOrderReportSerializer(data=data)

      # Validate the serializer and create the OrderReport if valid
      if serializer.is_valid():

        order_report = serializer.save(user=request.user)

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

class CustomerGlobalManifestAPIView(APIView):
  """Public endpoint for the customer app to fetch the global manifest and slides."""
  permission_classes = [AllowAny]

  def get(self, request):
    manifest = GlobalManifest.get_customer_cached_config()
    return Response(manifest)