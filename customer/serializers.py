from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from accounts.models import LaundrymartStore, Service, User
from admin_panel.models import GlobalManifest, SlideImage
from customer.models import OrderReport, OrderReportImage, Review
from payment.models import OrderProgression
import logging
logger = logging.getLogger(__name__)

class ServiceSerializer(serializers.ModelSerializer):
  class Meta:
    model = Service
    fields = '__all__'
class VendorLocation(serializers.ModelSerializer):
  class Meta:
    model=User
    fields = ['lat', 'lng', ]

class OpeningHoursSerializer(serializers.ModelSerializer):
  operating_hours_start_sunday = serializers.TimeField(format='%I:%M %p')
  operating_hours_end_sunday = serializers.TimeField(format='%I:%M %p')
  
  operating_hours_start_monday = serializers.TimeField(format='%I:%M %p')
  operating_hours_end_monday = serializers.TimeField(format='%I:%M %p')
  
  operating_hours_start_tuesday = serializers.TimeField(format='%I:%M %p')
  operating_hours_end_tuesday = serializers.TimeField(format='%I:%M %p')
  
  operating_hours_start_wednesday = serializers.TimeField(format='%I:%M %p')
  operating_hours_end_wednesday = serializers.TimeField(format='%I:%M %p')
  
  operating_hours_start_thursday = serializers.TimeField(format='%I:%M %p')
  operating_hours_end_thursday = serializers.TimeField(format='%I:%M %p')
  
  operating_hours_start_friday = serializers.TimeField(format='%I:%M %p')
  operating_hours_end_friday = serializers.TimeField(format='%I:%M %p')
  
  operating_hours_start_saturday = serializers.TimeField(format='%I:%M %p')
  operating_hours_end_saturday = serializers.TimeField(format='%I:%M %p')

  class Meta:
    model = LaundrymartStore
    fields = [
      'operating_hours_start_sunday', 'operating_hours_end_sunday', 'is_closed_sunday',
      'operating_hours_start_monday', 'operating_hours_end_monday', 'is_closed_monday',
      'operating_hours_start_tuesday', 'operating_hours_end_tuesday', 'is_closed_tuesday',
      'operating_hours_start_wednesday', 'operating_hours_end_wednesday', 'is_closed_wednesday',
      'operating_hours_start_thursday', 'operating_hours_end_thursday', 'is_closed_thursday',
      'operating_hours_start_friday', 'operating_hours_end_friday', 'is_closed_friday',
      'operating_hours_start_saturday', 'operating_hours_end_saturday', 'is_closed_saturday'
    ]

class VendorSerializer(serializers.ModelSerializer):
  distance=serializers.SerializerMethodField()
  opens_at = serializers.SerializerMethodField()
  store_message_pickup_now = serializers.SerializerMethodField()
  store_message_schedule = serializers.SerializerMethodField()
  is_available_for_pickup_now = serializers.SerializerMethodField()
  is_available_for_schedule = serializers.SerializerMethodField()
  vendor_services = ServiceSerializer(many=True, read_only=True)
  operating_hours_start_sunday = serializers.TimeField(
    format='%I:%M %p'
  )
  operating_hours_end_sunday = serializers.TimeField(
    format='%I:%M %p'
  )

  operating_hours_start_monday = serializers.TimeField(
    format='%I:%M %p'
  )
  operating_hours_end_monday = serializers.TimeField(
    format='%I:%M %p'
  )

  operating_hours_start_tuesday = serializers.TimeField(
    format='%I:%M %p'
  )
  operating_hours_end_tuesday = serializers.TimeField(
    format='%I:%M %p'
  )

  operating_hours_start_wednesday = serializers.TimeField(
    format='%I:%M %p'
  )
  operating_hours_end_wednesday = serializers.TimeField(
    format='%I:%M %p'
  )

  operating_hours_start_thursday = serializers.TimeField(
    format='%I:%M %p'
  )
  operating_hours_end_thursday = serializers.TimeField(
    format='%I:%M %p'
  )

  operating_hours_start_friday = serializers.TimeField(
    format='%I:%M %p'
  )
  operating_hours_end_friday = serializers.TimeField(
    format='%I:%M %p'
  )

  operating_hours_start_saturday = serializers.TimeField(
    format='%I:%M %p'
  )
  operating_hours_end_saturday = serializers.TimeField(
    format='%I:%M %p'
  )

  class Meta:
    model = LaundrymartStore
    fields = ['id', 'laundrymart_name','store_id','image','laundrymart_logo', 'location','lat', 'lng', 'vendor_description',
              'distance','price_per_pound','google_rating','get_turnaround_time','is_open_now',
              'closes_at', 'opens_at', 'store_message_pickup_now', 'store_message_schedule', 
              'is_available_for_pickup_now', 'is_available_for_schedule',
              'vendor_services','phone_number',

              'operating_hours_start_sunday', 'operating_hours_end_sunday', 'is_closed_sunday',
              'operating_hours_start_monday', 'operating_hours_end_monday', 'is_closed_monday',
              'operating_hours_start_tuesday', 'operating_hours_end_tuesday', 'is_closed_tuesday',
              'operating_hours_start_wednesday', 'operating_hours_end_wednesday', 'is_closed_wednesday',
              'operating_hours_start_thursday', 'operating_hours_end_thursday', 'is_closed_thursday',
              'operating_hours_start_friday', 'operating_hours_end_friday', 'is_closed_friday',
              'operating_hours_start_saturday', 'operating_hours_end_saturday', 'is_closed_saturday'
              ]
  def get_distance(self, obj):
    value = getattr(obj, "distance", None)
    if value is None:
      return None
    return round(value, 1)

  def get_store_times(self, obj):
    from django.utils import timezone
    local_now = timezone.localtime(timezone.now())
    weekday = local_now.weekday()
    day_map = {0: 'monday', 1: 'tuesday', 2: 'wednesday', 3: 'thursday', 4: 'friday', 5: 'saturday', 6: 'sunday'}
    day_name = day_map[weekday]
    
    is_closed = getattr(obj, f'is_closed_{day_name}', True)
    start_time = getattr(obj, f'operating_hours_start_{day_name}', None)
    end_time = getattr(obj, f'operating_hours_end_{day_name}', None)
    
    return is_closed, start_time, end_time, local_now

  def get_opens_at(self, obj):
    is_closed, start_time, _, _ = self.get_store_times(obj)
    return start_time.strftime('%I:%M %p').lstrip('0') if not is_closed and start_time else None

  def get_store_message_pickup_now(self, obj):
    is_closed, start_time, end_time, local_now = self.get_store_times(obj)
    if is_closed or not start_time or not end_time:
      return "Closed today"
    
    now_time = local_now.time()
    if now_time < start_time:
      return f"Opens at {start_time.strftime('%I:%M %p').lstrip('0')}"
      
    from datetime import datetime, timedelta
    end_dt = datetime.combine(local_now.date(), end_time)
    cutoff_dt = end_dt - timedelta(minutes=60)
    
    if now_time >= end_time:
      return "Closed"
      
    if now_time >= cutoff_dt.time():
      return f"Closes at {end_time.strftime('%I:%M %p').lstrip('0')} — too late for pickup now"
      
    return ""

  def get_store_message_schedule(self, obj):
    is_closed, start_time, end_time, local_now = self.get_store_times(obj)
    if is_closed or not start_time or not end_time:
      return "Closed today"
      
    now_time = local_now.time()
    if now_time < start_time:
      return f"Opens at {start_time.strftime('%I:%M %p').lstrip('0')}"
      
    from datetime import datetime, timedelta
    end_dt = datetime.combine(local_now.date(), end_time)
    cutoff_dt = end_dt - timedelta(minutes=60)
    
    if now_time >= end_time:
      return "Closed"
      
    if now_time >= cutoff_dt.time():
      return f"Latest pickup today: {cutoff_dt.strftime('%I:%M %p').lstrip('0')}"
      
    return ""

  def get_is_available_for_pickup_now(self, obj):
    is_closed, start_time, end_time, local_now = self.get_store_times(obj)
    if is_closed or not start_time or not end_time:
      return False
    from datetime import datetime, timedelta
    end_dt = datetime.combine(local_now.date(), end_time)
    cutoff_dt = end_dt - timedelta(minutes=60)
    return start_time <= local_now.time() < cutoff_dt.time()

  def get_is_available_for_schedule(self, obj):
    is_closed, start_time, end_time, local_now = self.get_store_times(obj)
    if is_closed or not start_time or not end_time:
      return False
    from datetime import datetime, timedelta
    end_dt = datetime.combine(local_now.date(), end_time)
    cutoff_dt = end_dt - timedelta(minutes=60)
    return start_time <= local_now.time() < cutoff_dt.time()



  # def get_distance(self, obj):
  #   annotated_distance = getattr(obj, 'distance', None)
  #   if annotated_distance is not None:
  #     return round(annotated_distance, 1) if annotated_distance else None
  #
  #   # Fallback: Python calculation (only if serializer used outside this view)
  #   request = self.context.get('request')
  #   if not request or not request.user.is_authenticated:
  #     return None
  #
  #   user = request.user
  #   #vendor_lat, vendor_lng = get_best_location(obj)
  #
  #   return calculate_distance_miles(user.lat, user.lng, obj.lat, obj.lng)

class ReviewSerializer(serializers.ModelSerializer):
  class Meta:
    model=Review
    fields = ['user', 'laundrymart', 'rating', 'created_at']
    read_only_fields = ['user', 'vendor', 'created_at']

class OrderReportImageSerializer(serializers.ModelSerializer):
  class Meta:
    model = OrderReportImage
    fields = ['image']  # Only the image field is needed for the upload

class CustomerOrderReportSerializer(serializers.ModelSerializer):
  images = serializers.SerializerMethodField()

  class Meta:
    model = OrderReport
    fields = ['id', 'user', 'delivery_quote', 'order', 'issue_description', 'created_at', 'images']
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
    return image_urls


  def create(self, validated_data):
    request = self.context['request']

    # Manually reconstruct the images data from form-data
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

    # Now associate the images with the OrderReport
    for image_data in images_data:
      OrderReportImage.objects.create(report=order_report, **image_data)

    return order_report

class ProgressionSerializer(serializers.ModelSerializer):
  class Meta:
    model=OrderProgression
    fields = '__all__'

class SlideImageSerializer(serializers.ModelSerializer):
  class Meta:
    model = SlideImage
    fields = ['image', 'order_index']

class GlobalManifestSerializer(serializers.ModelSerializer):
  class Meta:
    model = GlobalManifest
    fields = '__all__'


class CustomerGlobalManifestSerializer(serializers.ModelSerializer):
  """Serializer exposed to customers. Intentionally returns a subset of
  GlobalManifest fields that are relevant to the customer-facing app.
  It also includes slide images under the `slides` key.
  """
  slides = serializers.SerializerMethodField()

  class Meta:
    model = GlobalManifest
    fields = [
      'service_fee', 'insurance_fee',
      'customer_stripe_charge_in_percentage', 'customer_stripe_charge_added_cents',
      'small_bag_text', 'small_bag_image',
      'medium_bag_text', 'medium_bag_image',
      'large_bag_text', 'large_bag_image',
      'cust_navbar_text', 'full_service_text', 'drop_off_text', 'pickup_text',
      'customer_faq', 'customer_privacy_policy', 'customer_terms_conditions',
      'customer_laundry_protections', 'customer_account_delete_text',
      'invite_top_text', 'invite_image', 'invite_share_link_text', 'invite_get_credit_config',
      'updated_at',
      'slides'
    ]

  def get_slides(self, obj):
    # Use the cached helper to avoid extra queries
    slides = SlideImage.get_cached_slide_images()
    return slides

