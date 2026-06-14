from django import forms
from django.contrib import admin
from django.contrib.auth.admin import GroupAdmin
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from hijack.contrib.admin import HijackUserAdminMixin
from unfold.admin import ModelAdmin, TabularInline
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from admin_panel.admin import tab_description
from laundrymart import settings
from payment.models import Order
from .models import CustomerProxy, Employee, LaundrymartStore, Service, StaffProxy, User, VendorProxy
from .utils import reverse_geocode_google


# Register your models here.
@admin.register(User)
class UserAdmin(ModelAdmin):
    list_display = ('email', 'first_name', 'is_staff', 'is_active')
    search_fields = ('email', 'first_name','phone_number')
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    vendor_subscription_fields = ['stripe_connect_account_id','stripe_connect_account_status']
    customer_subscription_fields = ['stripe_customer_id']


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
                'location', 'lat', 'lng', 'secondary_location', 'email'
                'secondary_lat', 'secondary_lng', 'is_active', 'otp', 'otp_expires',
                'is_verified', 'is_tester', 'push_and_email_alerts', 'approved_by_admin',
                'preference', 'stripe_customer_id', 'groups', 'user_permissions',
                'stripe_customer_id', 'is_superuser', 'stripe_connect_account_status',
                'is_staff', 'groups', 'user_permissions', 'last_login','date_joined',
                'stripe_connect_account_id'
            ])

        return readonly_fields

    fieldsets = (
    ('Account',{
        "classes":["tab"],
        "fields":[
            'first_name', 'last_name', 'email', 'phone_number',

        ]
    }),
    ('Profile',{
        "classes":["tab"],
        "fields":[
            'full_name','image','password'

        ]
    }),
    ('Settings',{
        "classes":["tab"],
        "fields":[
            'push_and_email_alerts','is_tester','preference'

        ]
    }),
    ('Address',{
        "classes":["tab"],
        "fields":[
            'location','lat','lng',
            'secondary_location', 'secondary_lat', 'secondary_lng'

        ]
    }),
    ('Subscription info',{
        "classes":["tab"],
        "fields":[
            'stripe_customer_id','stripe_connect_account_id','stripe_connect_account_status'

        ]
    }),
    ('Otp For verification',{
        "classes":["tab"],
        "fields":[
            'otp','otp_expires',

        ]
    }),
    )

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

        # ───────────────────────────────────────────────
        # Dynamic subscription fields – only applied when editing an existing user
        # ───────────────────────────────────────────────
        if obj is not None:  # we're in change view (not add view)
            # Decide which subscription fields to show
            # Adjust this condition to match how you actually distinguish vendors
            if getattr(obj, 'stripe_connect_account_id', None):  # ← most common check
                subscription_fields = [
                    'stripe_connect_account_id',
                    'stripe_connect_account_status',
                    # 'stripe_customer_id',          # ← uncomment if you want to show both
                ]
            else:
                subscription_fields = [
                    'stripe_customer_id',
                ]

            # Rebuild fieldsets, replacing only the "Subscription info" section
            new_fieldsets = []
            for title, options in fieldsets:
                if title == 'Subscription info':
                    if subscription_fields:  # don't show empty tab
                        new_fieldsets.append(
                            ('Subscription info', {
                                "classes": ["tab"],
                                "fields": subscription_fields
                            })
                        )
                    # else → we skip it completely if no fields apply
                else:
                    new_fieldsets.append((title, options))

            fieldsets = tuple(new_fieldsets)

        return fieldsets


@admin.register(Service)
class ServiceAdmin(ModelAdmin):
    pass


class ServiceInline(TabularInline):
    model = Service
    extra = 1  # Number of empty forms to display by default
    fields = ('service_name', 'price_per_pound', 'image')  # Fields to display in the inline form
    tab=True

class OrderInline(TabularInline):
    model=Order

class LaundrymartStoreAdminForm(forms.ModelForm):
  location_search = forms.CharField(
    label="Search Primary Location (Google Places)",
    required=False,
    widget=forms.TextInput(attrs={
      'class': 'google-places-autocomplete w-full p-2 rounded border border-gray-300',
      'placeholder': 'Start typing an address...'
    })
  )

  class Meta:
    model = LaundrymartStore
    fields = "__all__"

  class Media:
    js = (
      'js/store_hours_timezone.js',
    )

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)

    operating_fields = [
      f for f in self.fields
      if f.startswith("operating_hours_start_")
      or f.startswith("operating_hours_end_")
    ]

    for field in operating_fields:
      self.fields[field].input_formats = [
        "%I:%M %p",
        "%H:%M",
        "%H:%M:%S"
      ]

      self.fields[field].widget = forms.TimeInput(
        format="%I:%M %p",
        attrs={
          "type": "text",
          "class": (
            "operating-hours-field "
            "w-full p-2 rounded border border-gray-300"
          ),
          "placeholder": "02:30 PM"
        }
      )

class LaundrymartStoreAdmin(ModelAdmin):
    list_display = ('laundrymart_name', 'store_id', 'phone_number', 'price_per_pound', 'service_fee')
    form = LaundrymartStoreAdminForm

    class Media:
        # Load the Google Maps API and our custom JavaScript file
        js = (
            f'https://maps.googleapis.com/maps/api/js?key={settings.GOOGLE_MAP_API_KEY}&loading=async&libraries=places',
            'js/google_autocomplete.js',
        )

    def get_readonly_fields(self, request, obj=None):
        """
        Make store_id + coordinate/location fields readonly for staff users,
        but fully editable for superusers.
        """
        readonly = ['store_id','location','lat','lng','google_rating','secondary_location',
                    'secondary_lat','secondary_lng', 'stripe_customer_id', 'google_rating']

        if request.user.is_superuser or getattr(request.user, 'is_hijacked', False):
            # Superusers can edit everything → return empty list
            return []

        # Staff (non-superuser) → apply readonly
        return readonly
    fieldsets = (
        ('Store Profile', {
            'classes': ('tab',),
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
            'classes': ('tab',),
            'fields': (
                'laundrymart_logo',
                'image',
            ),
        }),
        ('Pricing', {
            'classes': ('tab',),
            'fields': (
                'price_per_pound',
                'service_fee',
                'service_fee_percentage',
                'minimum_order_weight',
                'daily_capacity_limit',
                'stripe_connect_status'
            ),
        }),
        ('Secondary Location (optional)', {
            'classes': ('tab',),  # tabd by default
            'fields': (
                'secondary_location',
                'secondary_lat',
                'secondary_lng',
            ),
        }),
        ('Turnaround Time (days)', {
            'classes': ('tab',),
            'description': tab_description("Provide the input in hours"),
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
            'classes': ('tab',),
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
            'classes': ('tab',),
            'fields': (
                'push_and_email_alerts',
                'auto_accept_orders',
                'employee_edit_permission'
            ),
        }),
        ('Primary Location', {
            #'classes': ('collapse',),
            'fields': (
                'location_search',
                'location',
                'location_map',
                'google_rating'
            ),
            'description': _('Use the map to set or adjust the primary location.'),
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
    def save_model(self, request, obj, form, change):
        # If creating a new object AND user is staff (not superuser)
        if not change and request.user.is_staff and not request.user.is_superuser:
            obj.admin = request.user

        super().save_model(request, obj, form, change)


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

@admin.register(CustomerProxy)
class CustomerProxyAdmin(ModelAdmin):
    list_display = ('email', 'full_name', )
    search_fields = ('email', 'full_name', )
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        # Filter the queryset to only include users who are not staff (i.e., customers)
        return queryset.filter(is_staff=False)

    fieldsets = UserAdmin.fieldsets

@admin.register(VendorProxy)
class VendorProxyAdmin(HijackUserAdminMixin,ModelAdmin):
    list_display = ('id','email', 'full_name')
    search_fields = ('email', 'full_name')

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        # Filter the queryset to only include users who are not staff (i.e., customers)
        return queryset.filter(is_staff=True, is_superuser=False)

    fieldsets = UserAdmin.fieldsets
@admin.register(StaffProxy)
class StaffProxyAdmin(ModelAdmin):
    list_display = ('email', 'full_name' )
    search_fields = ('email', 'full_name')
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        # Filter the queryset to only include users who are not staff (i.e., customers)
        return queryset.filter(is_superuser=True)

    fieldsets = UserAdmin.fieldsets
