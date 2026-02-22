
from django.urls import path
from . import views
from rest_framework_simplejwt.views import (
    TokenRefreshView,
)

from .views import EmployeeLoginOTP, LoginView, ManageCustomerSettingsAPIView, ManageVendorSettingsAPIView, \
  VerifyEmployeeOTP, VerifyOTPView, ResendOTPView, \
  change_current_password, \
  delete_account, \
  forget_password_otp, \
  ChangePasswordAPIView, my_admin_profile

urlpatterns = [
    path('login', LoginView.as_view(), name='token_obtain_pair'),
    path('employee-login', EmployeeLoginOTP.as_view(), name='employee_login'),
    path('employee-otp', VerifyEmployeeOTP.as_view(), name='verify_employee_otp'),
    path('token/refresh', TokenRefreshView.as_view(), name='token_refresh'),
    path('verify-otp', VerifyOTPView.as_view(), name='verify_otp'),
    path('resend-otp', ResendOTPView.as_view(), name='resend_otp'),
    path('forget-password', forget_password_otp, name='forget_password'),
    path('change-password', ChangePasswordAPIView.as_view(), name='password_change'),
    path('change-current-password', change_current_password, name='change_current_password'),
    path('customer-profile', views.CustomerProfileAPIView.as_view(), name='customer_profile'),
    path('vendor-profile', views.VendorProfileAPIView.as_view(), name='vendor_profile'),
    path('delete-account', delete_account, name='delete_account'),
    path('admin/my-profile/', my_admin_profile, name='admin_my_profile'),

    path('manage-vendor-setting', ManageVendorSettingsAPIView.as_view(), name='manage_vendor_setting'),
    path('manage-customer-setting', ManageCustomerSettingsAPIView.as_view(), name='manage_customer_setting'),

    path('register', views.RegisterView.as_view(), name='register'),
    path('logout', views.LogoutAPIView.as_view(), name='logout'),
]