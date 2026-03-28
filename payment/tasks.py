from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from accounts.models import LaundrymartStore
from customer_push_notification.utils import customer_receive_reject_notification
from payment.models import Order
from uber.models import DeliveryQuote, ManifestItem
from uber.serializers import CreateDeliverySerializer, ManifestItemSerializer
from uber.utils import create_and_save_delivery
from celery.utils.log import get_task_logger
logger = get_task_logger(__name__)

def initiate_auto_assign_order_and_delivery(quote, customer):
    logger.info('Auto initiation of order')


@shared_task
def process_acceptance_by_vendor(quote_id):
    logger.info('process acceptance bg task triggered.')
    try:
        # Get the DeliveryQuote instance
        quote = DeliveryQuote.objects.get(pk=quote_id)

        # Ensure the quote is in 'pending' status before processing
        if quote.status != 'pending':
            return {"message": "Quote status is not pending, skipping process"}

        # Wait for 15 minutes (this is handled automatically by Celery's delay mechanism)

        # Retrieve the related LaundrymartStore
        try:
            store = LaundrymartStore.objects.get(store_id=quote.external_store_id)
        except LaundrymartStore.DoesNotExist:
            return {"error": f"Store with ID {quote.external_store_id} not found"}

        # Check if the store's auto_accept_orders flag is True
        if store.auto_accept_orders:
            # Proceed to create the order and the delivery
            with transaction.atomic():
                # Prepare the data to create the order
                order = Order.objects.create(
                    user=quote.customer,
                    service_provider=store,
                    pickup_address=quote.pickup_address,
                    dropoff_address=quote.dropoff_address,
                    pickup_latitude=quote.pickup_latitude,
                    pickup_longitude=quote.pickup_longitude,
                    dropoff_latitude=quote.dropoff_latitude,
                    dropoff_longitude=quote.dropoff_longitude,
                    insurance_amount=quote.insurance_amount,
                    status='card_saved',  # Default status
                    uber_pickup_quote_id=quote.quote_id,
                    stripe_customer_id=quote.customer.stripe_customer_id,
                    stripe_default_pm_id=quote.payment_method_id,  # You may set this later
                    customer_note=quote.customer_note or "",
                    estimated_value=quote.manifest_total_value
                )

                # Create the pickup delivery using the create_and_save_delivery function
                quote_data = {
                    "quote_id": quote.quote_id,
                    "pickup_name": store.laundrymart_name,
                    "pickup_address": quote.pickup_address,
                    "pickup_phone_number": quote.pickup_phone_number,
                    "dropoff_name": quote.customer.full_name or "Customer",
                    "dropoff_address": quote.dropoff_address,
                    "dropoff_phone_number": quote.dropoff_phone_number,
                    "pickup_latitude": quote.pickup_latitude,
                    "pickup_longitude": quote.pickup_longitude,
                    "dropoff_latitude": quote.dropoff_latitude,
                    "dropoff_longitude": quote.dropoff_longitude,
                    "deliverable_action": "deliverable_action_meet_at_door",
                    "manifest_items": [],
                    "external_store_id": quote.external_store_id,
                    "manifest_total_value": int(quote.manifest_total_value or 0),
                }

                # Load manifest items
                manifest_items_qs = ManifestItem.objects.filter(delivery_quote=quote)
                quote_data["manifest_items"] = ManifestItemSerializer(
                    manifest_items_qs, many=True
                ).data

                # Validate with your existing serializer
                serializer = CreateDeliverySerializer(data=quote_data)
                serializer.is_valid(raise_exception=True)
                validated_data = serializer.validated_data

                # Create the Uber pickup delivery
                pickup_delivery = create_and_save_delivery(
                    user=quote.customer,
                    validated_data=validated_data,
                    payload=validated_data,
                    is_return_leg=False  # this is always pickup leg
                )

                # Link manifest items to the delivery
                ManifestItem.objects.filter(delivery_quote=quote).update(
                    delivery=pickup_delivery
                )

                # Update pickup delivery details
                pickup_delivery.quote = quote
                pickup_delivery.quote_uid = quote.quote_id
                pickup_delivery.pickup_ready = quote.pickup_ready_dt

                pickup_delivery.save(update_fields=[
                    "quote",
                    "quote_uid",
                    "pickup_ready",
                    "pickup_name",  # only if changed
                ])

                # Finalize the quote status to 'accepted'
                quote.status = 'accepted'
                quote.save(update_fields=['status'])

                # Optionally, notify the customer about the acceptance (e.g., customer_receive_accept_notification)
                # customer_receive_accept_notification(order, quote.customer)

                return {
                    "success": True,
                    "quote_id": quote.quote_id,
                    "order_id": order.id,
                    "status": "accepted",
                    "pickup_delivery_uid": pickup_delivery.delivery_uid,
                    "tracking_url": pickup_delivery.tracking_url,
                    "fee": pickup_delivery.fee,
                    "message": "Quote accepted → Order created → Pickup delivery scheduled"
                }

        else:
            # Reject the quote by setting the status to 'rejected'
            quote.status = 'rejected'
            quote.save(update_fields=['status'])

            # Optionally notify the customer about the rejection
            customer_receive_reject_notification(quote, quote.customer)
            if quote.customer.preference=='Auto-assign another LaundryMart (fastest)':
                initiate_auto_assign_order_and_delivery(quote, quote.customer)

            return {
                "success": False,
                "quote_id": quote.quote_id,
                "status": "rejected"
            }

    except DeliveryQuote.DoesNotExist:
        logger.error("DeliveryQuote does not exist")
        return {"error": f"Quote with ID {quote_id} does not exist"}
    except Exception as e:
        logger.exception(e)
        return {"error": str(e)}