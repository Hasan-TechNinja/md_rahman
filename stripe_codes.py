"""
For new users: Collect card info via Stripe dashboard using a SetupIntent
For returning users: Show them their saved cards from Stripe and let them select one without redirecting to the Stripe dashboard
When a returning user selects a saved card, create a SetupIntent automatically
Here's how to implement this flow:

1. Initial Card Setup for New Users



"""
from payment.utils import create_stripe_customer


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_first_time_setup(request):
  """Create Checkout Session with Setup Mode for new users"""
  try:
    # Get or create customer ID
    if not request.user.stripe_customer_id:
      customer_id = create_stripe_customer(request.user)
      if not customer_id:
        return Response({
          'success': False,
          'error': 'Failed to create customer'
        }, status=400)
    else:
      customer_id = request.user.stripe_customer_id

    # Check if customer already has payment methods
    payment_methods = stripe.PaymentMethod.list(
      customer=customer_id,
      type="card"
    )

    if payment_methods.data:
      # User already has cards, don't need to collect again
      return Response({
        'success': True,
        'has_cards': True,
        'redirect_needed': False,
        'message': 'User already has payment methods'
      })

    # Create a Checkout Session in setup mode
    checkout_session = stripe.checkout.sessions.create(
      payment_method_types=['card'],
      mode='setup',
      customer=customer_id,
      success_url=request.build_absolute_uri('/payment-success?session_id={CHECKOUT_SESSION_ID}'),
      cancel_url=request.build_absolute_uri('/payment-canceled'),
    )

    # Return the session ID and URL
    return Response({
      'success': True,
      'has_cards': False,
      'redirect_needed': True,
      'session_id': checkout_session.id,
      'url': checkout_session.url
    })

  except Exception as e:
    return Response({
      'success': False,
      'error': str(e)
    }, status=400)
#2. Get Saved Cards for Returning Users
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_saved_cards(request):
  """Get all cards saved in Stripe for this user"""
  try:
    # Check for customer ID
    if not request.user.stripe_customer_id:
      return Response({
        'success': True,
        'has_cards': False,
        'cards': []
      })

    # Get payment methods from Stripe
    payment_methods = stripe.PaymentMethod.list(
      customer=request.user.stripe_customer_id,
      type="card"
    )

    # Format card data
    cards = []
    for pm in payment_methods.data:
      cards.append({
        'id': pm.id,
        'brand': pm.card.brand,
        'last4': pm.card.last4,
        'exp_month': pm.card.exp_month,
        'exp_year': pm.card.exp_year
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
# 3. Create SetupIntent for Selected Saved Card
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def setup_intent_with_saved_card(request):
  """Create a SetupIntent with a previously saved card"""
  try:
    data = request.data
    payment_method_id = data.get('payment_method_id')
    service_type = data.get('service_type')
    amount = data.get('amount')  # For reference only, not used in SetupIntent

    if not payment_method_id or not service_type:
      return Response({
        'success': False,
        'error': 'Missing required parameters'
      }, status=400)

    # Check for customer ID
    if not request.user.stripe_customer_id:
      return Response({
        'success': False,
        'error': 'No customer profile found'
      }, status=400)

    # Verify the payment method belongs to this user
    try:
      pm = stripe.PaymentMethod.retrieve(payment_method_id)
      if pm.customer != request.user.stripe_customer_id:
        return Response({
          'success': False,
          'error': 'Payment method does not belong to this customer'
        }, status=403)
    except Exception:
      return Response({
        'success': False,
        'error': 'Invalid payment method'
      }, status=400)

    # Create order to track this transaction
    order = Order.objects.create(
      customer=request.user,
      service_type=service_type,
      total=float(amount) if amount else 0,
      payment_status='pending'
    )

    # Create SetupIntent with the specified payment method
    setup_intent = stripe.SetupIntent.create(
      customer=request.user.stripe_customer_id,
      payment_method=payment_method_id,  # Use the saved payment method
      payment_method_types=['card'],
      usage='off_session',  # Important for future off-session payments
      metadata={
        'order_id': order.id,
        'service_type': service_type,
        'amount': amount  # Store for reference
      },
      confirm=True  # Confirm immediately since we're using a saved method
    )

    # Check setup intent status
    if setup_intent.status == 'succeeded':
      # SetupIntent was immediately successful
      order.payment_status = 'ready'  # Not charged yet, but ready
      order.save()

      return Response({
        'success': True,
        'setup_intent_id': setup_intent.id,
        'status': 'succeeded',
        'requires_action': False,
        'order_id': order.id
      })

    elif setup_intent.status == 'requires_action':
      # Additional authentication needed (3D Secure)
      return Response({
        'success': True,
        'setup_intent_id': setup_intent.id,
        'client_secret': setup_intent.client_secret,
        'status': 'requires_action',
        'requires_action': True,
        'order_id': order.id
      })

    else:
      # Other status
      return Response({
        'success': True,
        'setup_intent_id': setup_intent.id,
        'status': setup_intent.status,
        'requires_action': False,
        'order_id': order.id
      })

  except Exception as e:
    return Response({
      'success': False,
      'error': str(e)
    }, status=400)

#4. Process Payment After SetupIntent is Complete
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def process_payment_after_setup(request):
  """Process payment after SetupIntent is completed"""
  try:
    data = request.data
    setup_intent_id = data.get('setup_intent_id')
    order_id = data.get('order_id')

    if not setup_intent_id or not order_id:
      return Response({
        'success': False,
        'error': 'Missing required parameters'
      }, status=400)

    # Get the order
    try:
      order = Order.objects.get(id=order_id, customer=request.user)
    except Order.DoesNotExist:
      return Response({
        'success': False,
        'error': 'Order not found'
      }, status=404)

    # Get setup intent to verify status
    setup_intent = stripe.SetupIntent.retrieve(setup_intent_id)

    # Verify setup intent belongs to this user
    if setup_intent.customer != request.user.stripe_customer_id:
      return Response({
        'success': False,
        'error': 'SetupIntent does not belong to this customer'
      }, status=403)

    # Make sure setup intent is successful
    if setup_intent.status != 'succeeded':
      return Response({
        'success': False,
        'error': f'SetupIntent is not complete (status: {setup_intent.status})'
      }, status=400)

    # Get amount from metadata or order
    amount = int(float(setup_intent.metadata.get('amount', order.total)) * 100)

    # Create a PaymentIntent using the payment method from the SetupIntent
    payment_intent = stripe.PaymentIntent.create(
      amount=amount,
      currency='usd',
      customer=request.user.stripe_customer_id,
      payment_method=setup_intent.payment_method,
      off_session=True,
      confirm=True,
      metadata={
        'order_id': order.id,
        'service_type': order.service_type
      }
    )

    # Update order
    order.payment_id = payment_intent.id

    if payment_intent.status == 'succeeded':
      order.payment_status = 'paid'
      order.save()

      return Response({
        'success': True,
        'status': 'succeeded',
        'order_id': order.id
      })

    elif payment_intent.status == 'requires_action':
      # Additional action needed
      order.save()

      return Response({
        'success': True,
        'requires_action': True,
        'payment_intent_client_secret': payment_intent.client_secret,
        'status': payment_intent.status,
        'order_id': order.id
      })

    else:
      # Other status
      order.payment_status = payment_intent.status
      order.save()

      return Response({
        'success': True,
        'status': payment_intent.status,
        'order_id': order.id
      })

  except stripe.error.CardError as e:
    # Card was declined
    return Response({
      'success': False,
      'error': e.error.message
    }, status=400)

  except Exception as e:
    return Response({
      'success': False,
      'error': str(e)
    }, status=400)

