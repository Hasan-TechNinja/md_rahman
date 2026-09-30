from django.core.exceptions import ObjectDoesNotExist
from rest_framework.permissions import BasePermission


class IsAdminUser(BasePermission):
    def has_permission(self, request, view):
        if not request.user:                    # ← changed
            return False
        return bool(
            hasattr(request.user, 'is_staff') and
            request.user.is_staff and
            hasattr(request.user, 'is_superuser') and
            request.user.is_superuser
        )


class IsStaff(BasePermission):
    def has_permission(self, request, view):
        if not request.user:                    # ← changed
            return False

        # Only regular User with is_staff (not Employee)
        return (
            hasattr(request.user, 'is_staff') and
            request.user.is_staff and
            not hasattr(request.user, 'laundrymart_store')  # exclude Employee
        )


class IsCustomer(BasePermission):
    def has_permission(self, request, view):
        if not request.user:                    # ← changed
            return False

        return (
            hasattr(request.user, 'is_staff') and
            not request.user.is_staff and
            not hasattr(request.user, 'laundrymart_store')  # exclude Employee
        )


class IsEmployee(BasePermission):
    message = "Only employees are allowed to access this endpoint."

    def has_permission(self, request, view):
        # Your original is already safe — no change needed here
        return hasattr(request, 'employee') and request.employee is not None