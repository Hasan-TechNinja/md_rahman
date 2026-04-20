# Laundrymart Project

A Django-based platform for laundry pickup and delivery services, integrated with Uber Direct for logistics and Stripe for payments.

## Project Structure

This project is composed of several Django apps, each handling a specific part of the system:

- **[Accounts](./accounts/README.md)**: User management, authentication, and store details.
- **[Admin Panel](./admin_panel/README.md)**: Global settings, dynamic content, and notifications.
- **[Customer](./customer/README.md)**: Customer reviews, issue reporting, and market tracking.
- **[Vendor](./vendor/README.md)**: Vendor-specific reporting and order tracking.
- **[Payment](./payment/README.md)**: Order lifecycle, Stripe integration, and vendor payouts.
- **[Uber](./uber/README.md)**: Uber Direct integration for pickup and delivery.
- **[Messaging](./messaging/README.md)**: Real-time chat and system notifications.

## Technologies

- **Backend**: Django, Django REST Framework
- **Payments**: Stripe (including Connect for payouts)
- **Logistics**: Uber Direct
- **Database**: SQLite (development) / PostgreSQL (production candidate)
- **Cache**: Redis
- **Real-time**: Django Channels (implied by messaging)
