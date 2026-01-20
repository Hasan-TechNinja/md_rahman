from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from accounts.models import LaundrymartStore, Service, User
from common_utils.distance_utils import calculate_distance_miles, get_best_location
from customer.models import OrderReport, OrderReportImage, Review
from payment.models import OrderProgression


class ServiceSerializer(serializers.ModelSerializer):
  class Meta:
    model = Service
    fields = '__all__'
class VendorLocation(serializers.ModelSerializer):
  class Meta:
    model=User
    fields = ['lat', 'lng', ]

class VendorSerializer(serializers.ModelSerializer):
  distance=serializers.SerializerMethodField()
  vendor_services = ServiceSerializer(many=True, read_only=True)

  class Meta:
    model = LaundrymartStore
    fields = ['id', 'laundrymart_name','store_id','image','laundrymart_logo', 'location','lat', 'lng', 'vendor_description',
              'distance','price_per_pound','average_rating','get_turnaround_time','is_open_now',
              'closes_at', 'vendor_services',

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

  def get_images(self, obj):
    # Get the request from the context
    request = self.context.get('request')
    if not request:
      raise ValidationError("Request context is missing, can't generate image URLs.")

    # Fetch images related to the report
    images = OrderReportImage.objects.filter(report=obj).values_list('image', flat=True)

    # Construct the full URL for each image using the request's host and scheme (HTTP/HTTPS)
    image_urls = [
      request.build_absolute_uri(image)  # Builds the full URL using the request object
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

    print("Reconstructed images_data:", images_data)

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