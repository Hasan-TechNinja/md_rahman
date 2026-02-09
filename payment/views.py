import json
from uuid import uuid4

import requests
import stripe
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from unfold.views import UnfoldModelAdminViewMixin

from accounts.models import LaundrymartStore, User
from laundrymart.permissions import IsCustomer
from laundrymart.settings import STRIPE_PUBLISHABLE_KEY, STRIPE_SECRET_KEY
from django.shortcuts import render, redirect
from django.contrib import messages
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from .models import LaundrymartPaymentMethod
from payment.tasks import process_acceptance_by_vendor
from payment.utils import create_or_get_stripe_customer
from uber.models import DeliveryQuote, SERVICE_TYPE_CHOICE
from uber.serializers import DeliveryQuoteCreateSerializer
from vendor_push_notification.utils import vendor_accept_or_reject_notification


# Create your views here.
def stripe_success(request):
  return render(request, "payment/stripe_success.html")

def stripe_cancel(request):
  return render(request, "payment/stripe_cancel.html")

class ConfirmOrderAPIView(APIView):
  permission_classes = [IsCustomer]
  @extend_schema(
    request=DeliveryQuoteCreateSerializer
  )
  def post(self, request):
    with transaction.atomic():
      serializer = DeliveryQuoteCreateSerializer(data=request.data)
      serializer.is_valid(raise_exception=True)

      service_type = serializer.validated_data.get("service_type")

      # Ensure Stripe customer exists (create if needed)
      stripe_customer_result = create_or_get_stripe_customer(request.user)
      if not stripe_customer_result:
        return Response({"error": "Failed to initialize payment customer"}, status=500)

      stripe_customer_id = stripe_customer_result['customer_id']

      # Retrieve attached payment methods (optimized: single API call)
      try:
        payment_methods = stripe.PaymentMethod.list(
          customer=stripe_customer_id,
          type="card",
          limit=100,
        )
        has_saved_cards = len(payment_methods.data) > 0
      except Exception as e:
        return Response({"error": f"Failed to retrieve payment methods: {str(e)}"}, status=500)

      # Create the pending DeliveryQuote using serializer.save()
      # We inject required fields that are not in request.data: customer and default status
      pending_quote = serializer.save(customer=request.user)

      if has_saved_cards:
        cards = []
        for pm in payment_methods.data:
          cards.append({
            'id': pm.id,
            'brand': pm.card.brand.capitalize(),
            'last4': pm.card.last4,
            'exp_month': pm.card.exp_month,
            'exp_year': pm.card.exp_year,
            # 'pending_quote': str(pending_quote.id),   ← not needed here
          })

        return Response({
          "requires_card_validation": False,
          "has_saved_cards": True,
          "cards": cards,
          "pending_quote_id": str(pending_quote.id),
          "message": "Select a saved card to continue",
        }, status=status.HTTP_200_OK)


      else:

        return Response({
          "requires_card_validation": True,
          "has_saved_cards": False,
          "cards": [],
          "pending_quote_id": str(pending_quote.id),
          "message": "Please Add a billing card to progress further.",
        }, status=status.HTTP_200_OK)

# orders/views.py or similar
class SelectPaymentMethodForQuoteAPIView(APIView):
    """
    User selected existing saved card for this delivery quote
    """
    permission_classes = [IsCustomer]

    @transaction.atomic
    def post(self, request):
        pending_quote_id = request.data.get('pending_quote_id')
        payment_method_id = request.data.get('payment_method_id')

        if not pending_quote_id or not payment_method_id:
            return Response(
                {"error": "Both pending_quote_id and payment_method_id are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            quote = DeliveryQuote.objects.select_for_update().get(
                id=pending_quote_id,
                customer=request.user,
                payment_method_id=payment_method_id
            )

            # Very important security check: verify this PM belongs to the user
            pm = stripe.PaymentMethod.retrieve(payment_method_id)
            if pm.customer != request.user.stripe_customer_id:
                return Response(
                    {"error": "This payment method does not belong to you"},
                    status=status.HTTP_403_FORBIDDEN
                )
            # Optional but recommended: confirm it can be used off-session
            # (most already-attached cards are already confirmed, but we can be extra safe)

            stripe.SetupIntent.create(
                customer=request.user.stripe_customer_id,
                payment_method=payment_method_id,
                confirm=True,
                usage='off_session',
            )

            # Now the quote is ready for vendor
            quote.status = 'pending'
            quote.save(update_fields=['status'])

            # Notify vendor
            if quote.external_store_id:
                try:
                    store = LaundrymartStore.objects.get(id=quote.external_store_id)
                    vendor_accept_or_reject_notification(quote, store)
                    print(
                        f"Vendor notified - existing card selected | "
                        f"Quote: {quote.quote_id} → pending"
                    )
                except LaundrymartStore.DoesNotExist:
                    print(f"Store not found for quote {quote.quote_id}")

            return Response({
                "success": True,
                "message": "Payment method selected. Quote is now pending vendor approval.",
                "quote_status": quote.status
            }, status=status.HTTP_200_OK)

        except DeliveryQuote.DoesNotExist:
            return Response(
                {"error": "Quote not found or doesn't belong to you"},
                status=status.HTTP_404_NOT_FOUND
            )
        except stripe.error.StripeError as e:
            print(f"Stripe error while confirming PM: {str(e)}")
            return Response(
                {"error": "Payment method confirmation failed. Please try another card."},
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            print("Unexpected error in select payment method")
            return Response(
                {"error": "Something went wrong. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

@require_POST
# @csrf_exempt
# @transaction.atomic
# def stripe_webhook_confirm_order(request):
#   """
#   Stripe webhook - handles successful card setup (checkout.session.completed mode=setup)
#   Updates DeliveryQuote to 'pending' and notifies vendor
#   """
#   payload = request.body
#   sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
#
#   try:
#     event = stripe.Webhook.construct_event(
#       payload,
#       sig_header,
#       CUSTOMER_CONFIRM_ORDER_STRIPE_WEBHOOK_SECRET
#     )
#   except ValueError:
#     print("Invalid payload")
#     return HttpResponse(status=400)
#   except stripe.error.SignatureVerificationError:
#     print("Webhook signature verification failed")
#     return HttpResponse(status=400)
#
#   if event["type"] == "checkout.session.completed":
#     session = event["data"]["object"]
#
#     if session.get("mode") != "setup":
#       return HttpResponse(status=200)
#
#     pending_quote_id = session.metadata.get("pending_quote_id")
#     if not pending_quote_id:
#       print("No pending_quote_id in session metadata")
#       return HttpResponse(status=200)
#
#     try:
#       # Lock the quote row to prevent concurrent modifications
#       quote = DeliveryQuote.objects.select_for_update().get(id=pending_quote_id)
#
#       # Mark quote as ready for vendor review
#       quote.status = 'pending'
#       quote.save(update_fields=['status'])
#
#       # Optional: you could also store payment method reference here if needed later
#       # quote.stripe_payment_method_id = session.payment_method   # ← if you add this field
#       # quote.save(update_fields=['status', 'stripe_payment_method_id'])
#
#       # Find the assigned laundry store
#       # (assuming you set external_store_id when creating quote)
#       if quote.external_store_id:
#         try:
#           laundrymart = LaundrymartStore.objects.get(
#             store_id=quote.external_store_id  # or whatever field you use to link
#           )
#           vendor_accept_or_reject_notification(quote, laundrymart)
#
#           print(
#             f"Vendor notified after successful card setup | "
#             f"Quote: {quote.quote_id} → pending | "
#             f"Store: {laundrymart.laundrymart_name}"
#           )
#         except LaundrymartStore.DoesNotExist:
#           print(f"Store not found for quote {quote.quote_id} "
#                          f"(external_store_id: {quote.external_store_id})")
#       else:
#         print(f"No external_store_id set on quote {quote.quote_id}")
#
#     except DeliveryQuote.DoesNotExist:
#       print(f"Quote not found: {pending_quote_id}")
#     except Exception as e:
#       print("Error processing successful card setup webhook")
#
#   return HttpResponse(status=200)



@api_view(['POST'])
@permission_classes([IsCustomer])
def add_card_backend(request):
  """Add a new card for the customer via backend (creates SetupIntent)"""
  try:
    # Ensure Stripe customer exists
    if not request.user.stripe_customer_id:
      customer_result = create_or_get_stripe_customer(request.user)
      if not customer_result:
        return Response({
          'success': False,
          'error': 'Failed to create customer'
        }, status=400)

    # Create SetupIntent
    setup_intent = stripe.SetupIntent.create(
      customer=request.user.stripe_customer_id,
      payment_method_types=["card"],
      usage="off_session",
    )

    return Response({
      'success': True,
      'setup_intent_client_secret': setup_intent.client_secret,
      "setup_intent_id": setup_intent.id
    })

  except Exception as e:
    return Response({
      'success': False,
      'error': str(e)
    }, status=400)

class CardSerializer(serializers.Serializer):
  amount = serializers.DecimalField(max_digits=12, decimal_places=2)
  service_type = serializers.ChoiceField(required=True, choices=SERVICE_TYPE_CHOICE)
  payment_method_id = serializers.CharField(required=True)
  pending_quote_id= serializers.CharField(required=True)


@extend_schema(
  request=CardSerializer
)
@api_view(['POST'])
@permission_classes([IsCustomer])
@transaction.atomic
def validate_saved_method(request):
    """
    Validates/attempts off-session authorization with selected saved card for a pending DeliveryQuote.
    Uses idempotency to prevent duplicate PaymentIntents.
    Does NOT capture — places manual authorization hold if possible.
    """

    serializer = CardSerializer(data=request.data)
    print(request.data)
    if not serializer.is_valid():
        return Response({
            "success": False,
            "error": "Invalid input",
            "details": serializer.errors
        }, status=400)

    data = serializer.validated_data
    amount_cents = int(float(data["amount"])*100)
    print(amount_cents)
    service_type = data["service_type"]
    payment_method_id = data["payment_method_id"]  # required per your serializer
    pending_quote_id = data["pending_quote_id"]

    user = request.user
    if not user.stripe_customer_id:
        return Response({"success": False, "error": "No Stripe customer profile"}, status=400)

    customer_id = user.stripe_customer_id

    # 1. Fetch quote with lock + check if already validated successfully
    try:
        quote = DeliveryQuote.objects.select_for_update().get(
            id=pending_quote_id,
            customer=user,
        )
    except DeliveryQuote.DoesNotExist:
        return Response({"success": False, "error": "Quote not found or not owned by user"}, status=404)

    # Optional safety: prevent re-validation if already authorized
    # (you can remove or make optional depending on your flow)
    if quote.expires and quote.expires < timezone.now():
      return Response({"success": False, "error": "Quote expired. Please make a new order."}, status=404)
    if quote.validation_status in ("authorized", "succeeded") and quote.validation_pi_id:

        return Response({
            "success": True,
            "requires_action": False,
            "status": quote.validation_status,
            "payment_intent_id": quote.validation_pi_id,
            "message": "Quote already has valid authorization"
        }, status=200)

    # 2. Verify payment method ownership
    try:
        pm = stripe.PaymentMethod.retrieve(payment_method_id)
        if pm.customer != customer_id:
            return Response({"success": False, "error": "Payment method not owned by user"}, status=403)
    except stripe.error.InvalidRequestError:
        return Response({"success": False, "error": "Invalid payment method ID"}, status=400)

    # 3. Deterministic idempotency key → safe retries
    idempotency_key = f"validate_quote_{quote.id}_{user.id}"

    with transaction.atomic():
        try:
            pi = stripe.PaymentIntent.create(
                amount=amount_cents,
                currency="usd",
                customer=customer_id,
                payment_method=payment_method_id,
                off_session=True,
                confirm=True,
                capture_method="manual",  # hold only — capture later after weighing
                description=f"LaundryMart validation - quote {quote.id} - user {user.id}",
                metadata={
                    "user_id": str(user.id),
                    "quote_id": str(quote.id),
                    "service_type": service_type,
                    "attempt": "card_validation",
                },
                idempotency_key=idempotency_key,  # ← prevents duplicate PI creation
            )

            # Update quote with validation result (suggested fields from earlier)
            quote.validation_pi_id = pi.id
            quote.payment_method_id = payment_method_id
            quote.validation_amount_cents = int(float(data["amount"]))*100

            if pi.status == "requires_capture":
                quote.validation_status = "authorized"
                quote.status = "pending"
                process_acceptance_by_vendor.apply_async(args=[pending_quote_id], countdown=10*60)
                msg = "Card validated – authorization hold placed"
            elif pi.status == "requires_action":
                quote.validation_status = "requires_action"
                msg = "3D Secure authentication required"
            elif pi.status == "succeeded":  # rare for off-session larger amounts
                quote.validation_status = "succeeded"
                msg = "Instant confirmation succeeded"
            else:
                quote.validation_status = "failed"
                msg = f"Unexpected state: {pi.status}"

            quote.save(update_fields=[
                'validation_pi_id',
                'payment_method_id',
                'validation_amount_cents',
                'validation_status',
                'status'
            ])

            if pi.status in ("succeeded", "requires_capture"):
                serializer=DeliveryQuoteCreateSerializer(quote)
                return Response({
                    "success": True,
                    "data":serializer.data,
                    "requires_action": False,
                    "status": pi.status,
                    "payment_intent_id": pi.id,
                    "client_secret": pi.client_secret if pi.status == "requires_action" else None,
                    "message": msg
                }, status=200)

            elif pi.status == "requires_action":
                return Response({
                    "success": True,
                    "requires_action": True,
                    "payment_intent_id": pi.id,
                    "client_secret": pi.client_secret,
                    "next_action": pi.next_action,
                    "message": msg
                }, status=200)

            else:
                return Response({
                    "success": False,
                    "error": f"PaymentIntent in unexpected state: {pi.status}",
                    "payment_intent_id": pi.id,
                }, status=400)

        except stripe.error.CardError as e:
            quote.validation_status = "failed"
            quote.save(update_fields=['validation_status'])
            return Response({
                "success": False,
                "error": e.user_message or str(e),
                "code": e.code,
                "decline_code": e.error.get("decline_code") if e.error else None,
            }, status=402)

        except stripe.error.InvalidRequestError as e:
            # idempotency conflict would come here (but Stripe returns 200 with cached result normally)
            if "idempotency" in str(e).lower():
                return Response({
                    "success": False,
                    "error": "Request already processed (idempotency conflict)"
                }, status=409)
            return Response({"success": False, "error": str(e)}, status=400)

        except stripe.error.StripeError as e:
            quote.validation_status = "failed"
            quote.save(update_fields=['validation_status'])
            return Response({"success": False, "error": str(e)}, status=400)

        # except Exception as e:
        #     quote.validation_status = "failed"
        #     quote.save(update_fields=['validation_status'])
        #     return Response({"success": False, "error": "Server error","detail":str(e)}, status=500)


@api_view(['GET'])
@permission_classes([IsCustomer])
def list_cards_from_stripe(request):
  """Fetch saved payment methods directly from Stripe"""
  try:
    # Get or create Stripe customer ID
    if not request.user.stripe_customer_id:
      customer_id = create_or_get_stripe_customer(request.user)
      if not customer_id:
        return Response({
          'success': False,
          'error': 'Failed to create customer'
        }, status=400)
    else:
      customer_id = request.user.stripe_customer_id

    # Fetch payment methods directly from Stripe
    payment_methods = stripe.PaymentMethod.list(
      customer=customer_id,
      type="card"
    )

    # Format card data for the frontend
    cards = []
    for pm in payment_methods.data:
      cards.append({
        'id': pm.id,
        'brand': pm.card.brand,
        'last4': pm.card.last4,
        'exp_month': pm.card.exp_month,
        'exp_year': pm.card.exp_year,
        # Stripe doesn't track which card is default in their API
        # You would need to store this separately if needed
      })

    return Response({
      'success': True,
      'has_cards': len(cards) > 0,
      'cards': cards
    })

  except Exception as e:
    return Response({
      'success': False,
      'error': str(e)
    }, status=400)

@api_view(['POST'])
@permission_classes([IsCustomer])
def retrieve_saved_cards(request):
  """Retrieve saved payment methods for the authenticated user"""
  try:
    # Ensure Stripe customer exists
    if not request.user.stripe_customer_id:
      return Response({
        'message': 'No saved cards found',
        'success': True,
      }, status=200)

    # List saved payment methods from Stripe
    payment_methods = stripe.PaymentMethod.list(
      customer=request.user.stripe_customer_id,
      type="card"
    )

    cards = []
    for pm in payment_methods.data:
      cards.append({
        'id': pm.id,
        'brand': pm.card.brand,
        'last4': pm.card.last4,
        'name_on_card': pm.billing_details.name,
        'exp_month': pm.card.exp_month,
        'exp_year': pm.card.exp_year,
        'country': pm.card.country
      })

    return Response({
      'success': True,
      'has_cards': len(cards) > 0,
      'cards': cards
    })

  except Exception as e:
    return Response({
      'success': False,
      'error': str(e)
    }, status=400)

@api_view(['DELETE'])
@permission_classes([IsCustomer])
def delete_saved_card(request, payment_method_id):
  """Delete a saved payment method for the authenticated user"""
  try:
    # Ensure Stripe customer exists
    if not request.user.stripe_customer_id:
      return Response({
        'success': False,
        'error': 'No customer profile found'
      }, status=400)

    # Retrieve the payment method to verify ownership
    pm = stripe.PaymentMethod.retrieve(payment_method_id)
    if pm.customer != request.user.stripe_customer_id:
      return Response({
        'success': False,
        'error': 'Payment method does not belong to this customer'
      }, status=403)

    # Detach (delete) the payment method from the customer
    stripe.PaymentMethod.detach(payment_method_id)

    return Response({
      'success': True,
      'message': 'Payment method deleted successfully'
    })

  except Exception as e:
    return Response({
      'success': False,
      'error': str(e)
    }, status=400)

#   class SendOfferToVendorAPIView(APIView):
#     """
#     This endpoint is called AFTER the customer has successfully created an Uber quote
#     via UberCreateQuoteAPIView and has a saved/validated payment method.
#
#     It:
#     1. Validates the saved card (with $0 auth) for higher off-session success rate
#     2. Saves the delivery quote details in your system (triggers push notification to vendor)
#     3. Returns success – vendor will later accept/reject via their interface
#     """
#     permission_classes = [IsCustomer]  # Your existing customer permission
#
#     @extend_schema(
#       request=SendOfferSerializer,
#       responses={
#         200: OpenApiResponse(
#           description="Offer sent to vendor successfully. Card validated.",
#           response={
#             "type": "object",
#             "properties": {
#               "message": {"type": "string"},
#               "quote_id": {"type": "string"},
#               "estimated_uber_fee": {"type": "number"},
#               "service_type": {"type": "string"},
#             }
#           }
#         )
#       }
#     )
#     def post(self, request):
#       serializer = SendOfferSerializer(data=request.data)
#       serializer.is_valid(raise_exception=True)
#       quote_data = serializer.validated_data["quote_data"]  # Full response from UberCreateQuoteAPIView
#
#       service_type = quote_data["service_type"]
#
#       # Extract the main quote_id and fee – handle full_service slightly differently
#       if service_type == "full_service":
#         # You can choose to use first_quote or combined logic later
#         main_quote_id = quote_data["first_quote"]["id"]
#         uber_fee_cents = quote_data["combined_fee"]  # or calculate as needed
#       else:
#         main_quote_id = quote_data["quote_id"]
#         uber_fee_cents = quote_data["fee"]
#
#       # Assume stripe_customer_id is stored on user (from earlier create_stripe_customer)
#       stripe_customer_id = request.user.stripe_customer_id
#       if not stripe_customer_id:
#         return Response({"error": "No Stripe customer linked"}, status=400)
#
#       # Optional: Determine default payment method (or let frontend send selected one)
#       # Here we auto-pick the default or only card
#       try:
#         pm_list = stripe.PaymentMethod.list(
#           customer=stripe_customer_id,
#           type="card",
#           limit=1,
#         )
#         if not pm_list.data:
#           return Response({"error": "No saved payment method found"}, status=400)
#         payment_method_id = pm_list.data[0].id
#       except Exception as e:
#         return Response({"error": f"Failed to retrieve payment method: {str(e)}"}, status=500)
#
#       # Step 1: Validate the saved card with $0 confirmed off-session PaymentIntent
#       # (Stripe best practice for increasing future off-session charge success)
#       try:
#         pi = stripe.PaymentIntent.create(
#           amount=0,
#           currency=quote_data.get("currency", "usd").lower(),
#           customer=stripe_customer_id,
#           payment_method=payment_method_id,
#           off_session=True,
#           confirm=True,
#           description=f"Card validation for Uber {service_type} order (quote: {main_quote_id})",
#           metadata={
#             "user_id": str(request.user.id),
#             "service_type": service_type,
#             "uber_quote_id": main_quote_id,
#             "validation_type": "pre_delivery_offer",
#           },
#         )
#
#         if pi.status != "succeeded":
#           return Response({"error": "Card validation failed – please update payment method"}, status=400)
#       except stripe.error.CardError as e:
#         return Response({"error": f"Card declined during validation: {e.user_message or str(e)}"}, status=400)
#       except Exception as e:
#         return Response({"error": f"Card validation error: {str(e)}"}, status=500)
#
#       # Step 2: Save the quote and trigger vendor notification
#       # Extract only the fields needed for save_delivery_quote based on your signature
#       order_payload = {
#         "pickup_address": quote_data["pickup_address"],
#         "dropoff_address": quote_data["dropoff_address"],
#         "pickup_latitude": quote_data["pickup_latitude"],
#         "pickup_longitude": quote_data["pickup_longitude"],
#         "dropoff_latitude": quote_data["dropoff_latitude"],
#         "dropoff_longitude": quote_data["dropoff_longitude"],
#         "pickup_phone_number": quote_data["pickup_phone_number"],
#         "dropoff_phone_number": quote_data["dropoff_phone_number"],
#         # Add any other fields you normally include (manifest_items, etc.) if available
#       }
#
#       uber_data = {
#         "id": main_quote_id,
#         "fee": uber_fee_cents,
#         "currency": quote_data.get("currency"),
#         "currency_type": quote_data.get("currency_type"),
#         "dropoff_eta": quote_data.get("dropoff_eta"),
#         "dropoff_deadline": quote_data.get("dropoff_deadline"),
#       }
#
#       # This call will store the quote and send push notification to vendor
#       save_delivery_quote(
#         user=request.user,
#         service_type=service_type,
#         serializer_data=order_payload,
#         uber_data=uber_data,
#       )
#
#       return Response({
#         "message": "Offer successfully sent to vendor. Your card has been validated.",
#         "quote_id": main_quote_id,
#         "estimated_uber_fee": uber_fee_cents / 100.0,  # Display in dollars
#         "service_type": service_type,
#       }, status=status.HTTP_200_OK)

class SetupIntentCreateView(LoginRequiredMixin,UnfoldModelAdminViewMixin, View):
  """AJAX endpoint: Create SetupIntent for the logged-in laundrymart admin"""

  def post(self, request):
    user = request.user
    profile = get_object_or_404(LaundrymartStore, admin=user)  # where stripe_customer_id is stored

    if not profile.stripe_customer_id:
      try:
        customer = stripe.Customer.create(
          email=user.email,
          name=profile.laundrymart_name,
          metadata={"django_user_id": str(user.id)},
        )
        profile.stripe_customer_id = customer.id
        profile.save(update_fields=['stripe_customer_id'])
      except stripe.error.StripeError as e:
        return JsonResponse({'error': str(e)}, status=400)

    try:
      setup_intent = stripe.SetupIntent.create(
        customer=profile.stripe_customer_id,
        payment_method_types=['card'],
        usage='off_session',  # for future charges if needed
      )
      return JsonResponse({
        'client_secret': setup_intent.client_secret,
        'customer_id': profile.stripe_customer_id,
      })
    except stripe.error.StripeError as e:
      return JsonResponse({'error': e.user_message or str(e)}, status=400)


class AddPaymentMethodView(LoginRequiredMixin, UnfoldModelAdminViewMixin, TemplateView):
  template_name = 'admin_panels/vendor/add_payment_method.html'

  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)
    context['stripe_publishable_key'] = STRIPE_PUBLISHABLE_KEY
    return context

def sync_latest_payment_method(user):
  profile = LaundrymartStore.objects.get(admin=user)
  if not profile.stripe_customer_id:
    return

  pms = stripe.PaymentMethod.list(
    customer=profile.stripe_customer_id,
    type='card',
    limit=1,  # get the most recent
  )

  if pms.data:
    pm = pms.data[0]
    LaundrymartPaymentMethod.objects.update_or_create(
      laundrymart_admin=user,
      stripe_payment_method_id=pm.id,
      defaults={
        'stripe_external_account_id': '',  # empty for cards
        'brand': pm.card.brand,
        'last4': pm.card.last4,
        'exp_month': pm.card.exp_month,
        'exp_year': pm.card.exp_year,
        # is_default: can set if no others, etc.
      }
    )