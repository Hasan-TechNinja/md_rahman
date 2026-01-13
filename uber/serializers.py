from datetime import datetime, timedelta

from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from accounts.models import LaundrymartStore
from uber.models import DELIVERABLE_ACTION_CHOICES, Delivery, DeliveryQuote, ManifestItem, SERVICE_TYPE_CHOICE

class DimensionsSerializer(serializers.Serializer):
  length = serializers.IntegerField()
  height = serializers.IntegerField()
  depth = serializers.IntegerField()

  def validate(self, attrs):
    for key, value in attrs.items():
      if value <= 0:
        raise serializers.ValidationError(
          f"{key} must be a positive integer"
        )
    return attrs

class ManifestItemSerializer(serializers.Serializer):
  name = serializers.CharField()
  quantity = serializers.IntegerField()
  size = serializers.CharField(required=False)
  dimensions = DimensionsSerializer()
  #dimensions = serializers.JSONField()
  price = serializers.IntegerField()
  weight = serializers.IntegerField()
  vat_percentage = serializers.IntegerField(required=False, default=0)

class UberCreateQuoteSerializer(serializers.Serializer):
  service_type=serializers.ChoiceField(required=True,choices=SERVICE_TYPE_CHOICE)
  pickup_address = serializers.CharField()
  dropoff_address = serializers.CharField()

  pickup_latitude = serializers.FloatField(required=False)
  pickup_longitude = serializers.FloatField(required=False)
  dropoff_latitude = serializers.FloatField(required=False)
  dropoff_longitude = serializers.FloatField(required=False)

  customer_note = serializers.CharField(required=False)

  pickup_phone_number = serializers.RegexField(r'^\+[0-9]+$')
  dropoff_phone_number = serializers.RegexField(r'^\+[0-9]+$')
  pickup_ready_dt= serializers.DateTimeField(required=False)

  manifest_total_value = serializers.IntegerField(min_value=0)

  external_store_id = serializers.CharField()

  # def validate_external_store_id(self, value):
  #   try:
  #     store = LaundrymartStore.objects.get(store_id=value)
  #   except LaundrymartStore.DoesNotExist:
  #     raise ValidationError("The store with the provided external_store_id does not exist.")
  #
  #   # Check if the store will be closed in the next 15 minutes
  #   if not store.is_open_now:
  #     raise ValidationError("The store is not open now.")
  #   closing_time = store.closes_at
  #   if closing_time is None:
  #     raise ValidationError(f"The store is closed today.")
  #
  #   # Compare closing time with current time + 15 minutes
  #   now = datetime.now()
  #   if closing_time <= now + timedelta(minutes=15):
  #     raise ValidationError(f"The store will be closed in the next 15 minutes.")
  #
  #   return value

  def to_uber_payload(self, destination=None):

    data = self.validated_data
    import json  # Can be at top, but safe here too

    # Build structured address dict from free-text string
    def build_address_struct(address_str):
      return {
        "street_address": [address_str.strip()],
        "city": "",
        "state": "",
        "zip_code": "",
        "country": "US",  # Adjust if needed
      }

    pickup_address = data["pickup_address"]
    dropoff_address = data["dropoff_address"]

    # Swap pickup/dropoff based on destination
    if destination == "vendor":
      # Leg 1: customer -> vendor
      pickup_address, dropoff_address = pickup_address, dropoff_address
    elif destination == "customer":
      # Leg 2: vendor -> customer
      pickup_address, dropoff_address = dropoff_address, pickup_address

    pickup_struct = build_address_struct(pickup_address)
    dropoff_struct = build_address_struct(dropoff_address)

    payload = {
      "pickup_address": json.dumps(pickup_struct),
      "dropoff_address": json.dumps(dropoff_struct),
      "pickup_phone_number": data["pickup_phone_number"],
      "dropoff_phone_number": data["dropoff_phone_number"],
      "manifest_total_value": data["manifest_total_value"],
    }

    # Add optional lat/long if provided
    if data.get("pickup_latitude") is not None and data.get("pickup_longitude") is not None:
      payload["pickup_latitude"] = data["pickup_latitude"]
      payload["pickup_longitude"] = data["pickup_longitude"]

    if data.get("dropoff_latitude") is not None and data.get("dropoff_longitude") is not None:
      payload["dropoff_latitude"] = data["dropoff_latitude"]
      payload["dropoff_longitude"] = data["dropoff_longitude"]

    if data.get("external_store_id"):
      payload["external_store_id"] = data["external_store_id"]

    # Optional datetime fields (Uber expects ISO 8601 strings if provided)
    # Example: if data.get("pickup_ready_dt"):
    #   payload["pickup_ready_time"] = data["pickup_ready_dt"].isoformat() + "Z"

    return payload

class DeliveryQuoteCreateSerializer(serializers.ModelSerializer):
  manifest_items = ManifestItemSerializer(many=True, read_only=False)
  class Meta:
    model = DeliveryQuote
    fields = ["service_type","status","quote_id","customer","manifest_items","pickup_address","dropoff_address","pickup_latitude",
              "pickup_longitude","dropoff_latitude","dropoff_longitude","pickup_phone_number",
              "dropoff_phone_number", "manifest_total_value","external_store_id","fee",
              "currency","currency_type","pickup_ready_dt","dropoff_eta","duration","pickup_duration","dropoff_deadline",
              "expires"]
    read_only_fields = ["customer","status","currency", "currency_type", "expires","duration", "pickup_duration", "dropoff_deadline"]

  def create(self, validated_data):
    manifest_items_data = validated_data.pop('manifest_items', [])

    # Create the parent DeliveryQuote instance
    delivery_quote = DeliveryQuote.objects.create(**validated_data)

    # Create each ManifestItem and associate it with the parent DeliveryQuote instance
    for item_data in manifest_items_data:
      # You may need to associate the created ManifestItem with DeliveryQuote
      item_data['delivery_quote'] = delivery_quote  # Assuming you have a foreign key relation
      ManifestItem.objects.create(**item_data)

    return delivery_quote
class UberCreateDeliveryPayloadSerializer(serializers.Serializer):
  quote_id = serializers.CharField()

  pickup_name = serializers.CharField()
  pickup_phone_number = serializers.RegexField(r'^\+[0-9]+$')
  pickup_notes = serializers.CharField(required=False, allow_blank=True)

  dropoff_name = serializers.CharField()
  dropoff_phone_number = serializers.RegexField(r'^\+[0-9]+$')
  dropoff_notes = serializers.CharField(required=False, allow_blank=True)

  deliverable_action = serializers.ChoiceField(choices=DELIVERABLE_ACTION_CHOICES,required=False)

  pickup_ready_dt = serializers.DateTimeField(required=False)
  pickup_deadline_dt = serializers.DateTimeField(required=False)
  dropoff_ready_dt = serializers.DateTimeField(required=False)
  dropoff_deadline_dt = serializers.DateTimeField(required=False)

  tip = serializers.IntegerField(min_value=0, required=False)
  idempotency_key = serializers.CharField()

class CreateDeliverySerializer(serializers.Serializer):
  pickup_name = serializers.CharField()
  pickup_address = serializers.CharField()
  pickup_phone_number = serializers.CharField()
  dropoff_name = serializers.CharField()
  dropoff_address = serializers.CharField()
  dropoff_phone_number = serializers.CharField()
  manifest_items = ManifestItemSerializer(many=True)
  pickup_business_name = serializers.CharField(required=False, allow_blank=True)
  pickup_latitude = serializers.FloatField(required=False)
  pickup_longitude = serializers.FloatField(required=False)
  pickup_notes = serializers.CharField(required=False, allow_blank=True)
  dropoff_business_name = serializers.CharField(required=False, allow_blank=True)
  dropoff_latitude = serializers.FloatField(required=False)
  dropoff_longitude = serializers.FloatField(required=False)
  dropoff_notes = serializers.CharField(required=False, allow_blank=True)
  dropoff_seller_notes = serializers.CharField(required=False, allow_blank=True)
  deliverable_action = serializers.CharField(required=False)
  manifest_reference = serializers.CharField(required=False)
  manifest_total_value = serializers.IntegerField()
  quote_id = serializers.CharField()
  tip = serializers.IntegerField(required=False)
  idempotency_key = serializers.CharField(required=False)
  external_store_id = serializers.CharField(required=False, allow_blank=True)
  external_id = serializers.CharField(required=False, allow_blank=True)
  pickup_ready_dt = serializers.DateTimeField(required=False)
  pickup_deadline_dt = serializers.DateTimeField(required=False)
  dropoff_ready_dt = serializers.DateTimeField(required=False)
  dropoff_deadline_dt = serializers.DateTimeField(required=False)

