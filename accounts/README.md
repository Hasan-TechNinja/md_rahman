# Accounts Module Documentation

The `accounts` module manages identity, authentication, profile management, store configuration, multi-address management, and role-based access control (Customer, Vendor, Employee, Admin).

---

## 1. Database Tables & Models

| Model Name | Database Table | Description |
|---|---|---|
| `User` | `accounts_user` | Custom user model extending `AbstractUser`. Houses customer and vendor credentials, coordinates (`lat`, `lng`), OTP fields, Stripe customer/connect IDs, and customer dispatch preferences. |
| `LaundrymartStore` | `accounts_laundrymartstore` | Details of laundromat service providers: store location, Google ratings, base price per pound, service fees, operating hours for each day of the week, turnaround times, and order acceptance toggles. |
| `SecondaryLocation` | `accounts_secondarylocation` | Multiple saved addresses for customers (e.g., Home, Work, Other) with latitude and longitude. |
| `Service` | `accounts_service` | Specific services provided by a `LaundrymartStore` with individual price-per-pound rules. |
| `Employee` | `accounts_employee` | Store-level staff accounts associated with a specific `LaundrymartStore`, supporting hashed credentials and 2FA via store admin. |
| `CustomerProxy` | *(Proxy for `User`)* | Proxies customer users for Django admin filtering. |
| `VendorProxy` | *(Proxy for `User`)* | Proxies vendor owner users for Django admin filtering. |
| `StaffProxy` | *(Proxy for `User`)* | Proxies internal staff members for Django admin filtering. |

---

## 2. API Endpoints

### 2.1 User Registration & OTP Authentication

#### `POST /accounts/api/register`
* **Handler**: `RegisterView`
* **Permissions**: `AllowAny`
* **Description**: Registers a new customer or vendor. If an existing account with the same email/phone is unverified/inactive, it is cleaned up and recreated. An OTP is generated and dispatched.
* **DB Tables Used**:
  * `accounts_user` (Read, Delete if unverified duplicate, Insert)
* **Request Body**:
  ```json
  {
    "email": "user@example.com",
    "phone_number": "+1234567890",
    "password": "SecurePassword123!",
    "full_name": "John Doe",
    "location": "123 Main St",
    "lat": 40.7128,
    "lng": -74.0060
  }
  ```
* **Response**: `201 Created` with message indicating OTP delivery via Email or SMS.

#### `PATCH /accounts/api/verify-otp`
* **Handler**: `VerifyOTPView`
* **Permissions**: `AllowAny`
* **Description**: Verifies the 4-digit OTP against expiration time (`otp_expires`). Upon success, sets `is_active=True`, `is_verified=True`, clears OTP fields, and returns JWT access and refresh tokens.
* **DB Tables Used**:
  * `accounts_user` (Read, Update)
* **Request Body**:
  ```json
  {
    "email": "user@example.com",
    "otp": "1234"
  }
  ```
* **Response**: `200 OK` with user payload and JWT tokens (`access`, `refresh`).

#### `POST /accounts/api/resend-otp`
* **Handler**: `ResendOTPView`
* **Permissions**: `AllowAny`
* **Description**: Generates a fresh 4-digit numeric OTP with 1-minute expiration and dispatches it via email or SMS.
* **DB Tables Used**:
  * `accounts_user` (Read, Update)

---

### 2.2 Login & Session Management

#### `POST /accounts/api/login`
* **Handler**: `LoginView`
* **Permissions**: `AllowAny`
* **Description**: Authenticates users using email or phone number and password. Returns JWT token pair.
* **DB Tables Used**:
  * `accounts_user` (Read, Update `last_login`)
* **Request Body**:
  ```json
  {
    "email_or_phone": "user@example.com",
    "password": "SecurePassword123!"
  }
  ```
* **Response**: `200 OK` with user details and tokens.

#### `POST /accounts/api/firebase-login/`
* **Handler**: `FirebaseLoginAPIView`
* **Permissions**: `AllowAny`
* **Description**: Authenticates users using a Firebase JWT ID token. Links to existing user by email or creates a new active user with an unusable password.
* **DB Tables Used**:
  * `accounts_user` (Read, Update, or Insert)
* **Request Body**:
  ```json
  {
    "id_token": "<firebase_id_token>"
  }
  ```

#### `POST /accounts/api/token/refresh`
* **Handler**: `TokenRefreshView` (DRF SimpleJWT)
* **Permissions**: `AllowAny`
* **Description**: Exchanges a valid refresh token for a new access token.

#### `POST /accounts/api/logout`
* **Handler**: `LogoutAPIView`
* **Permissions**: `IsAuthenticated`
* **Description**: Blacklists the client's refresh token.
* **DB Tables Used**:
  * `token_blacklist_outstandingtoken`, `token_blacklist_blacklistedtoken`

---

### 2.3 Store Employee Authentication (Two-Factor Approval)

#### `POST /accounts/api/employee-login`
* **Handler**: `EmployeeLoginOTP`
* **Permissions**: `AllowAny`
* **Description**: Initiates employee login. Validates employee username and password against the store identified by `phone_number`. Generates an OTP and sends it directly to the store owner/admin.
* **DB Tables Used**:
  * `accounts_employee` (Read)
  * `accounts_laundrymartstore` (Read)
  * `accounts_user` (Read, Update OTP for store admin)
* **Request Body**:
  ```json
  {
    "username": "staff1",
    "password": "StaffPassword!",
    "phone_number": "+1234567890"
  }
  ```

#### `PATCH /accounts/api/employee-otp`
* **Handler**: `VerifyEmployeeOTP`
* **Permissions**: `AllowAny`
* **Description**: Verifies the OTP provided by the store admin. On verification, issues custom employee tokens (`EmployeeRefreshToken`) and store admin tokens.
* **DB Tables Used**:
  * `accounts_employee` (Read)
  * `accounts_laundrymartstore` (Read)
  * `accounts_user` (Read, Update)

---

### 2.4 Password Management & Recovery

#### `POST /accounts/api/forget-password`
* **Handler**: `forget_password_otp`
* **Permissions**: `AllowAny`
* **Description**: Generates an OTP with 1-minute validity for active users to reset password.
* **DB Tables Used**:
  * `accounts_user` (Read, Update)

#### `PATCH /accounts/api/change-password`
* **Handler**: `ChangePasswordAPIView`
* **Permissions**: `IsAuthenticated`
* **Description**: Sets a new password for the authenticated user without requiring the current password (used after OTP validation).
* **DB Tables Used**:
  * `accounts_user` (Read, Update)

#### `PATCH /accounts/api/change-current-password`
* **Handler**: `change_current_password`
* **Permissions**: `IsAuthenticated`
* **Description**: Validates `current_password` and updates to `new_password`.
* **DB Tables Used**:
  * `accounts_user` (Read, Update)

---

### 2.5 Profiles & Settings

#### `GET` / `PATCH /accounts/api/customer-profile`
* **Handler**: `CustomerProfileAPIView`
* **Permissions**: `IsCustomer`
* **Description**: Retrieves or updates customer personal details, address, avatar, and delivery preference.
* **DB Tables Used**:
  * `accounts_user` (Read, Update)

#### `GET` / `PATCH /accounts/api/vendor-profile`
* **Handler**: `VendorProfileAPIView`
* **Permissions**: `IsEmployee`
* **Description**: Retrieves or updates store details, pricing per pound, service fees, operating hours for each day, and turnaround times.
* **DB Tables Used**:
  * `accounts_laundrymartstore` (Read, Update)
  * `accounts_employee` (Read)

#### `GET` / `PATCH /accounts/api/manage-customer-setting`
* **Handler**: `ManageCustomerSettingsAPIView`
* **Permissions**: `IsCustomer`
* **Description**: Toggles notification alerts and customer order dispatch preferences (`Auto-assign another LaundryMart (fastest)` vs `Ask me to choose`).
* **DB Tables Used**:
  * `accounts_user` (Read, Update)

#### `GET` / `PATCH /accounts/api/manage-vendor-setting`
* **Handler**: `ManageVendorSettingsAPIView`
* **Permissions**: `IsEmployee`
* **Description**: Manages vendor preferences (`push_and_email_alerts`, `auto_accept_orders`, `employee_edit_permission`). Restricts updates if employee is in the `employee_without_edit_permission` group.
* **DB Tables Used**:
  * `accounts_laundrymartstore` (Read, Update)

#### `DELETE /accounts/api/delete-account`
* **Handler**: `delete_account`
* **Permissions**: `IsAuthenticated`
* **Description**: Deletes the authenticated user account and cascades deletions to owned relations.
* **DB Tables Used**:
  * `accounts_user` (Delete)

#### `GET /accounts/api/admin/my-profile/`
* **Handler**: `my_admin_profile`
* **Permissions**: Staff only
* **Description**: Redirects authenticated staff members to their change profile page in Django Admin.

---

### 2.6 Location Management (Mounted under `/customers/api/`)

#### `POST` / `GET /customers/api/locations`
* **Handler**: `SecondaryLocationAPIView`
* **Permissions**: `IsCustomer`
* **Description**: Creates or lists secondary locations (e.g. Work, Gym) alongside the primary Home address from the user profile.
* **DB Tables Used**:
  * `accounts_secondarylocation` (Read, Insert)
  * `accounts_user` (Read)

#### `PATCH` / `DELETE /customers/api/location/<int:pk>` & `PATCH /customers/api/location`
* **Handler**: `SecondaryLocationModifyAPIView`
* **Permissions**: `IsCustomer`
* **Description**: Updates or deletes a secondary location. If `<int:pk>` is omitted in `PATCH`, updates the primary location on `User`.
* **DB Tables Used**:
  * `accounts_secondarylocation` (Read, Update, Delete)
  * `accounts_user` (Read, Update)

---

## 3. Background Tasks & Fallback Logic

While the `accounts` module does not define Celery `@shared_task` workers directly, it integrates with asynchronous communication utilities:

* **OTP Delivery Fallback**:
  * Flow: In `RegisterView`, `ResendOTPView`, and `forget_password_otp`, delivery method is determined dynamically:
    1. Checks if `user.email` is present → calls `send_otp_for_email_verification` or `send_otp_for_password`.
    2. If email is absent or fails, falls back to `user.phone_number` → calls `send_otp_for_sms_verification` or `send_otp_for_sms_password`.
* **Store Reverse-Geocoding**:
  * When `LaundrymartStore` is saved with `location_map` or latitude/longitude, `reverse_geocode_google(lat, lng)` is executed synchronously to enrich the text `location` address.
  * Fallback: If the Google Geocoding API fails or coordinates are invalid, exception is swallowed gracefully without disrupting the store save.
