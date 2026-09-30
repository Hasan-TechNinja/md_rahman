import random
from datetime import datetime
from uuid import uuid4  # For generating unique UUIDs
from faker import Faker
from rest_framework.generics import get_object_or_404

from accounts.models import LaundrymartStore, User
from uber.models import Delivery, DeliveryQuote  # Adjust to your app's import path
from payment.models import Order  # Adjust to your app's import path

fake = Faker()
from decimal import Decimal, ROUND_HALF_UP
def d(value):
  return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

LAT_RANGE = (23.70, 23.90)
LNG_RANGE = (90.35, 90.50)

def random_lat_lng():
  return (
    round(random.uniform(*LAT_RANGE), 6),
    round(random.uniform(*LNG_RANGE), 6),
  )

def create_fake_order():
    # Fetch a random delivery associated with the service provider and not already attached to an order
    service_provider_store_id = '46d6e35d-3ca4-4092-8526-24a4bcd814a0'  # LaundrymartStore associated with the delivery

    # Fetch a delivery linked to the given store ID and that is not already attached to an order
    delivery = Delivery.objects.filter(
        quote__external_store_id=service_provider_store_id  # Corrected: Now querying through DeliveryQuote
    ).exclude(
        quote_uid__isnull=False,
        delivery_uid__isnull=False
    ).order_by('?').first()

    if not delivery:
        print(f"No available deliveries for service provider {service_provider_store_id}. Skipping order creation.")
        return None

    # Extract user (customer) and service provider (LaundrymartStore) from the delivery
    customer = delivery.customer  # User associated with the delivery
    service_provider = get_object_or_404(LaundrymartStore, store_id=service_provider_store_id)

    # Generate random values for the order (address, lat/lng, etc.)
    pickup_lat, pickup_lng = random_lat_lng()
    dropoff_lat, dropoff_lng = random_lat_lng()

    # Create a unique order UUID
    order_uuid = str(uuid4())

    # Randomize the order status
    status = random.choice(
        ['pending_setup', 'processing', 'card_saved', 'picked_up', 'weighed', 'charged', 'return_scheduled',
         'completed', 'canceled'])

    # Create random pricing and weights
    weight_in_pounds = d(random.uniform(1.0, 20.0))  # Random weight
    estimated_value = d(random.uniform(1.0, 20.0))  # Random weight
    service_charge_cents = random.randint(1000, 5000)  # Random service fee in cents
    delivery_fee_cents = random.randint(500, 2000)  # Random delivery fee in cents
    final_total_cents = service_charge_cents + delivery_fee_cents

    # Get the quote and delivery details from the existing delivery
    uber_pickup_quote_id = delivery.quote_uid
    uber_pickup_delivery_id = delivery.delivery_uid

    # Create the order and associate it with the delivery and quote
    order = Order.objects.create(
        uuid=order_uuid,
        user=customer,  # Use the user from the delivery
        service_provider=service_provider,  # Use the service provider (LaundrymartStore) from the delivery
        pickup_address=fake.address(),
        dropoff_address=fake.address(),
        pickup_latitude=pickup_lat,
        pickup_longitude=pickup_lng,
        dropoff_latitude=dropoff_lat,
        dropoff_longitude=dropoff_lng,
        uber_pickup_quote_id=uber_pickup_quote_id,
        uber_pickup_delivery_id=uber_pickup_delivery_id,
        weight_in_pounds=weight_in_pounds,
        service_charge_cents=service_charge_cents,
        delivery_fee_cents=delivery_fee_cents,
        final_total_cents=final_total_cents,
        status=status,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        estimated_value=estimated_value
    )

    return order

# Generate 50 fake orders and attach random deliveries
for _ in range(50):
  create_fake_order()
