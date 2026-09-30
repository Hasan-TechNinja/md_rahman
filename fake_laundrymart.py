import random
from faker import Faker
from django.utils import timezone
from datetime import time
from accounts.models import User  # Adjust app name if needed
from accounts.models import LaundrymartStore  # Adjust to your app's import path
from decimal import Decimal, ROUND_HALF_UP
from django.core.files.uploadedfile import SimpleUploadedFile
from io import BytesIO
from PIL import Image

fake = Faker()


# Dhaka-ish coordinate bounds (real, usable)
LAT_RANGE = (23.70, 23.90)
LNG_RANGE = (90.35, 90.50)


def random_lat_lng():
  return (
    round(random.uniform(*LAT_RANGE), 6),
    round(random.uniform(*LNG_RANGE), 6),
  )


def d(value):
  return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# Create a fake image for the laundrymart logo and image fields
def create_fake_image():
  image = Image.new('RGB', (100, 100),
                    color=(fake.random_int(0, 255), fake.random_int(0, 255), fake.random_int(0, 255)))
  byte_io = BytesIO()
  image.save(byte_io, 'PNG')
  byte_io.seek(0)
  return SimpleUploadedFile(f"{fake.word()}.png", byte_io.read(), content_type="image/png")


# Create a fake LaundrymartStore instance with an existing admin
def create_laundrymart_store(admin_user):
  lat, lng = random_lat_lng()

  # Create a new store and assign the provided admin (staff)
  store = LaundrymartStore.objects.create(
    admin=admin_user,
    laundrymart_name=fake.company(),
    store_id=fake.uuid4(),
    laundrymart_logo=create_fake_image(),  # Add fake image for logo
    image=create_fake_image(),  # Add fake image for store image
    price_per_pound=d(random.uniform(1.5, 4.5)),
    service_fee=d(random.uniform(1, 3)),
    vendor_description=fake.text(),
    location=fake.address(),
    lat=lat,
    lng=lng,
    minimum_order_weight=d(random.uniform(3, 10)),
    daily_capacity_limit=d(random.uniform(50, 150)),

    # Turnaround times (hours)
    turnaround_time_minimum_sunday=12,
    turnaround_time_maximum_sunday=24,
    turnaround_time_minimum_monday=12,
    turnaround_time_maximum_monday=24,
    turnaround_time_minimum_tuesday=12,
    turnaround_time_maximum_tuesday=24,
    turnaround_time_minimum_wednesday=12,
    turnaround_time_maximum_wednesday=24,
    turnaround_time_minimum_thursday=12,
    turnaround_time_maximum_thursday=24,
    turnaround_time_minimum_friday=12,
    turnaround_time_maximum_friday=24,
    turnaround_time_minimum_saturday=12,
    turnaround_time_maximum_saturday=24,

    # Operating hours
    operating_hours_start_sunday=time(10, 0),
    operating_hours_end_sunday=time(18, 0),
    is_closed_sunday=False,
    operating_hours_start_monday=time(9, 0),
    operating_hours_end_monday=time(21, 0),
    is_closed_monday=False,
    operating_hours_start_tuesday=time(9, 0),
    operating_hours_end_tuesday=time(21, 0),
    is_closed_tuesday=False,
    operating_hours_start_wednesday=time(9, 0),
    operating_hours_end_wednesday=time(21, 0),
    is_closed_wednesday=False,
    operating_hours_start_thursday=time(9, 0),
    operating_hours_end_thursday=time(21, 0),
    is_closed_thursday=False,
    operating_hours_start_friday=time(9, 0),
    operating_hours_end_friday=time(21, 0),
    is_closed_friday=False,
    operating_hours_start_saturday=time(10, 0),
    operating_hours_end_saturday=time(20, 0),
    is_closed_saturday=False,
  )

  return store


# Assign existing staff users to stores as admins
def assign_existing_staff_to_stores():
  # Get all existing staff users (users who are is_staff=True)
  staff_users = User.objects.filter(is_staff=True, is_superuser=False)

  stores = []

  # Create stores and assign random staff users as admins
  for _ in range(50):
    # Pick a random staff user as admin for the stored
    admin_user = random.choice(staff_users)
    store = create_laundrymart_store(admin_user)
    stores.append(store)




assign_existing_staff_to_stores()
