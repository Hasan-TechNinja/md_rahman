from datetime import datetime
from django.utils import timezone

import uuid

from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db.models import Avg, FloatField
from location_field.models.plain import PlainLocationField

from accounts.utils import reverse_geocode_google
import logging
logger = logging.getLogger(__name__)

# Create your models here.


class CustomUserManager(BaseUserManager):

  def _create_user(self, password, email=None, phone_number=None, full_name=None, **extra_fields):
    if not email and not phone_number:
      raise ValueError('Either email or phone number must be provided.')

    if email:
      email = self.normalize_email(email)

    user = self.model(
      email=email,
      phone_number=phone_number,
      full_name=full_name,
      **extra_fields
    )
    user.set_password(password)
    user.save(using=self._db)
    return user

  def create_user(self, password, email=None, phone_number=None, full_name=None, **extra_fields):
    extra_fields.setdefault('is_superuser', False)
    extra_fields.setdefault('is_staff', False)
    return self._create_user(password, email, phone_number, full_name, **extra_fields)

  def create_superuser(self,password, email=None, phone_number=None, full_name=None, **extra_fields):
    extra_fields.setdefault('is_superuser', True)
    extra_fields.setdefault('is_staff', True)
    extra_fields.setdefault('is_active', True)

    if extra_fields.get('is_superuser') is not True:
      raise ValueError('Superuser must have is_superuser=True.')

    return self._create_user(password, email, phone_number, full_name, **extra_fields)

PREFERENCE_CHOICES = [
  ('Auto-assign another LaundryMart (fastest)', 'Auto-assign another LaundryMart (fastest)'),
  ('Ask me to choose (I’ll decide each time)', 'Ask me to choose (I’ll decide each time)'),
]

class User(AbstractUser):
  #firebase fields
  firebase_uid = models.CharField(blank=True, null=True, unique=True,max_length=255)
  auth_provider=models.CharField(blank=True, null=True, default='email', max_length=20)

  username = None
  full_name = models.CharField(blank=True, max_length=255, null=True)
  email = models.EmailField(blank=True, null=True, unique=True, db_index=True)
  phone_number = models.CharField(blank=True, null=True, unique=True, max_length=30)
  location=models.TextField(blank=True, null=True)

  lat = models.FloatField(blank=True, null=True)
  lng = models.FloatField(blank=True, null=True)

  secondary_location=models.TextField(blank=True, null=True)
  secondary_lat = models.FloatField(blank=True, null=True)
  secondary_lng = models.FloatField(blank=True, null=True)

  is_active = models.BooleanField(default=False)
  otp = models.CharField(blank=True, null=True, max_length=4)
  otp_expires=models.DateTimeField(blank=True, null=True)
  is_verified = models.BooleanField(default=False)

  is_tester=models.BooleanField(default=False)

  push_and_email_alerts = models.BooleanField(default=True)

  approved_by_admin=models.BooleanField(default=False)

  preference = models.CharField(max_length=50, blank=True, null=True, choices=PREFERENCE_CHOICES, default='Auto-assign another LaundryMart (fastest)')
  stripe_customer_id = models.CharField(max_length=200, blank=True, null=True)
  stripe_connect_account_id = models.CharField(max_length=200, blank=True, null=True)
  stripe_connect_account_status = models.BooleanField(default=False)

  created_at=models.DateTimeField(auto_now_add=True)
  updated_at=models.DateTimeField(auto_now=True)

  image=models.ImageField(blank=True, null=True, upload_to='images/')

  USERNAME_FIELD = 'email'
  REQUIRED_FIELDS = []

  objects = CustomUserManager()
  @property
  def store_uid(self):
    if not self.store_id:
      return None
    return f"store_{self.store_id}"

  def average_rating(self):

    avg = self.received_reviews.aggregate(
      avg_rating=Avg('rating', output_field=FloatField())
    )['avg_rating']

    if avg is None:
      return None

    return round(avg, 2)

  @property
  def get_turnaround_time(self):
    local_now = timezone.localtime(timezone.now())
    weekday = local_now.weekday()  # 0: Monday, ..., 6: Sunday
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

    min_field = f'turnaround_time_minimum_{day_name}'
    max_field = f'turnaround_time_maximum_{day_name}'

    min_val = getattr(self, min_field)
    max_val = getattr(self, max_field)

    # If both are set, return formatted string
    if min_val is not None and max_val is not None:
      # Ensure proper formatting (e.g., 24.00 → 24, 24.50 → 24.5)
      min_str = str(float(min_val)).rstrip('0').rstrip('.') if '.' in str(min_val) else str(min_val)
      max_str = str(float(max_val)).rstrip('0').rstrip('.') if '.' in str(max_val) else str(max_val)
      return f'{min_str}-{max_str}'
    return None

  @property
  def is_open_now(self):
    local_now = timezone.localtime(timezone.now())
    weekday = local_now.weekday()  # 0: Monday, ..., 6: Sunday
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

    # Check if explicitly closed today
    is_closed_field = f'is_closed_{day_name}'
    if getattr(self, is_closed_field):
      return False

    # Get start and end times
    start_field = f'operating_hours_start_{day_name}'
    end_field = f'operating_hours_end_{day_name}'

    start_time = getattr(self, start_field)
    end_time = getattr(self, end_field)

    if start_time is None or end_time is None:
      return False

    now_time = local_now.time()

    return start_time <= now_time < end_time

  @property
  def closes_at(self):
    local_now = timezone.localtime(timezone.now())
    weekday = local_now.weekday()
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

    is_closed_field = f'is_closed_{day_name}'
    if getattr(self, is_closed_field):
      return None

    end_field = f'operating_hours_end_{day_name}'
    end_time = getattr(self, end_field)

    return end_time

  def clean(self):
    # Ensure at least one identifier is present
    if not self.email and not self.phone_number:
      raise ValidationError('Either email or phone number must be provided.')

  # def save(self, *args, **kwargs):
  #   # Validate first
  #   self.full_clean()
  #
  #   # Auto-generate store_id ONLY for vendors
  #   if self.is_staff and not self.is_superuser:
  #     if not self.store_id:
  #       self.store_id = uuid.uuid4()
  #   else:
  #     # Non-vendors must NOT have store_id
  #     self.store_id = None
  #
  #   super().save(*args, **kwargs)

  def __str__(self):
    return self.full_name or self.email or self.phone_number or str(self.pk)

  class Meta:
    verbose_name = 'User'
    verbose_name_plural = 'Users'

class CustomerProxy(User):

  class Meta:
    proxy=True
    verbose_name = 'Customer'
    verbose_name_plural = 'Customers'

class StaffProxy(User):

  class Meta:
    proxy = True
    verbose_name = 'Staff Member'
    verbose_name_plural = 'Staff Members'

class VendorProxy(User):

  class Meta:
    proxy = True
    verbose_name = 'Vendor'
    verbose_name_plural = 'Vendors'

class LaundrymartStore(models.Model):
  admin = models.ForeignKey(User, on_delete=models.CASCADE, blank=True, null=True, related_name='owned_stores')
  laundrymart_name = models.CharField(max_length=255, blank=False, null=False)
  store_id = models.UUIDField(blank=True, null=True, unique=True)
  laundrymart_logo=models.ImageField(blank=True, null=True, upload_to='laundrymart_logo')
  image = models.ImageField(blank=True, null=True, upload_to='laundrymart_image')
  stripe_customer_id=models.CharField(max_length=100, blank=True, null=True)
  stripe_connect_status = models.BooleanField(default=False)

  phone_number = models.CharField(max_length=255, unique=True)

  price_per_pound = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, help_text='Base price charged per pound of laundry (e.g. 2.50). This is the main rate shown to customers before any additional fees.')
  service_fee = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, help_text="Additional fixed fee or percentage added to every order. "
        "Examples: 2.50 → $2.50 flat fee | 0.10 → 10% if percentage mode is enabled. "
        "Leave blank or 0 if no service fee is charged.")
  service_fee_percentage=models.BooleanField(blank=True, null=True, default=False, help_text="Check this box (set to True) if the service fee should be calculated as a percentage "
        "of the order subtotal (e.g. 10% service fee). "
        "Leave unchecked (False) if you want to charge a fixed amount per order regardless of total.")

  vendor_description = models.TextField(blank=True, null=True)

  location=models.TextField(blank=True, null=True)
  lat = models.FloatField(blank=True, null=True)
  lng = models.FloatField(blank=True, null=True)

  location_map = PlainLocationField(based_fields=['location'], zoom=7, blank=True, null=True)

  secondary_location=models.TextField(blank=True, null=True)
  secondary_lat = models.FloatField(blank=True, null=True)
  secondary_lng = models.FloatField(blank=True, null=True)

  google_rating= models.DecimalField(max_digits=10, decimal_places=1, blank=True, null=True)

  minimum_order_weight = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, help_text='The minimum total weight (in pounds) required for an order to be placed. Leave blank or 0 if there is no minimum.')
  daily_capacity_limit = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, help_text='Maximum total weight (in pounds) this store can process in a single day. Leave blank or 0 for no daily limit.')

  turnaround_time_minimum_sunday = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
  turnaround_time_maximum_sunday = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

  turnaround_time_minimum_monday = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
  turnaround_time_maximum_monday = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

  turnaround_time_minimum_tuesday = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
  turnaround_time_maximum_tuesday = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

  turnaround_time_minimum_wednesday = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
  turnaround_time_maximum_wednesday = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

  turnaround_time_minimum_thursday = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
  turnaround_time_maximum_thursday = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

  turnaround_time_minimum_friday = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
  turnaround_time_maximum_friday = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

  turnaround_time_minimum_saturday = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
  turnaround_time_maximum_saturday = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

  operating_hours_start_sunday = models.TimeField(blank=True, null=True)
  operating_hours_end_sunday = models.TimeField(blank=True, null=True)
  is_closed_sunday = models.BooleanField(default=False)

  operating_hours_start_monday = models.TimeField(blank=True, null=True)
  operating_hours_end_monday = models.TimeField(blank=True, null=True)
  is_closed_monday = models.BooleanField(default=False)

  operating_hours_start_tuesday = models.TimeField(blank=True, null=True)
  operating_hours_end_tuesday = models.TimeField(blank=True, null=True)
  is_closed_tuesday = models.BooleanField(default=False)

  operating_hours_start_wednesday = models.TimeField(blank=True, null=True)
  operating_hours_end_wednesday = models.TimeField(blank=True, null=True)
  is_closed_wednesday = models.BooleanField(default=False)

  operating_hours_start_thursday = models.TimeField(blank=True, null=True)
  operating_hours_end_thursday = models.TimeField(blank=True, null=True)
  is_closed_thursday = models.BooleanField(default=False)

  operating_hours_start_friday = models.TimeField(blank=True, null=True)
  operating_hours_end_friday = models.TimeField(blank=True, null=True)
  is_closed_friday = models.BooleanField(default=False)

  operating_hours_start_saturday = models.TimeField(blank=True, null=True)
  operating_hours_end_saturday = models.TimeField(blank=True, null=True)
  is_closed_saturday = models.BooleanField(default=False)

  push_and_email_alerts = models.BooleanField(default=True)
  auto_accept_orders = models.BooleanField(default=False)
  employee_edit_permission=models.BooleanField(default=False)

  def __str__(self):
    return self.laundrymart_name

  class Meta:
    verbose_name = 'LaundryMart Store'
    verbose_name_plural = 'LaundryMart Stores'
  def average_rating(self):

    avg = self.received_reviews.aggregate(
      avg_rating=Avg('rating', output_field=FloatField())
    )['avg_rating']

    if avg is None:
      return None

    return round(avg, 2)

  @property
  def get_turnaround_time(self):
    local_now = timezone.localtime(timezone.now())
    weekday = local_now.weekday()  # 0: Monday, ..., 6: Sunday
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

    min_field = f'turnaround_time_minimum_{day_name}'
    max_field = f'turnaround_time_maximum_{day_name}'

    min_val = getattr(self, min_field)
    max_val = getattr(self, max_field)

    # If both are set, return formatted string
    if min_val is not None and max_val is not None:
      # Ensure proper formatting (e.g., 24.00 → 24, 24.50 → 24.5)
      min_str = str(float(min_val)).rstrip('0').rstrip('.') if '.' in str(min_val) else str(min_val)
      max_str = str(float(max_val)).rstrip('0').rstrip('.') if '.' in str(max_val) else str(max_val)
      return f'{min_str}-{max_str}'
    return None

  @property
  def is_open_now(self):
    local_now = timezone.localtime(timezone.now())
    weekday = local_now.weekday()  # 0: Monday, ..., 6: Sunday
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

    # Check if explicitly closed today
    is_closed_field = f'is_closed_{day_name}'
    if getattr(self, is_closed_field):
      return False

    # Get start and end times
    start_field = f'operating_hours_start_{day_name}'
    end_field = f'operating_hours_end_{day_name}'

    start_time = getattr(self, start_field)
    end_time = getattr(self, end_field)

    if start_time is None or end_time is None:
      return False

    now_time = local_now.time()
    logger.info(f'is_open_now check: local_now={local_now}, now_time={now_time}, start={start_time}, end={end_time}')

    return start_time <= now_time < end_time

  @property
  def closes_at(self):
    local_now = timezone.localtime(timezone.now())
    weekday = local_now.weekday()
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

    is_closed_field = f'is_closed_{day_name}'
    if getattr(self, is_closed_field):
      return None

    end_field = f'operating_hours_end_{day_name}'
    end_time = getattr(self, end_field)

    return end_time

  def save(self, *args, **kwargs):
    # Validate first
    self.full_clean()
    # Auto-generate store_id ONLY for vendors
    if not self.store_id:
      self.store_id = uuid.uuid4()

    if hasattr(self, 'location_map') and self.location_map:
      try:
        lat_str, lng_str = str(self.location_map).split(',')
        self.lat = float(lat_str.strip())
        self.lng = float(lng_str.strip())
      except (ValueError, TypeError):
        pass

    if self.lat is not None and self.lng is not None:
      addr = reverse_geocode_google(self.lat, self.lng)
      if addr:
        self.location = addr

    # Save the object
    super().save(*args, **kwargs)

class SecondaryLocation(models.Model):
  user=models.ForeignKey(User,on_delete=models.CASCADE, related_name='secondary_locations')
  type=models.CharField(max_length=100, blank=True, null=True)
  location=models.TextField(blank=True, null=True)
  lat=models.FloatField(blank=True, null=True)
  lng=models.FloatField(blank=True, null=True)

  created_at=models.DateTimeField(auto_now_add=True)
  updated=models.DateTimeField(auto_now=True)

  def __str__(self):
    return

  class Meta:
    verbose_name = 'Secondary Location'
    verbose_name_plural = 'Secondary Locations'

class Service(models.Model):
  vendor = models.ForeignKey(LaundrymartStore, on_delete=models.CASCADE, related_name='vendor_services')
  image = models.ImageField(blank=True, null=True, upload_to='service_image')
  service_name = models.CharField(max_length=255, blank=False, null=False)
  price_per_pound=models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)

  def __str__(self):
    return self.service_name

class Employee(models.Model):
  laundrymart_store = models.ForeignKey(LaundrymartStore, on_delete=models.CASCADE, related_name='employees')
  username = models.CharField(max_length=20, blank=False, null=False, db_index=True)
  name=models.CharField(max_length=100, blank=True, null=True)
  email=models.EmailField(max_length=100, blank=True, null=True, unique=True)
  password = models.CharField(max_length=128, blank=False, null=False)  # Hashed password storage

  def save(self, *args, **kwargs):

    if not self.password.startswith('pbkdf2_sha256$'):  # Check if already hashed
      self.password = make_password(self.password)

    super().save(*args, **kwargs)

  def check_password(self, raw_password):
    return check_password(raw_password, self.password)

  class Meta:
    unique_together = ('laundrymart_store', 'username')