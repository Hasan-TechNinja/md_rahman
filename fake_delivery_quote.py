import random
from faker import Faker
from datetime import datetime, timedelta
from accounts.models import LaundrymartStore, User
from fake_data import d, random_lat_lng
from uber.models import DeliveryQuote, SERVICE_TYPE_CHOICE, STATUS_CHOICES

fake = Faker()

def generate_fake_delivery_quote():
    # Random customer
    customer = User.objects.filter(is_staff=False).order_by('?').first()  # Get a random customer from the DB

    # Random pickup/dropoff lat/lng
    pickup_lat, pickup_lng = random_lat_lng()
    dropoff_lat, dropoff_lng = random_lat_lng()

    # Generate a random quote_id
    quote_id = fake.unique.uuid4()

    # Generate random times
    scheduled_pickup_time = fake.date_time_this_month()
    dropoff_eta = scheduled_pickup_time + timedelta(hours=random.randint(1, 5))
    expires = scheduled_pickup_time + timedelta(hours=24)

    # Generate random fee and currency
    fee = d(random.uniform(10.0, 100.0))
    currency = "USD"

    # Get a random LaundrymartStore and its external_store_id
    laundrymart_store = LaundrymartStore.objects.order_by('?').first()  # Get a random laundry mart store

    if not laundrymart_store:
        print("No LaundrymartStore found.")
        return None  # Ensure you handle this case if no store is available

    # Extract store details
    external_store_id = laundrymart_store.store_id  # Use the store's external_store_id

    # Create a random delivery quote and attach the LaundrymartStore details
    delivery_quote = DeliveryQuote.objects.create(
        quote_id=quote_id,
        customer=customer,
        scheduled_pickup_time=scheduled_pickup_time,
        service_type=random.choice([x[0] for x in SERVICE_TYPE_CHOICE]),
        status=random.choice([x[0] for x in STATUS_CHOICES]),
        pickup_address=fake.address(),
        dropoff_address=fake.address(),
        pickup_latitude=pickup_lat,
        pickup_longitude=pickup_lng,
        dropoff_latitude=dropoff_lat,
        dropoff_longitude=dropoff_lng,
        fee=fee,
        currency=currency,
        dropoff_eta=dropoff_eta,
        expires=expires,
        external_store_id='46d6e35d-3ca4-4092-8526-24a4bcd814a0',  # Store external_id here
    )
    return delivery_quote

# Generate 50 fake delivery quotes
for _ in range(50):
    generate_fake_delivery_quote()
