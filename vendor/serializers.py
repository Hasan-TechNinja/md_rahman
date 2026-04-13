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
    logger.info('Order Stats:', delivery_quote_stats)

    order_queryset = Order.objects.filter(
      service_provider=associated_laundrymart,
    )

    # In progress orders - excluding completion_failed, completed, canceled, and wait_for_support
    in_progress_orders = order_queryset.exclude(
      status__in=['completion_failed', 'completed', 'canceled', 'wait_for_support']
    ).count()

    # Completed orders
    completed_orders = order_queryset.filter(status='completed').count()

    # Ready to pick up orders - filter manually based on service_type
    ready_to_pick_up = sum(
      1 for order in order_queryset
      if order.status == 'return_scheduled' and order.get_service_type() in ['Full service', 'Pick up']
    )

    # Returning the aggregated counts
    return {
      'pending_orders': delivery_quote_stats['pending_orders'],
      'in_progress_orders': in_progress_orders,
      'ready_to_pick_up': ready_to_pick_up,
      'completed_orders': completed_orders,
      'rejected_orders': delivery_quote_stats['rejected_orders'],
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
    fields = ['id', 'laundrymart','images', 'delivery_quote', 'order', 'issue_description', 'created_at', 'images']
    read_only_fields = ['laundrymart', 'created_at']

  def get_images(self, obj):
    request = self.context.get('request')
    if not request:
      raise ValidationError("Request context is missing, can't generate image URLs.")

    images = OrderReportImage.objects.filter(report=obj).only('image')
    image_urls = [
      request.build_absolute_uri(image.image.url)  # ← .image.url is the key
      for image in images
    ]

    # logger.info(image_urls)   # for debugging only — remove in production
    return image_urls

  def create(self, validated_data):
    request = self.context['request']

    images_data = []
    i = 0
    while True:
      image_key = f'images[{i}]'  # Example format for image keys in form data

      if image_key not in request.FILES:
        break

      image_item = {
        'image': request.FILES[image_key],  # Fetch the image from request.FILES
      }

      images_data.append(image_item)
      i += 1

    logger.info("Reconstructed images_data:", images_data)

    # IMPORTANT: Remove 'images' from validated_data to prevent setter error
    validated_data.pop('images', None)

    # Create the OrderReport instance
    order_report = OrderReport.objects.create(**validated_data)

    for image_data in images_data:
      OrderReportImage.objects.create(report=order_report, **image_data)

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