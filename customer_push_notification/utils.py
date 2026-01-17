from accounts.models import LaundrymartStore
from messaging.models import CustomerNotification


def customer_create_notification(recipient,category, message, target_url=None, additional_info=None):
  CustomerNotification.objects.create(
      recipient=recipient,
      category=category,
      text=message,
      target_url=target_url,
      additional_info=additional_info
  )

def customer_receive_accept_notification(delivery_quote, user, order=None):
  service_provider_name=LaundrymartStore.objects.get(store_id=delivery_quote.external_store_id).laundrymart_name
  customer_create_notification(user, 'Important', f'{service_provider_name} has accepted your order.', order.id if order else None)

def customer_receive_delivery_picked_up_notification(order, user):
  print(f'notification sent to {user.full_name}')
  customer_create_notification(user, 'Important', f'Delivery for order {order.uuid} has been received by the Laundrymart.', order.id if order else None)

def customer_receive_payment_failed_notification(order, user):
  print(f'notification sent to {user.full_name}')
def customer_receive_payment_success_notification(order, user):
  print(f'notification sent to {user.full_name}')

def customer_receive_order_weighed_notification(order, user):
  print(f'notification sent to {user.full_name}')

def customer_receive_reject_notification(delivery_quote, user):
  print(f'notification sent to {user.full_name}')
  service_provider_name = LaundrymartStore.objects.get(store_id=delivery_quote.external_store_id).laundrymart_name
  customer_create_notification(user,'Important', f'Delivery has been rejected by {service_provider_name}. Please choose another laundrymart.' if user.preference=='Ask me to choose (I’ll decide each time)' else f'Delivery has been rejected by {service_provider_name}. Auto assigning another Laundrymart has been initiated')

def customer_recveive_payment_validation_failure_notification(user):
  customer_create_notification(
    user,
    "Important",
    "We couldn't assign a new laundry mart due to a payment issue. Please check your card.",
  )

def customer_receive_no_laundrymart_available_notification(user):
  print(f'notification sent to {user.full_name}')
  customer_create_notification(user, 'Important', 'No open Laundrymart available for you right now. We are stopping the auto assigning')

def send_completion_notification_to_customer(order, user):

  print(f'notification sent to {user.full_name}')

def send_order_return_scheduled_for_full_service_notification_to_customer(order, user):

  print(f'notification sent to {user.full_name}')
