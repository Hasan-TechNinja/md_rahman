from django.contrib import admin
from django.contrib.admin import DateFieldListFilter, SimpleListFilter
from django.db.models import Q
from unfold.admin import ModelAdmin, TabularInline
from django.utils.translation import gettext_lazy as _
from unfold.decorators import display

from payment.models import Order, OrderProgression, Payment, PendingStripeOrder
from uber.models import Delivery

# Register your models here.
admin.site.register(Payment)
admin.site.register(PendingStripeOrder)


class ServiceTypeFilter(SimpleListFilter):
  title = _('Service Type')
  parameter_name = 'service_type'

  def lookups(self, request, model_admin):
    return (
      ('pickup', _('Pickup')),
      ('full_service', _('Full Service')),
      ('drop_off', _('Drop Off')),
    )

  def queryset(self, request, queryset):
    if self.value() == 'pickup':
      return queryset.filter(uber_pickup_quote_id__isnull=False).exclude(uber_pickup_quote_id='')
    elif self.value() == 'full_service':
      return queryset.filter(
        uber_pickup_quote_id__isnull=False,
        uber_return_quote_id__isnull=False
      ).exclude(uber_pickup_quote_id='', uber_return_quote_id='')
    elif self.value() == 'drop_off':
      return queryset.filter(uber_return_quote_id__isnull=False).exclude(uber_return_quote_id='')
    return queryset

class OrderProgressionInline(TabularInline):
  model = OrderProgression
  extra = 0
  fields = ('name', 'is_complete', 'sequence_no')
  ordering = ('sequence_no',)
  readonly_fields = ('name', 'sequence_no')

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
  list_display = (
    'uuid_link',
    'user',
    'service_provider',
    'status',
    'get_service_type_display',
    'created_at',
    'updated_at',
  )
  list_display_links = ('uuid_link',)
  list_filter = (
    'status',
    ServiceTypeFilter,
    ('created_at', DateFieldListFilter),
  )
  search_fields = (
    'uuid',
    'user__full_name',
    'user__email',
    'service_provider__laundrymart_name',
  )
  date_hierarchy = 'created_at'

  # Grouping fields in the admin form with fieldsets
  fieldsets = (
    ('Main Info', {
      'fields': ('uuid', 'user', 'service_provider', 'status'),
    }),
    ('Address Information', {
      'fields': (
        'pickup_address', 'dropoff_address', 'pickup_latitude', 'pickup_longitude',
        'dropoff_latitude', 'dropoff_longitude', 'customer_note'
      ),
    }),
    ('Uber Tracking', {
      'fields': (
        'uber_pickup_quote_id', 'uber_pickup_delivery_id', 'uber_return_quote_id',
        'uber_parent_delivery_id', 'uber_return_delivery_id',
      ),
    }),
    ('Stripe Information', {
      'fields': ('stripe_customer_id', 'stripe_default_pm_id'),
    }),
    ('Pricing Information', {
      'fields': (
        'insurance_amount', 'weight_in_pounds', 'service_charge_cents',
        'delivery_fee_cents', 'final_total_cents'
      ),
    }),
    ('Timestamps', {
      'fields': ('created_at', 'updated_at'),
      'classes': ('collapse',)  # Optionally, collapse the timestamps section
    }),
  )

  readonly_fields = (
    'uuid', 'created_at', 'updated_at',
    'stripe_customer_id', 'stripe_default_pm_id',
    'uber_pickup_quote_id', 'uber_pickup_delivery_id',
    'uber_return_quote_id', 'uber_parent_delivery_id', 'uber_return_delivery_id'
  )

  def get_queryset(self, request):
    qs = super().get_queryset(request)
    if request.user.is_staff and not request.user.is_superuser:
      qs = qs.filter(service_provider__admin=request.user)  # Adjust if needed
    return qs.select_related(
      'user', 'service_provider'
    ).prefetch_related('progressions')

  @admin.display(description='UUID')
  def uuid_link(self, obj):
    return obj.uuid

  def get_service_type_display(self, obj):
    try:
      return obj.get_service_type()
    except Exception:
      return "—"

  get_service_type_display.short_description = 'Service Type'
admin.site.register(OrderProgression)