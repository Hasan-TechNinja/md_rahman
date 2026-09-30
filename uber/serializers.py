import json
from datetime import datetime, timedelta

from phonenumber_field.serializerfields import PhoneNumberField
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from accounts.models import LaundrymartStore
from uber.models import BAG_CHOICES, DELIVERABLE_ACTION_CHOICES, Delivery, DeliveryQuote, ManifestItem, \
  SERVICE_TYPE_CHOICE

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
  size = serializers.ChoiceField(required=False, choices=BAG_CHOICES)
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

  customer_note = serializers.CharField(required=False, allow_blank=True)
  pickup_notes = serializers.CharField(required=False, allow_blank=True)
  dropoff_notes = serializers.CharField(required=False, allow_blank=True)

  pickup_phone_number = PhoneNumberField(required=False)
  dropoff_phone_number = PhoneNumberField(required=False)
  pickup_ready_dt= serializers.DateTimeField(required=False)

  insurance_amount=serializers.IntegerField(min_value=0, required=False)
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

    pickup_address_str = data["pickup_address"]  # already correct: "{\"street_address\":[...]}"
    dropoff_address_str = data["dropoff_address"]
    
    pickup_phone = str(data["pickup_phone_number"])
    dropoff_phone = str(data["dropoff_phone_number"])
    
    pickup_lat = float(data["pickup_latitude"]) if "pickup_latitude" in data else None
    pickup_lng = float(data["pickup_longitude"]) if "pickup_longitude" in data else None
    dropoff_lat = float(data["dropoff_latitude"]) if "dropoff_latitude" in data else None
    dropoff_lng = float(data["dropoff_longitude"]) if "dropoff_longitude" in data else None

    # Optional: swap for full_service legs
    if destination == "vendor":
      # customer → vendor: keep as is
      pass
    elif destination == "customer":
      # vendor → customer: swap everything!
      pickup_address_str, dropoff_address_str = dropoff_address_str, pickup_address_str
      pickup_phone, dropoff_phone = dropoff_phone, pickup_phone
      pickup_lat, dropoff_lat = dropoff_lat, pickup_lat
      pickup_lng, dropoff_lng = dropoff_lng, pickup_lng

    payload = {
      "pickup_address": pickup_address_str,
      "dropoff_address": dropoff_address_str,
      "pickup_phone_number": pickup_phone,
      "dropoff_phone_number": dropoff_phone,
      "manifest_total_value": int(data["manifest_total_value"]),
    }

    # Coordinates (optional but strongly recommended by Uber)
    if pickup_lat is not None and pickup_lng is not None:
      payload["pickup_latitude"] = pickup_lat
      payload["pickup_longitude"] = pickup_lng

    if dropoff_lat is not None and dropoff_lng is not None:
      payload["dropoff_latitude"] = dropoff_lat
      payload["dropoff_longitude"] = dropoff_lng

    # if "external_store_id" in data and data["external_store_id"]:
    #   payload["external_store_id"] = data["external_store_id"]

    if "customer_note" in data and data["customer_note"]:
      payload["customer_note"] = data["customer_note"]

    if "pickup_ready_dt" in data and data["pickup_ready_dt"]:
      payload["pickup_ready_dt"] = data["pickup_ready_dt"].isoformat()

    # Optional: insurance if you want to support it
    if "insurance_amount" in data and data["insurance_amount"]:
      payload["insurance_amount"] = int(data["insurance_amount"])

    return payload

class DeliveryQuoteCreateSerializer(serializers.ModelSerializer):
  manifest_items = ManifestItemSerializer(many=True, read_only=False)
  class Meta:
    model = DeliveryQuote
    fields = ["service_type","status","quote_id","customer","customer_note","manifest_items","pickup_address","dropoff_address","pickup_latitude",
              "pickup_longitude","dropoff_latitude","dropoff_longitude","pickup_phone_number",
              "dropoff_phone_number", "manifest_total_value","external_store_id","fee","insurance_amount",
              "currency","currency_type","pickup_ready_dt","dropoff_eta","duration","pickup_duration","dropoff_deadline",
              "expires"]
    read_only_fields = ["customer","status","currency", "currency_type","duration", "pickup_duration", "dropoff_deadline"]

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
  pickup_business_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
  pickup_latitude = serializers.FloatField(required=False, allow_null=True)
  pickup_longitude = serializers.FloatField(required=False, allow_null=True)
  pickup_notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)
  dropoff_business_name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
  dropoff_latitude = serializers.FloatField(required=False, allow_null=True)
  dropoff_longitude = serializers.FloatField(required=False, allow_null=True)
  dropoff_notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)
  dropoff_seller_notes = serializers.CharField(required=False, allow_blank=True, allow_null=True)
  deliverable_action = serializers.CharField(required=False, allow_null=True)
  manifest_reference = serializers.CharField(required=False, allow_null=True)
  manifest_total_value = serializers.IntegerField()
  quote_id = serializers.CharField()
  tip = serializers.IntegerField(required=False, allow_null=True)
  idempotency_key = serializers.CharField(required=False, allow_null=True)
  external_store_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
  external_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
  pickup_ready_dt = serializers.DateTimeField(required=False, allow_null=True)
  pickup_deadline_dt = serializers.DateTimeField(required=False, allow_null=True)
  dropoff_ready_dt = serializers.DateTimeField(required=False, allow_null=True)
  dropoff_deadline_dt = serializers.DateTimeField(required=False, allow_null=True)

