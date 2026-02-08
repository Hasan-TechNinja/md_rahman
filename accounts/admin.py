from django import forms
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.forms import ModelForm
from unfold.admin import ModelAdmin

from .models import Employee, LaundrymartStore, Service, User
from .utils import reverse_geocode_google


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
        form_class = super().get_form(request, obj, **kwargs)

        if request.user.is_authenticated and not request.user.is_superuser:
            # Filter stores based on the logged-in user (assumes a 'admin' relationship)
            store = LaundrymartStore.objects.filter(admin=request.user).first()

            if store:
                # Filter the queryset for the 'laundrymart_store' field based on the user's store
                form_class.base_fields['laundrymart_store'].queryset = LaundrymartStore.objects.filter(id=store.id)

                # Optionally, set the initial value for the store field (pre-select it)
                if obj is None:  # new object
                    form_class.base_fields['laundrymart_store'].initial = store

        return form_class

    def get_queryset(self, request):
        # Start with the default queryset
        queryset = super().get_queryset(request)

        # Restrict queryset based on the current user's assigned LaundrymartStore
        if request.user.is_authenticated and not request.user.is_superuser:
            store = LaundrymartStore.objects.filter(admin=request.user).first()
            if store:
                # Filter employees based on the laundrymart_store they are associated with
                queryset = queryset.filter(laundrymart_store=store)

        return queryset

admin.site.register(Employee, EmployeeAdmin)
admin.site.unregister(Group)

@admin.register(Group)
class GroupAdmin(GroupAdmin, ModelAdmin):
    pass

