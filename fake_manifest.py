import random
from decimal import Decimal as D
from django.utils import timezone

from faker import Faker
fake = Faker()

# Your fixed store ID
TARGET_EXTERNAL_STORE_ID = "46d6e35d-3ca4-4092-8526-24a4bcd814a0"

# Import your models (adjust paths if needed)
from accounts.models import User, LaundrymartStore
from payment.models import Order
from uber.models import DeliveryQuote, Delivery, BAG_CHOICES, ManifestItem


# Helper functions to get valid parents for this store only
def get_random_user():
    return User.objects.order_by('?').first()

def get_random_store():
    # Return the store that matches your external ID
    return LaundrymartStore.objects.filter(store_id=TARGET_EXTERNAL_STORE_ID).first()

def get_random_quote():
    return DeliveryQuote.objects.filter(
        external_store_id=TARGET_EXTERNAL_STORE_ID,
        status='pending'
    ).order_by('?').first()

def get_random_order(status_filter=None):
    qs = Order.objects.filter(
        service_provider__store_id=TARGET_EXTERNAL_STORE_ID
    )
    if status_filter:
        qs = qs.filter(status__in=status_filter)
    return qs.order_by('?').first()

def get_random_delivery():
    return Delivery.objects.filter(
        external_store_id=TARGET_EXTERNAL_STORE_ID
    ).order_by('?').first()


# Generate ManifestItem linked to a DeliveryQuote (for pending)
def create_manifest_for_quote():
    quote = get_random_quote()
    if not quote:
        print("No pending DeliveryQuote found for this store!")
        return

    ManifestItem.objects.create(
        delivery_quote=quote,
        name="Laundry Bag",
        quantity=random.randint(1, 3),
        size=random.choice([choice[0] for choice in BAG_CHOICES]),
        weight=D(str(round(random.uniform(2.0, 15.0), 2))),
        price=D(str(round(random.uniform(20.0, 80.0), 2))),
        vat_percentage=D('8.875'),
        dimensions={
            "length": random.randint(30, 60),
            "depth": random.randint(20, 40),
            "height": random.randint(20, 50)
        }
    )
    print(f"ManifestItem created for Quote {quote.quote_id}")


# Generate ManifestItem linked to an Order (for active/delivered)
def create_manifest_for_order():
    # 50% chance active, 50% completed
    status_list = random.choice([
        ['card_saved', 'picked_up', 'weighed', 'charged', 'return_scheduled'],
        ['completed']
    ])
    order = get_random_order(status_list)
    if not order:
        # If no order in that status, fall back to any order for this store
        order = get_random_order()
    if not order:
        print("No Order found for this store!")
        return

    ManifestItem.objects.create(
        stripe_order=order,
        name="Laundry Bag",
        quantity=random.randint(1, 2),
        size=random.choice([choice[0] for choice in BAG_CHOICES]),
        weight=D(str(round(random.uniform(3.0, 12.0), 2))),
        price=D(str(round(random.uniform(15.0, 60.0), 2))),
        vat_percentage=D('8.875'),
        dimensions={
            "length": random.randint(30, 70),
            "depth": random.randint(20, 50),
            "height": random.randint(20, 60)
        }
    )
    print(f"ManifestItem created for Order {order.uuid} ({order.status})")


# Optional: Generate ManifestItem linked to a Delivery (if you use it)
def create_manifest_for_delivery():
    delivery = get_random_delivery()
    if not delivery:
        print("No Delivery found for this store!")
        return

    ManifestItem.objects.create(
        delivery=delivery,
        name="Clean Laundry Bag",
        quantity=1,
        size=random.choice([choice[0] for choice in BAG_CHOICES]),
        weight=D(str(round(random.uniform(4.0, 10.0), 2))),
        price=D('0.00'),  # return delivery usually no charge
        vat_percentage=D('0'),
        dimensions={
            "length": random.randint(40, 70),
            "depth": random.randint(30, 50),
            "height": random.randint(30, 60)
        }
    )
    print(f"ManifestItem created for Delivery {delivery.delivery_uid}")


# === GENERATE DATA ===

store = get_random_store()
if not store:
    print(f"ERROR: No LaundrymartStore found with store_id={TARGET_EXTERNAL_STORE_ID}")
    print("Make sure you have a store with that exact store_id in the database.")
else:
    print(f"Generating fake ManifestItems for store: {store.laundrymart_name or store.store_id}")

    print("\n--- Creating 25 ManifestItems for Pending Quotes ---")
    for _ in range(25):
        create_manifest_for_quote()

    print("\n--- Creating 40 ManifestItems for Active/Delivered Orders ---")
    for _ in range(40):
        create_manifest_for_order()

    print("\n--- Creating 15 ManifestItems for Deliveries (optional) ---")
    for _ in range(15):
        create_manifest_for_delivery()

    print("\nAll done! All ManifestItems are linked only to your store's quotes/orders/deliveries.")