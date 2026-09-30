from customer.tasks import auto_assign_another_laundrymart
from customer.utils import get_nearby_open_vendor
from laundrymart.settings import UBER_CUSTOMER_ID
from uber.models import DeliveryQuote
from accounts.models import User
quote = DeliveryQuote.objects.get(quote_id='dqt_KdG4R7IoRxW1Wph-EwkPmw')
customer =User.objects.get(email='redoy@gmail.com')
auto_assign_another_laundrymart(quote, UBER_CUSTOMER_ID)
