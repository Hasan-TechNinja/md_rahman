# Payment App

This is the core app for handling transactions, order lifecycle, and vendor payouts.

## Key Models

- **Order**: The central model for laundry orders, tracking pickup/dropoff, pricing, and overall status.
- **OrderProgression**: Tracks specific steps in the order lifecycle based on the service type (e.g., Full Service, Pick up only).
- **Payment**: Records of final Stripe charges.
- **SavedPaymentMethod**: References to customer payment methods in Stripe.
- **VendorPayout**: Manages the transfer of funds to vendors, including support for instant payouts.
- **PendingStripeOrder**: Temporary state for orders during the checkout process.

## Features

- Complete order lifecycle management from setup to completion.
- Deep integration with Stripe for payments and payouts (Connect).
- Dynamic progression tracking based on service level.
- Automated fee calculations (service charges, insurance, delivery).
