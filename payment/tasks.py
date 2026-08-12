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
def process_acceptance_by_vendor(quote_id, is_manual=False):
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

        # Check if the store's auto_accept_orders flag is True or it's a manual accept
        if store.auto_accept_orders or is_manual:
            # Proceed to create the order and the delivery
            logger.info('Accepting the quote and creating order/delivery')
            with transaction.atomic():
                # Prepare the data to create the order
                print(f"during delivery quote: fee={quote.fee}, manifest_total_value={quote.manifest_total_value}, insurance_amount={quote.insurance_amount}, validation_amount_cents={quote.validation_amount_cents}")
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
                    estimated_value=quote.manifest_total_value,
                    final_total_cents=quote.validation_amount_cents,
                    delivery_fee_cents=quote.fee
                )
                print(f"after conversion to order: estimated_value={order.estimated_value}, service_charge_cents={order.service_charge_cents}, delivery_fee_cents={order.delivery_fee_cents}, final_total_cents={order.final_total_cents}, insurance_amount={order.insurance_amount}")
                logger.info(f'Order created with ID: {order.id}')
                logger.info('Attempting to call the create progress button')
                order.create_progress_steps()

                if quote.service_type in ['pick_up', 'full_service']:
                    actual_pickup_name = quote.customer.full_name or "Customer"
                    actual_dropoff_name = store.laundrymart_name

                    # Create the pickup delivery using the create_and_save_delivery function
                    quote_data = {
                        "quote_id": quote.quote_id,
                        "pickup_name": actual_pickup_name,
                        "pickup_address": quote.pickup_address,
                        "pickup_phone_number": quote.pickup_phone_number,
                        "dropoff_name": actual_dropoff_name,
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
                        user=quote.customer.id,
                        validated_data=validated_data,
                        payload=validated_data,
                        order_id=order.uuid,
                        is_return_leg=False  # this is always pickup leg
                    )

                    # Link manifest items to the delivery
                    ManifestItem.objects.filter(delivery_quote=quote).update(
                        delivery=pickup_delivery,
                        stripe_order=order.id
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
                    
                    # Update order with delivery reference
                    order.uber_pickup_delivery_id = pickup_delivery.delivery_uid
                    order.pickup_delivery = pickup_delivery
                    order.delivery_fee_cents = pickup_delivery.fee
                    order.save(update_fields=['uber_pickup_delivery_id', 'pickup_delivery','delivery_fee_cents'])

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
                    "pickup_delivery_uid": pickup_delivery.delivery_uid if 'pickup_delivery' in locals() and pickup_delivery else None,
                    "tracking_url": pickup_delivery.tracking_url if 'pickup_delivery' in locals() and pickup_delivery else None,
                    "fee": pickup_delivery.fee if 'pickup_delivery' in locals() and pickup_delivery else None,
                    "message": "Quote accepted → Order created" + (" → Pickup delivery scheduled" if 'pickup_delivery' in locals() and pickup_delivery else "")
                }

        else:
            #check whether customer's auto assign another vendor option is on or not. and then execute
            # that function after 8 minutes
            from customer.tasks import auto_assign_another_laundrymart
            if quote.customer.preference == 'Auto-assign another LaundryMart (fastest)':
                return auto_assign_another_laundrymart.apply_async(
                    args=[quote.id, quote.customer.id],
                    countdown=480
                )


    except DeliveryQuote.DoesNotExist:
        logger.error("DeliveryQuote does not exist")
        return {"error": f"Quote with ID {quote_id} does not exist"}
    except Exception as e:
        logger.exception(e)
        return {"error": str(e)}
