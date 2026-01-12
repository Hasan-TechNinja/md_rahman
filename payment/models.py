from django.db import models

# Create your models here.
# orders/models.py
from django.db import models
from laundrymart import settings
from django.core.validators import MinValueValidator
import uuid

from accounts.models import LaundrymartStore, User


class SavedPaymentMethod(models.Model):
  """Store references to user's payment methods in Stripe"""
  user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payment_methods')
  stripe_payment_method_id = models.CharField(max_length=100)

  # Store display info only (non-sensitive)
  last4 = models.CharField(max_length=4)
  card_brand = models.CharField(max_length=20)  # visa, mastercard, etc.
  exp_month = models.IntegerField()
  exp_year = models.IntegerField()

  # Optional: store a recognizable name for the card
  nickname = models.CharField(max_length=50, blank=True, null=True)

  # Is this the default payment method?
  is_default = models.BooleanField(default=False)

  # When the card was added
  created_at = models.DateTimeField(auto_now_add=True)

  class Meta:
    ordering = ['-is_default', '-created_at']

  def __str__(self):
    return f"{self.card_brand} **** {self.last4}"

class Order(models.Model):
  """
  Main order for laundry pickup → weigh → return delivery
  """
  uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
  user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='orders')
  service_provider=models.ForeignKey(LaundrymartStore, on_delete=models.CASCADE, related_name='received_orders', blank=True, null=True)

  # Addresses (stored as JSON strings to match Uber format – you can change later if needed)
  pickup_address = models.TextField(blank=True, null=True)
  dropoff_address = models.TextField(blank=True, null=True)

  pickup_latitude=models.FloatField(blank=True, null=True)
  pickup_longitude=models.FloatField(blank=True, null=True)
  dropoff_latitude=models.FloatField(blank=True, null=True)
  dropoff_longitude=models.FloatField(blank=True, null=True)

  customer_note = models.TextField(blank=True, null=True)
  # Uber tracking
  uber_pickup_quote_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
  uber_pickup_delivery_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)

  pickup_delivery=models.OneToOneField('uber.Delivery', on_delete=models.CASCADE, related_name='uber_pickup_deivery', blank=True, null=True)

  uber_return_quote_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
  uber_parent_delivery_id= models.CharField(max_length=100, blank=True, null=True, db_index=True)
  parent_delivery = models.OneToOneField('uber.Delivery', on_delete=models.CASCADE, related_name='uber_parent_deivery',blank=True, null=True)

  uber_return_delivery_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)

  return_delivery=models.OneToOneField('uber.Delivery', on_delete=models.CASCADE, related_name='uber_return_delivery', blank=True, null=True)

  # Stripe
  stripe_customer_id = models.CharField(max_length=100, blank=True, null=True)
  stripe_default_pm_id = models.CharField(max_length=100, blank=True, null=True)  # saved payment method

  # Pricing
  weight_in_pounds = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
  service_charge_cents = models.PositiveIntegerField(blank=True, null=True)  # your laundry fee
  delivery_fee_cents = models.PositiveIntegerField(blank=True, null=True)   # final Uber fee
  final_total_cents = models.PositiveIntegerField(blank=True, null=True)

  # Status flow
  STATUS_CHOICES = [
    ('pending_setup', 'Pending Card Setup'),
    ('processing', 'Processing – Creating Delivery'),
    ('card_saved', 'Card Saved – Awaiting Pickup'),
    ('picked_up', 'Picked Up'),
    ('weighed', 'Weighed & Priced'),
    ('charged', 'Charged'),
    ('return_scheduled', 'Return Delivery Scheduled'),
    ('completed', 'Completed'),
    ('canceled', 'Canceled'),
  ]
  status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending_setup')

  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  class Meta:
    indexes = [
      models.Index(fields=['status']),
      models.Index(fields=['user']),
      models.Index(fields=['stripe_customer_id']),
    ]
    ordering = ['-created_at']

  def __str__(self):
    return f"Order {self.uuid} – {self.user} – {self.status}"

# models.py (add these fields via migration)
class PendingStripeOrder(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pending_stripe_orders')
    metadata = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    status = models.CharField(
        max_length=20,
        choices=[("pending", "Pending"), ("completed", "Completed"), ("failed", "Failed")],
        default="pending"
    )
    stripe_session_id = models.CharField(max_length=255, blank=True, null=True, unique=True)

    def __str__(self):
        return f"PendingStripeOrder for {self.user.email} at {self.created_at}"

    class Meta:
        ordering = ['-created_at']

class Payment(models.Model):
  """
  Final charge record (one-to-one with Order)
  """
  order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name='payment')
  stripe_payment_intent_id = models.CharField(max_length=100, unique=True)
  amount_cents = models.PositiveIntegerField()
  status = models.CharField(max_length=20, default='pending')  # succeeded, failed, etc.
  created_at = models.DateTimeField(auto_now_add=True)

  def __str__(self):
    return f"Payment {self.stripe_payment_intent_id} for Order {self.order.uuid}"