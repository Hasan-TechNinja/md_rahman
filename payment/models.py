from django.db import models

# Create your models here.
# orders/models.py
from django.db import models
from laundrymart import settings
from django.core.validators import MinValueValidator
import uuid

from accounts.models import LaundrymartStore, User
import logging
logger = logging.getLogger(__name__)



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
  uuid = models.CharField(editable=False, unique=True, verbose_name='Order Id')
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
  estimated_value=models.DecimalField(max_digits=12, decimal_places=2,blank=True, null=True, validators=[MinValueValidator(0)], verbose_name='Estimated value before final weighing', help_text='In cents')
  weight_in_pounds = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
  service_charge_cents = models.PositiveIntegerField(blank=True, null=True, help_text='Laundry fee')  # your laundry fee
  delivery_fee_cents = models.PositiveIntegerField(blank=True, null=True)   # final Uber fee
  final_total_cents = models.PositiveIntegerField(blank=True, null=True, help_text='(Laundry fee* weight in pounds)+platform fee + insurance amount if there any+ delivery_fee')


  status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='pending_setup')

  created_at = models.DateTimeField(auto_now_add=True, verbose_name='Date')
  updated_at = models.DateTimeField(auto_now=True)
  completed_at =models.DateTimeField(blank=True, null=True)

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
  @property
  def get_parent_quote_schedule(self):
    from uber.models import DeliveryQuote

    try:
        parent_quote = DeliveryQuote.objects.get(
            quote_id=self.uber_pickup_quote_id
        )
        return parent_quote.pickup_ready_dt
    except DeliveryQuote.DoesNotExist:
        return None

  def generate_order_id(self):
    import secrets
    import string
    chars = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(5))

  def save(self, *args, **kwargs):    
    if not self.uuid:
      new_id = self.generate_order_id()

      # ensure uniqueness (very important)
      while Order.objects.filter(uuid=new_id).exists():
        new_id = self.generate_order_id()

      self.uuid = new_id

    super().save(*args, **kwargs)

  def create_progress_steps(self):
    logger.info('create progression function triggered')
    service_type = self.get_service_type()
    logger.info(f'service type: {service_type}')
    if not service_type:
      return

    if service_type == "Pick up":
      steps = [
        {"name": "placed","display_name":"Order placed","description":"Your order has been received", "is_complete": True, "sequence_no": 0},
        {"name": "accepted","display_name":"Order accepted by LaundryMart","description":"Laundromat confirmed your order", "is_complete": True, "sequence_no": 1},
        {"name": "pickup_courier_assigned","display_name":"Driver assigned for pickup","description":"Your laundry has been collected", "is_complete": False, "sequence_no": 2},
        {"name": "picked_up_by_laundrymart","display_name":"Laundry received","description":"Your laundry is being processed", "is_complete": False, "sequence_no": 3},
        {"name": "laundry_complete","display_name":"Laundry complete","description":"Your laundry is ready for pickup/delivery", "is_complete": False, "sequence_no": 4},
        {"name": "pickup_customer","display_name":"Pick up your laundry", "description":"Please pick up your laundry", "is_complete": False, "sequence_no": 5},
        {"name": "delivered","display_name":"Delivered", "description":"Order completed", "is_complete": False, "sequence_no": 6},
      ]

    elif service_type == "Full service":
      steps = [
        {"name": "placed","display_name":"Order placed","description":"Your order has been received", "is_complete": True, "sequence_no": 0},
        {"name": "accepted","display_name":"Order accepted by LaundryMart","description":"Laundromat confirmed your order", "is_complete": True, "sequence_no": 1},
        {"name": "pickup_courier_assigned", "display_name": "Driver assigned for pickup",
         "description": "Your laundry has been collected", "is_complete": False, "sequence_no": 2},
        {"name": "picked_up_by_laundrymart", "display_name": "Laundry received",
         "description": "Your laundry is being processed", "is_complete": False, "sequence_no": 3},
        {"name": "laundry_complete", "display_name": "Laundry complete",
         "description": "Your laundry is ready for pickup/delivery", "is_complete": False, "sequence_no": 4},
        {"name": "return_courier_assigned","display_name":"Driver assigned for return","description":"On the way to you", "is_complete": False, "sequence_no": 5},
        {"name": "delivered","display_name":"Delivered", "description":"Order completed", "is_complete": False, "sequence_no": 6},
      ]

    elif service_type == "Drop off":
      steps = [
        {"name": "placed","display_name":"Order placed","description":"Your order has been received", "is_complete": True, "sequence_no": 0},
        {"name": "accepted","display_name":"Order accepted by LaundryMart","description":"Laundromat confirmed your order", "is_complete": True, "sequence_no": 1},
        {"name": "customer_drop_off","display_name":"Laundry drop off","description":"Please drop off your laundry", "is_complete": True, "sequence_no": 2},
        {"name": "picked_up_by_laundrymart","display_name":"Laundry received","description":"Your laundry is being processed", "is_complete": False, "sequence_no": 3},
        {"name": "laundry_complete", "display_name": "Laundry complete",
         "description": "Your laundry is ready for pickup/delivery", "is_complete": False, "sequence_no": 4},
        {"name": "picked_up_by_courier", "display_name": "Driver assigned for return", "description":"On the way to you", "is_complete": False, "sequence_no": 5},
        {"name": "delivered", "display_name": "Delivered", "description":"Order completed", "is_complete": False, "sequence_no": 6},
      ]

    else:
      # fallback or raise error
      logger.error('progression error')
      return
    logger.info(f'progression steps:{steps}')

    for step in steps:
      OrderProgression.objects.create(
        order=self,
        name=step["name"],
        display_name=step["display_name"],
        description=step["description"],
        is_complete=step["is_complete"],
        sequence_no=step["sequence_no"]
      )


class OrderProgression(models.Model):
  order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='progressions')
  name = models.CharField(max_length=100, blank=True, null=True)
  display_name = models.CharField(max_length=100, blank=True, null=True)
  description = models.TextField(blank=True, null=True)
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

class SalesReport(models.Model):
  pass

# payment/models.py   (add at the bottom)

class VendorPayout(models.Model):
  vendor_admin = models.ForeignKey(
    User,
    on_delete=models.CASCADE,
    related_name='payouts'
  )
  associated_store = models.ForeignKey(
    LaundrymartStore,
    on_delete=models.CASCADE,
    related_name='store_payouts'
  )
  order = models.ForeignKey(
    Order,           # your Order model
    on_delete=models.SET_NULL,
    blank=True,
    null=True,
    related_name='vendor_payouts'
  )
  payment_intent_id = models.CharField(
    max_length=255,
    blank=True,
    null=True,
    unique=True,  # ← Prevents duplicate payouts for same charge
    help_text="Stripe PaymentIntent ID (pi_...)"
  )

  idempotency_key = models.CharField(
    max_length=255,
    blank=True,
    null=True,
    unique=True,  # ← Extra safety
    help_text="Internal idempotency key used when creating PaymentIntent"
  )
  stripe_payout_id = models.CharField(max_length=255, blank=True, null=True)
  amount = models.DecimalField(max_digits=12, decimal_places=2)
  currency = models.CharField(max_length=3, default='USD')
  status = models.CharField(max_length=50, default='pending')
  platform_fee = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
  added_stripe_fee = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
  is_instant = models.BooleanField(default=True)
  initiated_by = models.ForeignKey(
    User,
    on_delete=models.SET_NULL,
    null=True,
    blank=True
  )
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  class Meta:
    verbose_name = "Vendor Payout"
    verbose_name_plural = "Vendor Payouts"
    ordering = ['-created_at']

  def initiate_instant_payout(self, requested_by=None):
    """
    Initiate instant payout to vendor's Stripe Connect account
    Returns (success: bool, message: str)
    """
    import stripe
    if not self.associated_store or not self.associated_store.admin.stripe_connect_account_id:
      return False, "Vendor does not have a connected Stripe account"

    if self.status != 'pending':
      return False, f"Payout is already in {self.status} status"

    if not self.order or not self.order.final_total_cents:
      return False, "No associated order or amount to payout"

    try:
      # Official Stripe way: Create a Payout on the Connect account
      payout = stripe.Payout.create(
        amount=int(self.amount * 100),  # convert to cents
        currency=self.currency.lower(),
        stripe_account=self.associated_store.admin.stripe_connect_account_id,
        metadata={
          "vendor_payout_id": str(self.pk),
          "order_uuid": str(self.order.uuid) if self.order else "",
          "initiated_by": str(requested_by) if requested_by else "super_admin"
        }
      )

      # Update our model
      self.stripe_payout_id = payout.id
      self.status = payout.status
      self.is_instant = True
      if requested_by:
        self.initiated_by = requested_by
      self.save()

      return True, f"Instant payout initiated successfully. Payout ID: {payout.id}"

    except stripe.error.StripeError as e:
      error_msg = e.user_message if hasattr(e, 'user_message') else str(e)
      self.status = 'failed'
      self.save()
      return False, f"Stripe error: {error_msg}"
    except Exception as e:
      self.status = 'failed'
      self.save()
      return False, f"Unexpected error: {str(e)}"

  def __str__(self):
    return f"Payout {self.stripe_payout_id} - ${self.amount} - {self.vendor_admin}"