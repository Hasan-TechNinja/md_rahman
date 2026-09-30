from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from admin_panel.models import GlobalManifest
from messaging.models import VendorNotification
from messaging.serializers import VendorNotificationSerializer
from payment.models import Order
from uber.models import DeliveryQuote
from uber.serializers import ManifestItemSerializer
from vendor.models import OrderReport, OrderReportImage
import logging
logger = logging.getLogger(__name__)

class DashboardSerializer(serializers.Serializer):
  order_stats=serializers.SerializerMethodField()
  # revenue_last_seven_days = serializers.SerializerMethodField()
  recent_orders = serializers.SerializerMethodField()
  #in_progress=serializers.SerializerMethodField()
  alert_notifications=serializers.SerializerMethodField()

  def get_order_stats(self, obj):
    associated_laundrymart = self.context.get('associated_laundrymart')
    store_uuid = self.context.get('store_uuid')
    logger.info(f'store_uuid:{store_uuid}')

    current_month = timezone.now().month

    logger.info(f'current_month:{current_month}')

    # Query to get the counts for all the statuses in a single query
    delivery_quote_stats = DeliveryQuote.objects.filter(
        external_store_id=store_uuid,
        saved_at__month=current_month,
    ).aggregate(
        pending_orders=Count('id', filter=Q(status='pending')),
        rejected_orders=Count('id', filter=Q(status__in=['rejected', 'wait_for_support'])),
    )
    logger.info(f'Order Stats: {delivery_quote_stats}')

    order_queryset = Order.objects.filter(
      service_provider=associated_laundrymart,
    )

    active_status_list = ['processing', 'card_saved', 'pickup_courier_scheduled', 'pickup_courier_assigned', 'pickup_arriving_soon',
         'picked_up_by_courier', 'moving_towards_laundrymart', 'moving_towards_customer', 'arrived_at_laundry',
         'received', 'weighed', 'charged', 'processing_laundry', 'picked_up_by_customer','awaiting_pickup',
         'processing_completion', 'ready_for_pickup', 'dropping_of_soon', 'picked_up_by_laundrymart',
         'return_scheduled', 'return_courier_assigned', 'return_arriving_soon']

    incoming_status_list = [
        'processing', 'card_saved', 'awaiting_pickup',
        'pickup_courier_scheduled', 'pickup_courier_assigned', 'pickup_arriving_soon',
        'picked_up_by_courier', 'moving_towards_laundrymart', 'arrived_at_laundry'
    ]

    all_incoming_quotes = DeliveryQuote.objects.filter(
        service_type__in=['full_service', 'pickup', 'drop_off', 'dropoff']
    ).values('quote_id')
    drop_off_quotes = DeliveryQuote.objects.filter(
        service_type__in=['drop_off', 'dropoff']
    ).values('quote_id')

    incoming_filter = (
        Q(status__in=incoming_status_list, uber_pickup_quote_id__in=all_incoming_quotes) |
        Q(status='charged', uber_pickup_quote_id__in=drop_off_quotes)
    )

    # In progress orders - means active orders (excluding incoming)
    in_progress_orders = order_queryset.filter(status__in=active_status_list).exclude(incoming_filter).count()

    # Incoming orders - orders from accepted to arrived at laundry (full_service/pickup/drop_off)
    incoming_orders = order_queryset.filter(incoming_filter).count()

    # Completed orders
    completed_orders = order_queryset.filter(status='completed').count()

    # Ready to pick up orders - optimized using ORM to prevent N+1 queries
    ready_to_pick_up = order_queryset.filter(
        Q(status='return_scheduled', uber_pickup_quote_id__in=DeliveryQuote.objects.filter(service_type__in=['full_service', 'pickup']).values('quote_id')) |
        Q(status='charged', uber_pickup_quote_id__in=DeliveryQuote.objects.filter(service_type__in=['drop_off']).values('quote_id'))
    ).count()

    # Returning the aggregated counts
    return {
      'pending_orders': delivery_quote_stats['pending_orders'],
      'in_progress_orders': in_progress_orders,
      'ready_to_pick_up': ready_to_pick_up,
      'completed_orders': completed_orders,
      'rejected_orders': delivery_quote_stats['rejected_orders'],
      'incoming_orders': incoming_orders,
    }

  # Convert cents to dollars
  #
  def get_alert_notifications(self, obj):
    associated_laundrymart = self.context.get('associated_laundrymart')
    notifications = VendorNotification.objects.filter(recipient=associated_laundrymart, category='Important', is_read=False).order_by('-created_at')[:2]
    return VendorNotificationSerializer(notifications, many=True).data

  def get_recent_orders(self, obj):
    associated_laundrymart = self.context.get('associated_laundrymart')
    recent_orders = Order.objects.filter(
      service_provider=associated_laundrymart
    ).only('id', 'uuid', 'user_id', 'status', 'weight_in_pounds', 'created_at', 'service_provider_id').order_by('-created_at')[:5]  # Get the 5 most recent orders
    return DashboardOrderSerializer(recent_orders, many=True, context={'associated_laundrymart':associated_laundrymart}).data

class OrderReportImageSerializer(serializers.ModelSerializer):
  class Meta:
    model = OrderReportImage
    fields = ['image']  # Only the image field is needed for the upload

class VendorOrderReportSerializer(serializers.ModelSerializer):
  images = serializers.SerializerMethodField()

  class Meta:
    model = OrderReport
    fields = ['id', 'laundrymart', 'images', 'delivery_quote', 'order', 'issue_description', 'created_at']
    read_only_fields = ['laundrymart', 'created_at']

  def get_images(self, obj):
    request = self.context.get('request')
    images = OrderReportImage.objects.filter(report=obj).only('image')
    image_urls = []
    for image in images:
      if image.image:
        url = request.build_absolute_uri(image.image.url) if request else image.image.url
        image_urls.append(url)
    return image_urls

  def create(self, validated_data):
    request = self.context.get('request')

    uploaded_images = []
    if request and hasattr(request, 'FILES'):
      # 1. Standard keys 'images', 'images[]', 'image'
      for key in ['images', 'images[]', 'image']:
        if key in request.FILES:
          uploaded_images.extend(request.FILES.getlist(key))

      # 2. Indexed keys like images[0], images[1], image_0, etc.
      for key in request.FILES:
        if key not in ['images', 'images[]', 'image']:
          if key.startswith('images[') or key.startswith('image[') or key.startswith('images.') or key.startswith('image_'):
            uploaded_images.extend(request.FILES.getlist(key))

    logger.info(f"Reconstructed uploaded_images count: {len(uploaded_images)}")

    # IMPORTANT: Remove 'images' from validated_data to prevent setter error
    validated_data.pop('images', None)

    # Create the OrderReport instance
    order_report = OrderReport.objects.create(**validated_data)

    for img in uploaded_images:
      OrderReportImage.objects.create(report=order_report, image=img)

    return order_report

class DashboardOrderSerializer(serializers.ModelSerializer):
  user = serializers.StringRelatedField()
  price=serializers.SerializerMethodField()
  status=serializers.SerializerMethodField()
  class Meta:
    model = Order
    fields = ['id','uuid', 'user', 'status', 'weight_in_pounds','price', 'created_at']

  def get_status(self, obj):
    return obj.get_status_display()

  def get_price(self, obj):
    associated_laundrymart = self.context.get('associated_laundrymart')
    store_fee = associated_laundrymart.price_per_pound if associated_laundrymart.price_per_pound is not None else 0
    weight_in_pounds = obj.weight_in_pounds if obj.weight_in_pounds is not None else 0
    service_fee = associated_laundrymart.service_fee if associated_laundrymart.service_fee is not None else 0
    total_fee = store_fee * weight_in_pounds + service_fee
    return round(total_fee, 2)


class OrderDetailSerializer(serializers.ModelSerializer):
  user = serializers.StringRelatedField()
  # service_provider = serializers.StringRelatedField()
  manifest_items = ManifestItemSerializer(many=True)
  phone_number = serializers.SerializerMethodField()
  class Meta:
    model = Order
    fields = ['id','uuid','phone_number', 'time_ago', 'user', 'manifest_items', 'service', 'total_cost', 'vendor_fee', 'address']
  def get_phone_number(self, obj):
    return obj.user.phone_number or obj.user.email

class OrderWeightSerializer(serializers.ModelSerializer):
  class Meta:
    model = Order
    fields = ['id', 'weight_in_pounds', 'service_charge_cents', 'final_total_cents']

class VendorGlobalManifestSerializer(serializers.ModelSerializer):
  """Serializer exposed to vendor employees. Returns vendor/admin related
  settings and platform transaction charge configuration.
  """
  class Meta:
    model = GlobalManifest
    fields = [
      'payout_transaction_charge_in_percentage', 'payout_transaction_added_cents',
      'service_fee', 'insurance_fee',
      'vendor_register_page_text', 'vendor_order_history_info_text', 'vendor_faq',
      'vendor_privacy_policy', 'vendor_terms_conditions', 'vendor_laundry_protection',
      'vendor_account_delete_text',
      'customer_stripe_charge_in_percentage', 'customer_stripe_charge_added_cents',
      'updated_at'
    ]