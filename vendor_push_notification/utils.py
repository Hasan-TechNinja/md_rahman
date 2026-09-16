from messaging.models import VendorNotification
import logging
logger = logging.getLogger(__name__)

def vendor_create_notification(recipient,category, message, target_url=None, additional_info=None):
  VendorNotification.objects.create(
      recipient=recipient,
      category=category,
      text=message,
      target_url=target_url,
      additional_info=additional_info
  )

def vendor_accept_or_reject_notification(delivery_quote, laundrymart):
  logger.info(f'notification sent to {laundrymart.laundrymart_name}')

def send_order_return_scheduled_for_full_service_notification_to_vendor(order, user):
  name = getattr(user, 'laundrymart_name', getattr(user, 'full_name', str(user)))
  logger.info(f'notification sent to {name}')