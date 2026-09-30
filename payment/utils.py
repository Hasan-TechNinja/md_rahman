# payments/utils.py
import stripe
from django.conf import settings

from payment.models import PendingStripeOrder, SavedPaymentMethod
stripe.api_key = settings.STRIPE_SECRET_KEY
import logging
logger = logging.getLogger(__name__)


def create_pending_stripe_order(user, metadata):
  pending_order = PendingStripeOrder.objects.create(
    user=user,
    metadata=metadata
  )
  return pending_order
def create_or_get_stripe_customer(user):
  """Create Stripe Customer if not exists in User model"""
  # Check if user already has a Stripe customer ID
  if not user.stripe_customer_id:
    try:
      # Create a new customer in Stripe
      customer = stripe.Customer.create(
        email=user.email or None,
        name=user.full_name,  # Assuming Django's User model
        metadata={'django_user_id': user.id}
      )
      user.stripe_customer_id = customer.id
      user.save()

      return {'customer_id':customer.id, 'is_new': True}

    except Exception as e:
      # Log the error
      logger.error(f"Error creating Stripe customer: {str(e)}")
      return None

  return {'customer_id':user.stripe_customer_id, 'is_new': False}

def create_setup_checkout_session(order, success_url, cancel_url):
  """
  Create Checkout Session in setup mode (zero charge, saves card)
  """
  session = stripe.checkout.Session.create(
    mode="setup",
    customer=order.stripe_customer_id,
    payment_method_types=["card"],
    success_url=success_url,
    cancel_url=cancel_url,
    metadata={'order_uuid': str(order.uuid)},
  )
  return session

def sync_payment_method(user, payment_method_id):
    """Save payment method reference to database"""
    import stripe
    from django.conf import settings

    stripe.api_key = settings.STRIPE_SECRET_KEY

    try:
      # Retrieve the payment method details from Stripe
      pm = stripe.PaymentMethod.retrieve(payment_method_id)

      # Check if this payment method already exists in our DB
      existing = SavedPaymentMethod.objects.filter(
        user=user,
        stripe_payment_method_id=payment_method_id
      ).first()

      if existing:
        # Update the existing record
        existing.last4 = pm.card.last4
        existing.card_brand = pm.card.brand
        existing.exp_month = pm.card.exp_month
        existing.exp_year = pm.card.exp_year
        existing.save()
        return existing

      # Create a new record
      payment_method = SavedPaymentMethod.objects.create(
        user=user,
        stripe_payment_method_id=payment_method_id,
        last4=pm.card.last4,
        card_brand=pm.card.brand,
        exp_month=pm.card.exp_month,
        exp_year=pm.card.exp_year,
        # If this is the user's first payment method, make it the default
        is_default=not SavedPaymentMethod.objects.filter(user=user).exists()
      )

      return payment_method

    except Exception as e:
      logger.error(f"Error syncing payment method: {str(e)}")
      return None
import stripe
from typing import Dict, Any, List, Optional


def create_setup_intent(stripe_customer_id: str, metadata: dict = None) -> Dict[str, Any]:
  """
  Create a SetupIntent to add a new card in-app (used in payment settings).
  No redirect to Stripe Checkout – fully handled in your mobile/web form.

  Args:
      stripe_customer_id: Stripe Customer ID from user.stripe_customer_id
      metadata: Optional metadata (e.g., {"django_user_id": str(user.id)})

  Returns:
      Dict with client_secret for frontend use
  """
  try:
    params = {
      "customer": stripe_customer_id,
      "payment_method_types": ["card"],
      "usage": "off_session",  # Allows future off-session charges
    }
    if metadata:
      params["metadata"] = metadata

    setup_intent = stripe.SetupIntent.create(**params)

    return {
      "success": True,
      "client_secret": setup_intent.client_secret,
      "setup_intent_id": setup_intent.id,
    }

  except stripe.error.StripeError as e:
    return {"success": False, "error": str(e)}
  except Exception as e:
    return {"success": False, "error": f"Unexpected error: {str(e)}"}

def list_saved_payment_methods(stripe_customer_id: str) -> List[Dict[str, Any]]:
  """
  List all saved card payment methods for a Stripe customer.

  Args:
      stripe_customer_id: Stripe Customer ID from user.stripe_customer_id
  Returns:
      List of payment method dicts with card details
  """
  try:
    payment_methods = stripe.PaymentMethod.list(
      customer=stripe_customer_id,
      type="card"
    )

    cards = []
    for pm in payment_methods.data:
      cards.append({
        "id": pm.id,
        "brand": pm.card.brand,
        "last4": pm.card.last4,
        "exp_month": pm.card.exp_month,
        "exp_year": pm.card.exp_year,
      })

    return cards

  except stripe.error.StripeError as e:
    logger.error(f"Stripe error listing payment methods: {str(e)}")
    return []
  except Exception as e:
    logger.error(f"Unexpected error listing payment methods: {str(e)}")
    return []