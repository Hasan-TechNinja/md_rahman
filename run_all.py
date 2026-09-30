from fake_delivery import generate_fake_delivery
from fake_delivery_quote import generate_fake_delivery_quote
from fake_manifest import generate_fake_manifest_item


def run_all():

  # Generate fake delivery quotes
  delivery_quotes = 0
  for _ in range(50):
    generate_fake_delivery_quote()
    delivery_quotes += 1
  print(f"Created {delivery_quotes} delivery quotes.")

  # Generate fake deliveries
  deliveries = 0
  for _ in range(50):
    generate_fake_delivery()
    deliveries += 1
  print(f"Created {deliveries} deliveries.")

  # Generate fake manifest items
  manifest_items = 0
  for _ in range(50):
    generate_fake_manifest_item()
    manifest_items += 1
  print(f"Created {manifest_items} manifest items.")


run_all()
