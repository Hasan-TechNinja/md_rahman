from messaging.models import CustomerNotification


def customer_create_notification(recipient,category, message, target_url=None, additional_info=None):
  CustomerNotification.objects.create(
      recipient=recipient,
      category=category,
      text=message,
      target_url=target_url,
      additional_info=additional_info
  )

def customer_receive_accept_notification(delivery_quote, user):
  print(f'notification sent to {user.full_name}')

def customer_receive_delivery_picked_up_notification(order, user):
  print(f'notification sent to {user.full_name}')

def customer_receive_payment_failed_notification(order, user):
  print(f'notification sent to {user.full_name}')
def customer_receive_payment_success_notification(order, user):
  print(f'notification sent to {user.full_name}')

def customer_receive_order_weighed_notification(order, user):
  print(f'notification sent to {user.full_name}')

def customer_receive_reject_notification(delivery_quote, user):
  print(f'notification sent to {user.full_name}')

def send_completion_notification_to_customer(order, user):

  print(f'notification sent to {user.full_name}')

def send_order_return_scheduled_for_full_service_notification_to_customer(order, user):

  print(f'notification sent to {user.full_name}')
