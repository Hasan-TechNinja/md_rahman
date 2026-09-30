import random
from faker import Faker
from django.utils import timezone
from datetime import time
from accounts.models import User  # adjust app name if needed

fake = Faker()

PASSWORD = "arnob0188"

# Dhaka-ish coordinate bounds (real, usable)
LAT_RANGE = (23.70, 23.90)
LNG_RANGE = (90.35, 90.50)

def random_lat_lng():
  return (
    round(random.uniform(*LAT_RANGE), 6),
    round(random.uniform(*LNG_RANGE), 6),
  )

def create_customer():
  lat, lng = random_lat_lng()

  user = User.objects.create_user(
    email=fake.unique.email(),
    password=PASSWORD,
    full_name=fake.name(),
    is_active=True,
    is_verified=True,
    is_staff=False,
    location=fake.address(),
    lat=str(lat),
    lng=str(lng),
  )
  return user
from decimal import Decimal, ROUND_HALF_UP
def d(value):
  return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def create_vendor():
  lat, lng = random_lat_lng()

  user = User.objects.create_user(
    email=fake.unique.email(),
    password=PASSWORD,
    full_name=fake.company(),
    is_active=True,
    is_verified=True,
    is_staff=True
  )
  return user

def run():
  customers = 0
  vendors = 0

  for _ in range(50):
    create_customer()
    customers += 1

  for _ in range(50):
    create_vendor()
    vendors += 1

  print(f"Created {customers} customers and {vendors} vendors.")

run()
