# Admin Panel App

This app provides global configuration and administrative settings for the platform.

## Key Models

- **GlobalManifest**: A singleton model for platform-wide settings such as service fees, insurance fees, Stripe charges, and UI content (FAQs, policies, landing page text).
- **NotificationText**: A singleton model to customize system-generated notification messages for various order stages.
- **SlideImage**: Manages carousel images for the mobile application.

## Features

- Uses `django-solo` for singleton configuration management.
- Cache-aware settings (Redis) to ensure high performance.
- Centralized control for both Customer and Vendor app content.
