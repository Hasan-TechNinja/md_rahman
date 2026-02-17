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

STATUS_CHOICES = [
    ('pending_setup', 'Pending Card Setup'),
    ('processing', 'Processing'),
    ('card_saved', 'Card Saved'),
    ('awaiting_pickup', 'Awaiting Pickup'),

    # Pickup and Drop-Off services (only one leg involved)
    ('pickup_courier_scheduled', 'Pickup courier Scheduled'),
    ('pickup_courier_assigned', 'Pickup Courier Assigned'),
    ('pickup_arriving_soon', 'Pickup Arriving Soon'),
    ('picked_up_by_courier', 'Picked Up by Courier'),

    ('moving_towards_customer', 'Moving towards customer'),
    ('moving_towards_laundrymart', 'Moving towards laundrymart'),

    ('return_scheduled', 'Return courier scheduled'),
    ('return_courier_assigned', 'Return courier assigned.'),


    ('picked_up_by_customer', 'Picked up by Customer'),
    ('dropping_of_soon', 'Dropping off very soon'),
    ('picked_up_by_laundrymart', 'Picked up by Laundrymart'),

    ('arrived_at_laundry', 'Arrived at Laundry'),

    # Laundry internal processing
    ('received', 'Received'),
    ('weighed', 'Weighed & Priced'),
    ('charged', 'Charged'),

    ('processing_completion', 'Processing Completion'),
    ('completion_failed', 'Completion Failed'),
    ('completed', 'Completed'),

    # Failure cases
    ('canceled', 'Canceled'),
    ('wait_for_support', 'Wait for support')
]

class Order(models.Model):
  """
  Main order for laundry pickup → weigh → return delivery
  """
  uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, verbose_name='Order Id')
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

  pickup_delivery=models.OneToOneField('uber.Delivery', on_delete=models.CASCADE, related_name='uber_pickup_delivery', blank=True, null=True)

  uber_return_quote_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)
  uber_parent_delivery_id= models.CharField(max_length=100, blank=True, null=True, db_index=True)
  parent_delivery = models.OneToOneField('uber.Delivery', on_delete=models.CASCADE, related_name='uber_parent_delivery',blank=True, null=True)

  uber_return_delivery_id = models.CharField(max_length=100, blank=True, null=True, db_index=True)

  return_delivery=models.OneToOneField('uber.Delivery', on_delete=models.CASCADE, related_name='uber_return_delivery', blank=True, null=True)

  # Stripe
  stripe_customer_id = models.CharField(max_length=100, blank=True, null=True)
  stripe_default_pm_id = models.CharField(max_length=100, blank=True, null=True)  # saved payment method

  # Pricing
  insurance_amount = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True,
                                         validators=[MinValueValidator(0)], default=0)
  weight_in_pounds = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
  service_charge_cents = models.PositiveIntegerField(blank=True, null=True)  # your laundry fee
  delivery_fee_cents = models.PositiveIntegerField(blank=True, null=True)   # final Uber fee
  final_total_cents = models.PositiveIntegerField(blank=True, null=True)


  status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending_setup')

  created_at = models.DateTimeField(auto_now_add=True, verbose_name='Date')
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

  def get_service_type(self):
    from uber.models import DeliveryQuote
    return DeliveryQuote.objects.get(quote_id=self.uber_pickup_quote_id).get_service_type_display()

  def create_progress_steps(self):
    print('create progression function triggered')
    service_type = self.get_service_type()
    print('service type')
    if not service_type:
      return

    if service_type == "pickup":
      steps = [
        {"name": "accepted", "is_complete": True, "sequence_no": 1},
        {"name": "laundry_received", "is_complete": False, "sequence_no": 2},
        {"name": "weighed", "is_complete": False, "sequence_no": 3},
        {"name": "processing_completion", "is_complete": False, "sequence_no": 4},
        {"name": "return_scheduled", "is_complete": False, "sequence_no": 5},
        {"name": "return_courier_assigned", "is_complete": False, "sequence_no": 6},
        {"name": "picked_up_by_customer", "is_complete": False, "sequence_no": 7},
      ]

    elif service_type == "full_service":
      steps = [
        {"name": "accepted", "is_complete": True, "sequence_no": 1},
        {"name": "pickup_scheduled", "is_complete": False, "sequence_no": 2},
        {"name": "pickup_courier_assigned", "is_complete": False, "sequence_no": 3},
        {"name": "picked_up_by_courier", "is_complete": False, "sequence_no": 4},
        {"name": "picked_up_by_laundrymart", "is_complete": False, "sequence_no": 5},
        {"name": "return_scheduled", "is_complete": False, "sequence_no": 6},
        {"name": "return_courier_assigned", "is_complete": False, "sequence_no": 7},
        {"name": "picked_up_by_customer", "is_complete": False, "sequence_no": 8},
      ]

    elif service_type == "drop_off":
      steps = [
        {"name": "accepted", "is_complete": True, "sequence_no": 1},
        {"name": "pickup_scheduled", "is_complete": False, "sequence_no": 2},
        {"name": "pickup_courier_assigned", "is_complete": False, "sequence_no": 3},
        {"name": "picked_up_by_courier", "is_complete": False, "sequence_no": 4},
        {"name": "picked_up_by_laundrymart", "is_complete": False, "sequence_no": 5},
        {"name": "weighed", "is_complete": False, "sequence_no": 6},
        {"name": "processing_completion", "is_complete": False, "sequence_no": 7},
      ]

    else:
      # fallback or raise error
      return
    print('progression steps:', steps)

    for step in steps:
      OrderProgression.objects.create(
        order=self,
        name=step["name"],
        is_complete=step["is_complete"],
        sequence_no=step["sequence_no"]
      )


class OrderProgression(models.Model):
  order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='progressions')
  name = models.CharField(max_length=100, blank=True, null=True)
  is_complete=models.BooleanField(default=False)
  sequence_no = models.PositiveSmallIntegerField(blank=True, null=True)

  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)


  def __str__(self):
    return f"Order {self.order.uuid} - {self.name}({self.is_complete}"
  class Meta:
    ordering=['-created_at']


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


class LaundrymartPaymentMethod(models.Model):
  laundrymart_admin = models.ForeignKey(User, on_delete=models.CASCADE)
  stripe_external_account_id = models.CharField(max_length=255, unique=True)
  stripe_payment_method_id = models.CharField(max_length=100)
  brand = models.CharField(max_length=50)  # e.g., 'Visa', 'Mastercard'
  last4 = models.CharField(max_length=4)
  exp_month = models.PositiveIntegerField()
  exp_year = models.PositiveIntegerField()
  is_default = models.BooleanField(default=False)

  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  class Meta:
    ordering = ['-is_default', '-created_at']  # Optimized for listing defaults first.

  def __str__(self):
    return f"{self.brand} **** {self.last4}"
