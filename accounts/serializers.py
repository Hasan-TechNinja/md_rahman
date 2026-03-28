import json
from datetime import timedelta

from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers
import logging
logger = logging.getLogger(__name__)

from .models import LaundrymartStore, SecondaryLocation, Service, User
import random

class CreateUserSerializer(serializers.ModelSerializer):
  role = serializers.ChoiceField(choices=['Customer', 'Vendor'], write_only=True)
  class Meta:
    model = User
    fields = ['email', 'phone_number', 'role', 'password']
    extra_kwargs = {'password': {'write_only': True}}

  def validate(self, attrs):
    email = attrs.get('email')
    phone = attrs.get('phone_number')
    role = attrs.get('role')
    if role not in ['Customer', 'Vendor']:
      raise serializers.ValidationError({"role": "Role must be either 'Customer' or 'Vendor'."})

    # Normalize input
    email = email.strip().lower() if email else None
    phone = phone.strip() if phone and phone.strip() else None

    attrs['email'] = email
    attrs['phone_number'] = phone

    if not email and not phone:
      raise serializers.ValidationError(
        "Either email or phone number must be provided."
      )

    # Email validation
    if email:
      try:
        validate_email(email)
      except ValidationError:
        raise serializers.ValidationError(
          {"email": "Enter a valid email address."}
        )

      if User.objects.filter(email=email).exists():
        raise serializers.ValidationError(
          {"email": "An account with this email already exists."}
        )

    # Phone validation
    if phone:
      if User.objects.filter(phone_number=phone).exists():
        raise serializers.ValidationError(
          {"phone_number": "An account with this phone number already exists."}
        )

    # Password validation
    password = attrs.get('password')

    if not password or not password.strip():
      raise serializers.ValidationError(
        {"password": "Password cannot be empty."}
      )

    try:
      validate_password(password)
    except ValidationError as e:
      raise serializers.ValidationError(
        {"password": list(e.messages)}
      )

    return attrs

  def create(self, validated_data):
    email = validated_data.get('email')
    phone = validated_data.get('phone_number')
    role = validated_data.pop('role')
    password = validated_data.pop('password')

    # Generate OTP
    otp = str(random.randint(1000, 9999))
    otp_expiry = timezone.now() + timedelta(minutes=2)

    # Build safe query
    query = Q()
    if email:
      query |= Q(email=email)
    if phone:
      query |= Q(phone_number=phone)

    existing_user = User.objects.filter(query).first()

    if existing_user:
      if existing_user.is_active and existing_user.is_verified:
        raise serializers.ValidationError(
          "User already exists and is active."
        )

      existing_user.otp = str(otp)
      existing_user.otp_expires = otp_expiry
      existing_user.set_password(password)
      existing_user.save()
      if role == 'Vendor':
        group, _ = Group.objects.get_or_create(name='laundrymart_admin')
        existing_user.groups.add(group)  # ← correct here

      return existing_user

    # Create a new user
    user = User(
      email=email,
      phone_number=phone,
      is_active=False,
      is_verified=False,
      otp=str(otp),
      otp_expires=otp_expiry,
      approved_by_admin=False,
      is_staff=False if role == 'Customer' else True,
    )
    user.set_password(password)
    user.save()
    if role == 'Vendor':
      group, _ = Group.objects.get_or_create(name='laundrymart_admin')
      user.groups.add(group)  # ← FIXED: use user, not existing_user

    return user

class ResendOTPSerializer(serializers.Serializer):
  email = serializers.EmailField(required=False, allow_null=True)
  phone_number = serializers.CharField(required=False, allow_null=True, max_length=30)

  def validate(self, attrs):
    email = attrs.get('email')
    phone_number = attrs.get('phone_number')
    if not email and not phone_number:
      raise serializers.ValidationError("Either email or phone number must be provided.")
    return attrs

class ForgetPasswordSerializer(serializers.Serializer):
  email = serializers.EmailField(required=False, allow_null=True)
  phone_number = serializers.CharField(required=False, allow_null=True, max_length=30)

  def validate(self, attrs):
    email = attrs.get('email')
    phone_number = attrs.get('phone_number')
    if not email and not phone_number:
      raise serializers.ValidationError("Either email or phone number must be provided.")
    return attrs

class ChangePasswordSerializer(serializers.Serializer):
  new_password = serializers.CharField(required=True)

  def validate_new_password(self, value):
    # Use Django’s built-in password validators
    try:
      validate_password(value)
    except ValidationError as e:
      raise serializers.ValidationError(e.messages)
    return value

from rest_framework import serializers

class OTPSerializer(serializers.Serializer):
  email = serializers.EmailField(required=False, allow_null=True)
  phone_number = serializers.CharField(required=False, allow_null=True, max_length=30)
  otp = serializers.CharField(max_length=4)

  def validate(self, attrs):
    email = attrs.get('email')
    phone_number = attrs.get('phone_number')
    otp = attrs.get('otp')

    if not email and not phone_number:
      raise serializers.ValidationError("Either email or phone number must be provided.")
    if not otp:
      raise serializers.ValidationError("OTP is required.")
    return attrs


# class MyTokenObtainPairSerializer(TokenObtainPairSerializer):
#   def validate(self, attrs):
#     data = super().validate(attrs)
#
#     user = self.user
#
#     # Prepare extra user info (outside token)
#     data['login_user_info'] = {
#       'name': user.full_name if user.full_name else '',
#       'image': user.image.url if user.image else None
#     }
#     return data


class LogoutSerializer(serializers.Serializer):
  refresh_token = serializers.CharField(required=True)

class CustomerProfileSerializer(serializers.ModelSerializer):
  location = serializers.JSONField(required=False)
  class Meta:
    model = User
    fields = ['id', 'full_name', 'email','is_verified', 'phone_number', 'image', 'location', 'lat', 'lng']
    read_only_fields = ('is_verified',)

  def validate_location(self, value):
    """
    Custom validation to ensure that the location is correctly stringified as JSON.
    """
    if value:
      try:
        # Ensure the value is a valid JSON object (this also stringifies it if necessary)
        json_string = json.dumps(value)
        # You can add more validation here if necessary, but we're focusing on stringification
        return json_string
      except (TypeError, ValueError) as e:
        raise serializers.ValidationError(f"Invalid location format: {e}")
    return value

class ServiceSerializer(serializers.ModelSerializer):
  class Meta:
    model = Service
    fields = ['id', 'service_name', 'price_per_pound', 'image']


class VendorProfileSerializer(serializers.ModelSerializer):
  vendor_services = ServiceSerializer(many=True, read_only=True)
  class Meta:
    model = LaundrymartStore
    fields = [
              'id', 'laundrymart_name', 'store_id', 'image', 'laundrymart_logo', 'location', 'lat', 'lng',
              'vendor_description','minimum_order_weight', 'store_id',
              'daily_capacity_limit', 'vendor_services',

              'turnaround_time_minimum_sunday', 'turnaround_time_maximum_sunday',
              'turnaround_time_minimum_monday', 'turnaround_time_maximum_monday',
              'turnaround_time_minimum_tuesday', 'turnaround_time_maximum_tuesday',
              'turnaround_time_minimum_wednesday', 'turnaround_time_maximum_wednesday',
              'turnaround_time_minimum_thursday', 'turnaround_time_maximum_thursday',
              'turnaround_time_minimum_friday', 'turnaround_time_maximum_friday',
              'turnaround_time_minimum_saturday', 'turnaround_time_maximum_saturday',

              'operating_hours_start_sunday', 'operating_hours_end_sunday', 'is_closed_sunday',
              'operating_hours_start_monday', 'operating_hours_end_monday', 'is_closed_monday',
              'operating_hours_start_tuesday', 'operating_hours_end_tuesday', 'is_closed_tuesday',
              'operating_hours_start_wednesday', 'operating_hours_end_wednesday', 'is_closed_wednesday',
              'operating_hours_start_thursday', 'operating_hours_end_thursday', 'is_closed_thursday',
              'operating_hours_start_friday', 'operating_hours_end_friday', 'is_closed_friday',
              'operating_hours_start_saturday', 'operating_hours_end_saturday', 'is_closed_saturday'
              ]
    read_only_fields = ['id', 'laundrymart_name', 'store_id', 'image', 'laundrymart_logo', 'location', 'lat', 'lng',
              'vendor_description','minimum_order_weight', 'store_id',
              'daily_capacity_limit']
  def update(self, instance, validated_data):
    request = self.context['request']

    # Manually reconstruct services_data from form-data
    services_data = []
    i = 0
    while True:
      service_name_key = f'vendor_services[{i}][service_name]'
      price_key = f'vendor_services[{i}][price_per_pound]'
      image_key = f'vendor_services[{i}][image]'

      if service_name_key not in request.data:
        break

      service_item = {
        'service_name': request.data[service_name_key],
        'price_per_pound': request.data[price_key],
      }

      if image_key in request.FILES:
        service_item['image'] = request.FILES[image_key]

      services_data.append(service_item)
      i += 1

    logger.info("Reconstructed services_data:", services_data)

    # IMPORTANT: Remove 'vendor_services' from validated_data to prevent setattr error
    validated_data.pop('vendor_services', None)

    # Now safely update the scalar fields on the vendor (User instance)
    for attr, value in validated_data.items():
      setattr(instance, attr, value)
    instance.save()

    # Only replace services if any were provided in the request
    if services_data:
      instance.vendor_services.all().delete()
      for service in services_data:
        Service.objects.create(
          vendor=instance,
          service_name=service['service_name'],
          price_per_pound=service['price_per_pound'],
          image=service.get('image')
        )

    return instance

class VendorSettingSerializer(serializers.ModelSerializer):
  class Meta:
    model = LaundrymartStore
    fields = ['push_and_email_alerts', 'auto_accept_orders']

class CustomerSettingSerializer(serializers.ModelSerializer):
  class Meta:
    model = User
    fields = ['push_and_email_alerts', 'preference']

class SecondaryLocationSerializer(serializers.ModelSerializer):
  location = serializers.JSONField()
  class Meta:
    model = SecondaryLocation
    fields = ['user','type','lat', 'lng','location', 'created_at']
    read_only_fields=['created_at', 'user']
  def validate_location(self, value):
    """
    Custom validation to ensure that the location is correctly stringified as JSON.
    """
    if value:
      try:
        # Ensure the value is a valid JSON object (this also stringifies it if necessary)
        json_string = json.dumps(value)
        # You can add more validation here if necessary, but we're focusing on stringification
        return json_string
      except (TypeError, ValueError) as e:
        raise serializers.ValidationError(f"Invalid location format: {e}")
    return value

class EmployeeLoginSerializer(serializers.Serializer):
  phone_number=serializers.CharField()
  username = serializers.CharField()
  password = serializers.CharField()

