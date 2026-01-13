from decimal import Decimal

import humanize
from django.db.models import Avg, Case, FloatField, IntegerField, Value, When

from django.db.models.functions import Coalesce
from django.utils import timezone

from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import LaundrymartStore, User
from common_utils.distance_utils import calculate_distance_miles, calculate_distance_sql, get_best_location
from customer.serializers import CustomerOrderReportSerializer, ReviewSerializer, VendorSerializer
from laundrymart.permissions import IsCustomer
from payment.models import Order
from uber.models import Delivery, DeliveryQuote
from uber.serializers import ManifestItemSerializer
from vendor.serializers import VendorOrderReportSerializer
from vendor.views import StandardResultsSetPagination


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

  ordering_fields = ['average_rating','price_per_pound','distance']

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
    ]
  )
  def get(self, request, *args, **kwargs):
    return super().get(request, *args, **kwargs)
  def get_serializer_context(self):
    context = super().get_serializer_context()
    context["request"] = self.request   # already included, but explicit is fine
    return context
  def get_queryset(self):
    user = self.request.user
    lat_param = self.request.query_params.get('lat')
    lng_param = self.request.query_params.get('lng')

    # Handle latitude and longitude
    if lat_param and lng_param:
      try:
        lat = float(lat_param)
        lng = float(lng_param)
      except (TypeError, ValueError):
        raise ValidationError({"error": "Invalid latitude or longitude format."})
    else:
      # Fallback to user's saved location
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
      average_rating=Coalesce(
        Avg("received_reviews__rating", output_field=FloatField()),
        Value(0.0)
      ),

      # Flag vendors missing location
      has_no_location=Case(
        When(lat__isnull=True, then=Value(1)),
        When(lng__isnull=True, then=Value(1)),
        default=Value(0),
        output_field=IntegerField()
      )
    )

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
      )
      .annotate(distance=calculate_distance_sql(lat, lng))
      .filter(distance__lte=10)  # within 10 miles
      .order_by('price_per_pound')  # lowest price first
    )

    if not candidates.exists():
      return Response(
        {"detail": "No LaundryMart found within 10 miles with available pricing."},
        status=status.HTTP_404_NOT_FOUND
      )

    selected_vendor = candidates.first()
    serializer = VendorSerializer(selected_vendor, context={'request': request})

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

  def get(self, request):
    filter_type = request.query_params.get('filter', 'pending').lower()

    user = request.user


    # We'll collect unified results with a creation timestamp for sorting
    results = []

    if filter_type == 'pending':
      quotes_qs = DeliveryQuote.objects.filter(
        customer=user,
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
          "order_id": None,  # frontend uses this as identifier
          "phone_number": quote.customer.phone_number,
          "email": quote.customer.email,
          "time_ago": time_ago,
          "customer_note": quote.customer_note,
          "status": quote.get_status_display(),
          "user": quote.customer.full_name or quote.customer.phone_number or quote.customer.email,
          "vendor_report": VendorOrderReportSerializer(quote.vendor_filed_report,context={'request': request}).data if hasattr(quote,
                                                                                                     'vendor_filed_report') else None,
          "customer_report": CustomerOrderReportSerializer(quote.customer_filed_report,
                                                           context={'request': request}).data if hasattr(quote,
                                                                                                         'customer_filed_report') else None,
          # "service_provider": store.laundrymart_name or user.full_name,  # if needed
          "manifest_items": ManifestItemSerializer(quote.manifest_items.all(), many=True).data,
          "service": quote.get_service_type_display(),
          "total_cost": None,
          "vendor_fee": quote.fee / Decimal('100') if quote.fee else None,
          "address": quote.dropoff_address or quote.pickup_address,
          "is_quote": True,
          "quote_id": quote.quote_id,
          "expires": quote.expires.isoformat() if quote.expires else None,
          "created_at": quote.saved_at.isoformat(),
        })

    elif filter_type in ['active', 'completed']:
      status_list = (
        ['card_saved', 'picked_up', 'weighed', 'charged', 'return_scheduled']
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

        results.append({
          "id": order.id,
          "order_id": str(order.uuid),  # consistent with frontend expectation
          "phone_number": order.user.phone_number or order.user.email,
          "customer_note": order.customer_note,
          "email": order.user.email,
          "time_ago": time_ago,
          "status": order.get_status_display(),
          "user": str(order.user),  # or order.user.full_name / email if you prefer
          # "service_provider": store.laundrymart_name,
          "tracking_url": None,
          "manifest_items": ManifestItemSerializer(order.manifest_items.all(), many=True).data,
          "service": "full_service",  # or add a field later if needed
          "total_cost": order.final_total_cents / Decimal('100') if order.final_total_cents else None,
          "vendor_fee": order.delivery_fee_cents / Decimal('100') if order.delivery_fee_cents else None,
          "address": order.dropoff_address or order.pickup_address,
          "is_quote": False,
          "quote_id": order.uber_pickup_quote_id if order.parent_delivery is None else order.parent_delivery.quote_uid,
          "expires": None,
          "created_at": order.created_at.isoformat(),
        })

    else:
      return Response({"error": "Invalid filter. Use: pending, active, delivered"}, status=400)

    return paginator.get_paginated_response({
      "results": results,
      "filter": filter_type,
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