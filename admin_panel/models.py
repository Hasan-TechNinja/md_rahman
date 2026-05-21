from django.core.cache import cache
from django.db import models
from solo.models import SingletonModel
from django.utils.translation import gettext_lazy as _
import logging

from laundrymart.settings import BASE_URL

logger = logging.getLogger(__name__)


# Create your models here.
class GlobalManifest(SingletonModel):

  # --- Customer App: ordering   page Section ---
  service_fee=models.DecimalField(max_digits=10,decimal_places=2, blank=True,help_text='Percentage based dynamic fee', null=True)
  insurance_fee=models.DecimalField(max_digits=10,decimal_places=2, blank=True, null=True)

  customer_stripe_charge_in_percentage=models.DecimalField(max_digits=10,decimal_places=2, blank=True, null=True, help_text='Stripe charge percentage based dynamic fee')
  customer_stripe_charge_added_cents=models.PositiveIntegerField(blank=True, null=True, help_text='Stripe charge added cents based dynamic fee')

  payout_transaction_charge_in_percentage=models.DecimalField(max_digits=10,decimal_places=2, blank=True, null=True, help_text='Payout transaction charge percentage based dynamic fee')
  payout_transaction_added_cents = models.PositiveIntegerField(blank=True, null=True, help_text='Payout transaction added cents based dynamic fee')

  small_bag_text=models.CharField(max_length=200,blank=True, null=True)
  small_bag_image=models.ImageField(upload_to='bag_images/',blank=True, null=True)

  medium_bag_text=models.CharField(max_length=200,blank=True, null=True)
  medium_bag_image=models.ImageField(upload_to='bag_images/',blank=True, null=True)

  large_bag_text=models.CharField(max_length=200,blank=True, null=True)
  large_bag_image=models.ImageField(upload_to='bag_images/',blank=True, null=True)

  # --- Customer App: Front page Section ---
  cust_navbar_text = models.CharField(max_length=100, default="Hello {name}, ready for laundry?", help_text="Navbar greeting with placeholder {name}")
  full_service_text = models.TextField(blank=True, null=True)
  drop_off_text = models.TextField(blank=True, null=True)
  pickup_text = models.TextField(blank=True, null=True)

  # --- Customer App: More Section ---
  customer_faq = models.JSONField(default=list, help_text="List of {question, answer}. Format: [{\"question\": \"How do I schedule a pickup?\", \"answer\": \"You can schedule a pickup by...\"}, ...]")
  customer_privacy_policy = models.TextField(blank=True, null=True)
  customer_terms_conditions = models.TextField(blank=True, null=True)
  customer_laundry_protections = models.TextField(blank=True, null=True)
  customer_account_delete_text = models.TextField(blank=True, null=True)

  # --- Customer App: Invite Friends ---
  invite_top_text = models.TextField(blank=True, null=True)
  invite_image = models.ImageField(upload_to='invites/', blank=True, null=True)
  invite_share_link_text = models.CharField(max_length=255, blank=True, null=True)
  invite_get_credit_config = models.JSONField(default=dict,
                                              help_text="Format: {\"bold_part\": \"You'll get $10 in credit\","
                                              " \"normal_part\": \"for each friend you refer when they complete their first order!\"}")

  # --- Vendor App ---
  vendor_register_page_text = models.TextField(blank=True, null=True)
  vendor_order_history_info_text = models.TextField(blank=True, null=True)
  vendor_faq = models.JSONField(default=list,
                                help_text="List of {question, answer}. Format: [{\"question\": \"How do I schedule a pickup?\","
                                          " \"answer\": \"You can schedule a pickup by...\"}, ...]")
  vendor_privacy_policy = models.TextField(blank=True, null=True)
  vendor_terms_conditions = models.TextField(blank=True, null=True)
  vendor_laundry_protection = models.TextField(blank=True, null=True)
  vendor_account_delete_text = models.TextField(blank=True, null=True)

  updated_at = models.DateTimeField(auto_now=True)

  def save(self, *args, **kwargs):
    super().save(*args, **kwargs)
    print(self)
    from customer.serializers import CustomerGlobalManifestSerializer
    from vendor.serializers import VendorGlobalManifestSerializer
    customer_global_manifest_data = CustomerGlobalManifestSerializer(self).data
    vendor_global_manifest_data = VendorGlobalManifestSerializer(self).data

    logger.info("GlobalManifest updated, refreshing cache with new data.")
    cache.set('customer_global_manifest_data', customer_global_manifest_data, timeout=None)
    cache.set('vendor_global_manifest_data', vendor_global_manifest_data, timeout=None)


  @classmethod
  def get_customer_cached_config(cls):
    # Try to get from Redis
    data = cache.get('customer_global_manifest_data')
    logger.info(f'get_customer_cached_config called:{data}')
    from customer.serializers import CustomerGlobalManifestSerializer
    if not data:
      # Fallback to DB and update Redis if Redis was cleared
      logger.info('Fallback to DB and update Redis if Redis was cleared')
      instance = cls.get_solo()
      data = CustomerGlobalManifestSerializer(instance).data
      cache.set('customer_global_manifest_data', data, timeout=None)
    logger.info(f'Final data:{data}')
    return data

  @classmethod
  def get_vendor_cached_config(cls):
    data = cache.get('vendor_global_manifest_data')
    logger.info(f'get_vendor_cached_config called:{data}')
    from vendor.serializers import VendorGlobalManifestSerializer

    if not data:
      # Fallback to DB and update Redis if Redis was cleared
      logger.info('Fallback to DB and update Redis if Redis was cleared')
      instance = cls.get_solo()
      data = VendorGlobalManifestSerializer(instance).data
      cache.set('vendor_global_manifest_data', data, timeout=None)
    logger.info(f'Final data:{data}')
    return data

  def __str__(self):
    return "Global Manifest"

  class Meta:
    verbose_name = "Global Manifest"
    verbose_name_plural = "Global Manifest"

class NotificationText(SingletonModel):
  # --- Order Creation & Status ---
  order_submitted = models.TextField(
    default="Your order has been submitted to {vendor_name} for review.",
    help_text="Placeholders: {vendor_name}"
  )
  order_accepted = models.TextField(
    default="{vendor_name} accepted your order. Pickup is scheduled for {date} at {time}.",
    help_text="Placeholders: {vendor_name}, {date}, {time}"
  )
  order_declined = models.TextField(
    default="{vendor_name} declined your order. We are finding another LaundryMart for you."
  )
  order_reassigned = models.TextField(
    default="Your order has been reassigned to another LaundryMart."
  )
  order_canceled_general = models.TextField(default="Your order has been canceled.")
  order_canceled_by_vendor = models.TextField(default="Your order has been canceled by {vendor_name}.")
  order_canceled_by_customer = models.TextField(default="You have successfully canceled your order.")

  # --- Pickup Phase ---
  driver_assigned_pickup = models.TextField(default="A driver has been assigned to pick up your laundry.")
  driver_en_route_pickup = models.TextField(default="A driver is on the way to pick up your laundry.")
  driver_arrived_pickup = models.TextField(default="Your driver has arrived for pickup.")
  pickup_success = models.TextField(default="Your laundry has been picked up successfully.")
  pickup_access_issue = models.TextField(
    default="The driver could not access your pickup location. Please contact support.")
  pickup_delayed = models.TextField(default="Your pickup has been delayed. We apologize for the inconvenience.")

  # --- Processing Phase ---
  laundry_received = models.TextField(default="Your laundry has been received by {vendor_name}.")
  processing_started = models.TextField(default="{vendor_name} has started processing your laundry.")
  processing_finished = models.TextField(default="{vendor_name} has finished your laundry.")
  ready_for_delivery_or_pickup = models.TextField(default="Your laundry is ready for delivery or pickup!")
  processing_delayed = models.TextField(default="Your order is running behind schedule. We will update you shortly.")

  # --- Delivery Phase ---
  customer_picked_up = models.TextField(default="Your order has been picked up.")
  driver_assigned_delivery = models.TextField(default="A driver is picking up your order for delivery.")
  driver_en_route_delivery = models.TextField(default="A driver is on the way to deliver your laundry.")
  driver_arrived_delivery = models.TextField(default="Your driver has arrived with your laundry.")
  delivery_success = models.TextField(default="Your laundry has been delivered. Thank you for using Laundrmart!")

  # --- Payment & Adjustments ---
  payment_authorized = models.TextField(default="Your payment has been authorized successfully.")
  payment_failed = models.TextField(default="Your payment could not be processed. Please update your payment method.")
  weight_adjustment = models.TextField(
    default="Your laundry weighs {weight} lbs.",
    help_text="Placeholders: {weight}"
  )

  # --- Post-Order Engagement ---
  rate_vendor = models.TextField(default="How was your service with {vendor_name}? Tap to rate.")
  rate_driver = models.TextField(default="Please rate your delivery experience.")
  leave_review = models.TextField(default="Leave a review and help others.")

  # --- Vendor App Notifications ---
  new_customer_message = models.TextField(
    default="{customer_name} sent you a message about Order #{order_id}.",
    help_text="Placeholders: {customer_name}, {order_id}"
  )
  unread_message_reminder = models.TextField(default="You have unread messages from {customer_name}.")
  customer_waiting_reminder = models.TextField(default="Customer is waiting for your response (Order #{order_id}).")
  general_reply_reminder = models.TextField(default="Reminder: Reply to customer message.")

  def __str__(self):
    return "Global Notification Settings"

  class Meta:
    verbose_name = "Notification Text Content"
  def save(self, *args, **kwargs):
    super().save(*args, **kwargs)
    # We "Set" instead of "Delete" to ensure Redis is always populated
    # 'manifest_data' is the key we will use in our API/Views
    logger.info("Notification texts updated, refreshing cache with new data.")
    cache.set('notification_text_data', self, timeout=None)

  @classmethod
  def get_cached_notification_text(cls):
    # Try to get from Redis
    data = cache.get('notification_text_data')
    logger.info(f'get_cached_notification_text called:{data}')
    if not data:
      # Fallback to DB and update Redis if Redis was cleared
      logger.info('Fallback to DB and update Redis if Redis was cleared')
      data = cls.get_solo()
      cache.set('notification_text_data', data, timeout=None)
    logger.info(f'Final data:{data}')
    return data

class SlideImage(models.Model):
  image = models.ImageField(upload_to='slide_images/')
  order_index=models.PositiveIntegerField(_("order_index"),default=0, help_text="Order of the slide in the carousel (0-based index)", db_index=True)

  def __str__(self):
    return f"Slide Image {self.id} (Order: {self.order_index})"

  @classmethod
  def refresh_cache(cls):
    data = []

    for slide in cls.objects.order_by('order_index'):
      image_url = None

      if slide.image:
        image_url = f"{BASE_URL}{slide.image.url}"

      data.append({
        "id": slide.id,
        "image": image_url,
        "order_index": slide.order_index,
      })

    try:
      cache.set('slide_image_data', data, timeout=None)
    except Exception:
      logger.exception('Failed to set slide_image_data cache')

    # Also rebuild global manifest caches so that customer manifest
    # always contains the up-to-date slides payload.
    try:
      # Import serializers lazily to avoid circular import at module load
      from customer.serializers import CustomerGlobalManifestSerializer
      from vendor.serializers import VendorGlobalManifestSerializer

      # Use the singleton instance and serialize fresh payloads
      gm_instance = GlobalManifest.get_solo()
      customer_global_manifest_data = CustomerGlobalManifestSerializer(gm_instance).data
      vendor_global_manifest_data = VendorGlobalManifestSerializer(gm_instance).data

      try:
        cache.set('customer_global_manifest_data', customer_global_manifest_data, timeout=None)
      except Exception:
        logger.exception('Failed to set customer_global_manifest_data cache')

      try:
        cache.set('vendor_global_manifest_data', vendor_global_manifest_data, timeout=None)
      except Exception:
        logger.exception('Failed to set vendor_global_manifest_data cache')

    except Exception:
      # Log and continue; cache failure or serializer import issues
      # should not prevent the slide cache from being updated.
      logger.exception('Failed to refresh global manifest caches after slide cache update')


  def save(self, *args, **kwargs):
    super().save(*args, **kwargs)

    logger.info("SlideImage updated, refreshing cache.")
    self.__class__.refresh_cache()

  def delete(self, *args, **kwargs):
    super().delete(*args, **kwargs)

    logger.info("SlideImage deleted, refreshing cache.")
    self.__class__.refresh_cache()

  @classmethod
  def get_cached_slide_images(cls):
    data = None
    try:
      data = cache.get('slide_image_data')
    except Exception:
      logger.exception('Cache GET failed for slide_image_data; falling back to DB')

    # Validate cached shape: expect a list of dicts with at least 'id' and 'image'
    invalid = False
    if not data or not isinstance(data, list):
      invalid = True
    else:
      for item in data:
        if not isinstance(item, dict) or 'id' not in item or 'image' not in item:
          invalid = True
          break

    if invalid:
      logger.info("Cached slide data missing or invalid. Rebuilding from DB.")
      cls.refresh_cache()
      try:
        data = cache.get('slide_image_data')
      except Exception:
        logger.exception('Cache GET failed for slide_image_data after refresh; falling back to DB')
        # Last resort: read directly from DB and build the payload
        data = []
        for slide in cls.objects.order_by('order_index'):
          image_url = f"{BASE_URL}{slide.image.url}" if slide.image else None
          data.append({
            'id': slide.id,
            'image': image_url,
            'order_index': slide.order_index,
          })

    logger.info(f'Cached slide: {data}')
    return data

  class Meta:
    verbose_name = "Slide Image"
    verbose_name_plural = "Slide Images"
    ordering = ['order_index']  # Ensure images are ordered by the specified index


class AdminDashboard(models.Model):
  pass
