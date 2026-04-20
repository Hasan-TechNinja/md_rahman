# Accounts App

This app handles user authentication, profile management, and store details.

## Key Models

- **User**: Custom user model supporting email/phone login, OTP verification, and location data. Includes properties for turnaround time and store status.
- **LaundrymartStore**: Details about laundry service providers, including pricing (base and service fees), operating hours, capacity, and location.
- **SecondaryLocation**: Allows users to store multiple addresses.
- **Service**: Defines specific laundry services offered by stores.
- **Employee**: Manages store staff with specific permissions.

## Features

- Custom authentication backend (Email/Phone).
- OTP-based registration and verification.
- Integration with Stripe for customer and connect account IDs.
- Geocoding support via Google Maps API.
