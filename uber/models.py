import requests
from django.db import models
from django.core.validators import MinValueValidator
from accounts.models import User
from payment.models import Order
from uber.cache_access_token import UBER_BASE_URL, uber_headers

# Create your models here.
SERVICE_TYPE_CHOICE=[
  ('drop_off', 'Drop off'),
  ('pickup', 'Pick up'),
  ('full_service', 'Full service')
]
STATUS_CHOICES=[
  ('draft', 'Draft'),
  ('pending', 'Pending'),
  ('accepted', 'Accepted'),
  ('rejected', 'Rejected'),
  ('delayed', 'Delayed')
]

VALIDATION_STATUS_CHOICES = [
    ('pending', 'Pending'),
    ('in_progress', 'In Progress'),
    ('authorized', 'Authorized'),
    ('requires_action', 'Requires Action'),
    ('succeeded', 'Succeeded'),
    ('failed', 'Failed'),
    ('canceled', 'Canceled'),
    ('expired', 'Expired'),
]
class DeliveryQuote(models.Model):
  service_type=models.CharField(max_length=50, blank=True, null=True, choices=SERVICE_TYPE_CHOICE)
  status=models.CharField(max_length=50, blank=True, null=True, choices=STATUS_CHOICES, default='draft')
  quote_id = models.CharField(blank=True, null=True,unique=True, max_length=255, verbose_name='Order')
  customer=models.ForeignKey(User, on_delete=models.CASCADE, related_name='delivery_quotes')
  customer_note = models.TextField(blank=True, null=True)
  pickup_address=models.TextField(blank=True, null=True)
  dropoff_address=models.TextField(blank=True, null=True)
  pickup_latitude=models.FloatField(blank=True, null=True)
  pickup_longitude=models.FloatField(blank=True, null=True)
  dropoff_latitude=models.FloatField(blank=True, null=True)
  dropoff_longitude=models.FloatField(blank=True, null=True)
  pickup_phone_number=models.CharField(blank=True, null=True, max_length=50)
  dropoff_phone_number=models.CharField(blank=True, null=True, max_length=50)
  manifest_total_value=models.DecimalField(max_digits=12, decimal_places=2,blank=True, null=True, validators=[MinValueValidator(0)])
  insurance_amount=models.DecimalField(max_digits=12, decimal_places=2,blank=True, null=True, validators=[MinValueValidator(0)], default=0)
  external_store_id=models.CharField(blank=True, null=True, db_index=True)
  payment_method_id=models.CharField(max_length=255, blank=True, null=True)

  validation_status=models.CharField(max_length=255, blank=True, null=True, choices=VALIDATION_STATUS_CHOICES, default="pending")
  validation_pi_id=models.CharField(max_length=255, blank=True, null=True, db_index=True)
  validation_amount_cents = models.PositiveIntegerField(blank=True, null=True)



  fee=models.DecimalField(blank=True, null=True, max_digits=10, decimal_places=2)
  currency=models.CharField(max_length=20, blank=True, null=True, default='usd')
  currency_type=models.CharField(max_length=20, blank=True, null=True, default='USD')
  dropoff_eta=models.DateTimeField(blank=True, null=True)

  duration = models.PositiveIntegerField( blank=True, null=True, help_text="Estimated total duration in minutes")
  pickup_duration = models.PositiveIntegerField(blank=True, null=True,help_text="Estimated pickup duration in minutes")

  pickup_ready_dt = models.DateTimeField(blank=True, null=True)

  dropoff_deadline = models.DateTimeField(blank=True, null=True)

  created=models.DateTimeField(blank=True, null=True)
  expires=models.DateTimeField(blank=True, null=True)

  saved_at = models.DateTimeField(auto_now_add=True, verbose_name='Date')

  class Meta:
    verbose_name = "Uber Direct Delivery Quote"
    verbose_name_plural = "Uber Direct Delivery Quotes"
    ordering = ['-saved_at']


  def __str__(self):
    return f"Quote {self.quote_id} - ${self.fee if self.fee else 0} - Expires {self.expires}"



DELIVERABLE_ACTION_CHOICES=[
  ('deliverable_action_meet_at_door', 'deliverable_action_meet_at_door'),
  ('deliverable_action_leave_at_door', 'deliverable_action_leave_at_door')
]
DELIVERY_STATUS_CHOICES=[
  ('pending', 'Pending'),
  ('pickup_true', 'Pickup True'),
  ('pickup_false', 'Pickup False'),
  ('pickup_complete', 'Pickup Comuplete'),
  ('dropoff_true', 'Dropoff True'),
  ('dropoff_false', 'Dropoff False'),
  ('delivered', 'Delivered'),
  ('canceled', 'Canceled'),
  ('returned', 'Returned')

]
class Delivery(models.Model):
  delivery_uid = models.CharField(max_length=255,unique=True,blank=True,null=True)

  quote = models.OneToOneField(DeliveryQuote,on_delete=models.CASCADE,null=True,blank=True)
  quote_uid=models.CharField(max_length=100, blank=True, null=True, db_index=True)
  parent_delivery=models.ForeignKey('self', null=True, on_delete=models.CASCADE,related_name='child_deliveries')

  batch_id=models.CharField(max_length=255,blank=True,null=True)

  customer = models.ForeignKey(
    User,
    on_delete=models.CASCADE,
    related_name='deliveries'
  )

  idempotency_key = models.CharField(max_length=255, blank=True, null=True, unique=True)

  courier_imminent= models.BooleanField(default=False)

  pickup_name = models.CharField(max_length=255, blank=True, null=True)
  pickup_address = models.TextField(blank=True, null=True)
  pickup_phone_number = models.CharField(max_length=30, blank=True, null=True)
  pickup_latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
  pickup_longitude = models.DecimalField(max_digits=10, decimal_places=6, blank=True, null=True)
  pickup_notes = models.TextField(blank=True, null=True)
  pickup_ready=models.DateTimeField(blank=True, null=True)
  pickup_business_name = models.CharField(max_length=255, blank=True, null=True)

  dropoff_name = models.CharField(max_length=255, blank=True, null=True)
  dropoff_address = models.TextField(blank=True, null=True)
  dropoff_phone_number = models.CharField(max_length=30, blank=True, null=True)
  dropoff_latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
  dropoff_longitude = models.DecimalField(max_digits=10, decimal_places=6, blank=True, null=True)
  dropoff_notes = models.TextField(blank=True, null=True)
  dropoff_seller_notes = models.TextField(blank=True, null=True)
  dropoff_business_name = models.CharField(max_length=255, blank=True, null=True)


  external_store_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
  external_id = models.CharField(max_length=100, blank=True, null=True)

  deliverable_action = models.CharField(max_length=100, blank=True, null=True, choices=DELIVERABLE_ACTION_CHOICES, default='deliverable_action_meet_at_door')

  # Response fields from Uber (updated via webhook or polling)
  status = models.CharField(max_length=100, blank=True, null=True, choices=DELIVERY_STATUS_CHOICES)  # e.g., pending, driver_en_route, completed
  fee = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)  # In cents
  total_fee=models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
  currency = models.CharField(max_length=3, default='usd')
  tracking_url = models.URLField(blank=True, null=True)
  dropoff_eta = models.DateTimeField(blank=True, null=True)
  dropoff_deadline = models.DateTimeField(blank=True, null=True)

  completion_lat=models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True)
  completion_lng=models.DecimalField(max_digits=10, decimal_places=6, blank=True, null=True)

  courier_name = models.CharField(max_length=255, blank=True, null=True)
  courier_tip=models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
  courier_phone = models.CharField(max_length=30, blank=True, null=True)
  courier_vehicle_type = models.CharField(max_length=50, blank=True, null=True)

  uber_raw_response = models.JSONField(blank=True, null=True)

  created_at_uber = models.DateTimeField(blank=True, null=True)
  updated_at_uber = models.DateTimeField(blank=True, null=True)

  # Local timestamps
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  class Meta:
    verbose_name = "Uber Direct Delivery"
    verbose_name_plural = "Uber Direct Deliveries"
    ordering = ['-created_at']

  def __str__(self):
    return f"Delivery {self.delivery_uid or 'Pending'} - {self.external_id or self.pk}"

  @property
  def is_return_leg(self):
    return self.parent_delivery is None
  @property
  def has_return_leg(self):
    return self.quote.service_type=='full_service' and self.parent_delivery is None

BAG_CHOICES=[
  ('small', 'Small'),
  ('big', 'Big'),
  ('medium', 'Medium')
]
class ManifestItem(models.Model):
  delivery_quote=models.ForeignKey(DeliveryQuote, on_delete=models.CASCADE, blank=True, null=True, related_name='manifest_items')
  delivery=models.ForeignKey(Delivery,on_delete=models.CASCADE, blank=True, null=True, related_name='manifest_items')
  stripe_order=models.ForeignKey(Order,on_delete=models.CASCADE, blank=True, null=True, related_name='manifest_items')
  name=models.CharField(max_length=255, default='Bag')
  quantity=models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
  size=models.CharField(max_length=255, choices=BAG_CHOICES)
  dimensions=models.JSONField(blank=True, null=True)
  weight=models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
  price=models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
  vat_percentage=models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)