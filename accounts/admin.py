from django import forms
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.forms import ModelForm
from unfold.admin import ModelAdmin

from .models import Employee, LaundrymartStore, Service, User
# Register your models here.

class UserAdmin(ModelAdmin):
    list_display = ('email', 'first_name', 'is_staff', 'is_active')
    search_fields = ('email', 'full_name',)
    
admin.site.register(User, UserAdmin)

admin.site.register(Service)


class LaundrymartStoreAdmin(ModelAdmin):
    list_display = ('laundrymart_name', 'store_id', 'phone_number', 'price_per_pound', 'service_fee')

    # Restrict access to laundrymart stores based on the user
    def get_queryset(self, request):
        """
        Override to limit the queryset based on the user.
        """
        queryset = super().get_queryset(request)

        if request.user.is_staff and not request.user.is_superuser:
            # Only show stores that the staff member is an admin of
            queryset = queryset.filter(admin=request.user)

        return queryset

    # Optionally, you can add custom logic for restricting access to the add/edit forms
    def has_add_permission(self, request):
        # Allow staff to add stores if they're not a superuser
        if request.user.is_staff and not request.user.is_superuser:
            return True
        return super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        # Allow staff to change only their own stores
        if request.user.is_staff and not request.user.is_superuser:
            if obj and obj.admin == request.user:
                return True
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        # Allow staff to delete only their own stores
        if request.user.is_staff and not request.user.is_superuser:
            if obj and obj.admin == request.user:
                return True
            return False
        return super().has_delete_permission(request, obj)


# Register the custom admin class
admin.site.register(LaundrymartStore, LaundrymartStoreAdmin)


class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # If the employee is being created (instance not saved yet), auto-fill the laundrymart_store for vendor admins
        if not self.instance.pk:
            if hasattr(self.instance, 'laundrymart_store') and self.instance.laundrymart_store is None:
                # If the user is a vendor admin, set the 'laundrymart_store' field
                if self.initial.get('laundrymart_store') is None and self.instance.laundrymart_store is None:
                    user = self.initial.get('user')  # The logged-in user
                    if user and user.is_authenticated and not user.is_superuser:
                        self.fields['laundrymart_store'].initial = LaundrymartStore.objects.filter(admin=user).first()
                        self.fields['laundrymart_store'].widget.attrs['readonly'] = True  # Make it read-only

    def clean(self):
        cleaned_data = super().clean()
        laundrymart_store = cleaned_data.get('laundrymart_store')

        # Check if the laundrymart_store has more than 3 employees
        if laundrymart_store:
            employee_count = laundrymart_store.employees.count()
            if employee_count >= 3:
                # Raise the validation error that will be caught by the form and shown in the admin panel
                raise ValidationError("This laundrymart can only have up to 3 employee accounts.")

        return cleaned_data



class EmployeeAdmin(ModelAdmin):
    form = EmployeeForm
    list_display = ('name', 'username', 'email', 'laundrymart_store')

    def get_form(self, request, obj=None, **kwargs):
        """
        Override get_form to customize form field for vendor admins.
        """
        form = super().get_form(request, obj, **kwargs)

        if request.user.is_authenticated and not request.user.is_superuser:
            # Automatically fill the 'laundrymart_store' field for vendor admins
            form.base_fields['laundrymart_store'].initial = LaundrymartStore.objects.filter(admin=request.user).first()
            form.base_fields['laundrymart_store'].widget.attrs['readonly'] = True  # Make it readonly for admins

        return form

admin.site.register(Employee, EmployeeAdmin)

