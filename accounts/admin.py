from django import forms
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin, TabularInline

from .models import Employee, LaundrymartStore, Service, User
from .utils import reverse_geocode_google


# Register your models here.
@admin.register(User)
class UserAdmin(ModelAdmin):
    list_display = ('email', 'first_name', 'is_staff', 'is_active')
    search_fields = ('email', 'first_name',)


    # Restrict access to users based on whether they are superusers
    def get_search_fields(self, request):
        if request.user.is_staff and not request.user.is_superuser:
            return []  # Return an empty list to disable search fields
        return self.search_fields  # Use the default search fields for superusers
    def get_queryset(self, request):
        """
        Limit the queryset based on the user. If the user is not a superuser, only show their own user record.
        """
        queryset = super().get_queryset(request)
        if not request.user.is_superuser:
            # Only show the current user's record
            queryset = queryset.filter(id=request.user.id)
        return queryset

    def has_change_permission(self, request, obj=None):
        """
        Allow change permission only for the user's own data if they are not a superuser.
        """
        if not request.user.is_superuser:
            # Staff (non-superuser) can only change their own user entity
            if obj and obj == request.user:
                return True
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        """
        Allow delete permission only for the user's own data if they are not a superuser.
        """
        if not request.user.is_superuser:
            # Staff (non-superuser) can only delete their own user entity
            if obj and obj == request.user:
                return True
            return False
        return super().has_delete_permission(request, obj)

    def has_add_permission(self, request):
        # Allow staff to add stores if they're not a superuser
        if request.user.is_staff and not request.user.is_superuser:
            return False
        return super().has_add_permission(request)

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = [
        ]

        if not request.user.is_superuser:
            # Add location-related fields to readonly list for non-superusers
            readonly_fields.extend([
                'location', 'lat', 'lng', 'secondary_location',
                'secondary_lat', 'secondary_lng', 'is_active', 'otp', 'otp_expires',
                'is_verified', 'is_tester', 'push_and_email_alerts', 'approved_by_admin',
                'preference', 'stripe_customer_id', 'groups', 'user_permissions',
                'stripe_customer_id', 'password', 'is_superuser',
                'is_staff', 'groups', 'user_permissions', 'last_login','date_joined'
            ])

        return readonly_fields

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)

        if not request.user.is_superuser:
            # Remove location-related fields from the fieldsets for non-superusers
            fieldsets = [
                (title, {**options, 'fields': tuple(
                    f for f in options['fields'] if
                    f not in ['location', 'lat', 'lng', 'secondary_location', 'secondary_lat', 'secondary_lng',
                              'is_active', 'is_verified', 'is_tester', 'push_and_email_alerts',
                              'approved_by_admin', 'preference', 'stripe_customer_id', 'password', 'is_superuser',
                              'is_staff', 'groups', 'user_permissions', 'last_login', ]
                )})
                for title, options in fieldsets
            ]

        return fieldsets


admin.site.register(Service)

class ServiceInline(TabularInline):
    model = Service
    extra = 1  # Number of empty forms to display by default
    fields = ('service_name', 'price_per_pound', 'image')  # Fields to display in the inline form


class LaundrymartStoreAdmin(ModelAdmin):
    list_display = ('laundrymart_name', 'store_id', 'phone_number', 'price_per_pound', 'service_fee')

    def get_readonly_fields(self, request, obj=None):
        """
        Make store_id + coordinate/location fields readonly for staff users,
        but fully editable for superusers.
        """
        readonly = ['store_id','location','lat','lng','secondary_location',
                    'secondary_lat','secondary_lng']

        if request.user.is_superuser:
            # Superusers can edit everything → return empty list
            return []

        # Staff (non-superuser) → apply readonly
        return readonly
    fieldsets = (
        ('Store Profile', {
            'classes': ('collapse',),
            'fields': (
                'admin',
                'laundrymart_name',
                'stripe_customer_id',
                'store_id',
                'phone_number',
                'vendor_description',
            ),
        }),
        ('Images & Branding', {
            'classes': ('collapse',),
            'fields': (
                'laundrymart_logo',
                'image',
            ),
        }),
        ('Pricing', {
            'classes': ('collapse',),
            'fields': (
                'price_per_pound',
                'service_fee',
                'service_fee_percentage',
                'minimum_order_weight',
                'daily_capacity_limit',
            ),
        }),
        ('Primary Location', {
            'classes': ('collapse',),
            'fields': (
                'location',
                'location_map',
            ),
            'description': _('Use the map to set or adjust the primary location.'),
        }),
        ('Secondary Location (optional)', {
            'classes': ('collapse',),  # collapsed by default
            'fields': (
                'secondary_location',
                'secondary_lat',
                'secondary_lng',
            ),
        }),
        ('Turnaround Time (days)', {
            'classes': ('collapse',),
            'fields': (
                ('turnaround_time_minimum_sunday', 'turnaround_time_maximum_sunday'),
                ('turnaround_time_minimum_monday', 'turnaround_time_maximum_monday'),
                ('turnaround_time_minimum_tuesday', 'turnaround_time_maximum_tuesday'),
                ('turnaround_time_minimum_wednesday', 'turnaround_time_maximum_wednesday'),
                ('turnaround_time_minimum_thursday', 'turnaround_time_maximum_thursday'),
                ('turnaround_time_minimum_friday', 'turnaround_time_maximum_friday'),
                ('turnaround_time_minimum_saturday', 'turnaround_time_maximum_saturday'),
            ),
        }),
        ('Operating Hours', {
            'classes': ('collapse',),
            'fields': (
                ('operating_hours_start_sunday', 'operating_hours_end_sunday', 'is_closed_sunday'),
                ('operating_hours_start_monday', 'operating_hours_end_monday', 'is_closed_monday'),
                ('operating_hours_start_tuesday', 'operating_hours_end_tuesday', 'is_closed_tuesday'),
                ('operating_hours_start_wednesday', 'operating_hours_end_wednesday', 'is_closed_wednesday'),
                ('operating_hours_start_thursday', 'operating_hours_end_thursday', 'is_closed_thursday'),
                ('operating_hours_start_friday', 'operating_hours_end_friday', 'is_closed_friday'),
                ('operating_hours_start_saturday', 'operating_hours_end_saturday', 'is_closed_saturday'),
            ),
        }),
        ('Order & Notification Settings', {
            'classes': ('collapse',),
            'fields': (
                'push_and_email_alerts',
                'auto_accept_orders',
                'employee_edit_permission'
            ),
        }),
    )
    inlines = [ServiceInline]

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

