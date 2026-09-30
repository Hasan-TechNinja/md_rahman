import random
from datetime import datetime

from django.db import transaction

from accounts.models import User
from fake_data import d, fake, random_lat_lng
from uber.models import Delivery, DeliveryQuote  # Adjust to your app's import path


def generate_fake_delivery():
    # Randomly select an existing delivery quote for a specific external store ID
    quote = DeliveryQuote.objects.filter(external_store_id='46d6e35d-3ca4-4092-8526-24a4bcd814a0').order_by('?').first()

    # If no quote is found, handle this case gracefully
    if not quote:
        print("No delivery quote found. Skipping delivery creation.")
        return None

    if Delivery.objects.filter(quote_uid=quote.quote_id).exists():
        print(f"Delivery with quote ID {quote.quote_id} already exists. Skipping delivery creation.")
        return None

    # Generate random latitudes and longitudes for pickup and dropoff locations
    pickup_lat, pickup_lng = random_lat_lng()
    dropoff_lat, dropoff_lng = random_lat_lng()

    # Generate random delivery UID
    delivery_uid = fake.uuid4()

    # Randomly select a customer (non-staff)
    customer = User.objects.filter(is_staff=False).order_by('?').first()

    # Randomize the status
    status = random.choice(['pending', 'pickup_true', 'pickup_false', 'pickup_complete', 'dropoff_true', 'dropoff_false', 'delivered', 'canceled', 'returned'])

    # Generate a tracking URL
    tracking_url = f"https://tracking.uber.com/{delivery_uid}"

    # Random fee and currency
    fee = d(random.uniform(5.0, 50.0))
    total_fee = fee + d(random.uniform(2.0, 10.0))
    currency = "USD"

    # Create the Delivery object and associate it with the quote
    delivery = Delivery.objects.create(
        delivery_uid=delivery_uid,
        quote=quote,  # Link to the selected delivery quote
        customer=customer,
        status=status,
        fee=fee,
        total_fee=total_fee,
        currency=currency,
        external_store_id=quote.external_store_id,
        tracking_url=tracking_url,
        pickup_latitude=pickup_lat,
        pickup_longitude=pickup_lng,
        dropoff_latitude=dropoff_lat,
        dropoff_longitude=dropoff_lng,
        created_at_uber=datetime.now(),
        updated_at_uber=datetime.now(),
    )
    return delivery


# Generate 50 fake deliveries in a transaction to ensure consistency

for _ in range(50):
    generate_fake_delivery()

print("50 fake deliveries created successfully.")
