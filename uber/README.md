# Uber App

This app handles the integration with Uber Direct for logistics and delivery.

## Key Models

- **DeliveryQuote**: Stores quotes from Uber, including fees, ETAs, and validation status using Stripe.
- **Delivery**: Tracks active and past Uber deliveries, including courier info and real-time status.
- **ManifestItem**: Details the items (e.g., laundry bags) being transported in a delivery.

## Features

- Real-time logistics integration via Uber Direct.
- Support for multi-leg deliveries (pickup and return).
- Webhook/polling support for delivery status updates.
- Manifest management for insurance and courier verification.
