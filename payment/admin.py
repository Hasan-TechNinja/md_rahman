from django.contrib import admin
from django.contrib.admin import DateFieldListFilter, SimpleListFilter
from django.db.models import Q
from unfold.admin import ModelAdmin, TabularInline
from django.utils.translation import gettext_lazy as _
from unfold.contrib.filters.admin import ChoicesDropdownFilter, RangeDateTimeFilter
from unfold.decorators import display

from payment.models import Order, OrderProgression, Payment, PendingStripeOrder
from uber.models import Delivery, DeliveryQuote

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
      # Filter orders where the related DeliveryQuote has a service type of 'pickup'
      return queryset.filter(
        uber_pickup_quote_id__isnull=False,
        uber_pickup_quote_id__in=DeliveryQuote.objects.filter(service_type='pickup').values('quote_id')
      ).exclude(uber_pickup_quote_id='')

    elif self.value() == 'full_service':
      # Filter orders where the related DeliveryQuote has a service type of 'full_service'
      return queryset.filter(
        uber_pickup_quote_id__isnull=False
      ).exclude(uber_pickup_quote_id='').filter(
        uber_pickup_quote_id__in=DeliveryQuote.objects.filter(service_type='full_service').values('quote_id')
      )

    elif self.value() == 'drop_off':
      # Filter orders where the related DeliveryQuote has a service type of 'drop_off'
      return queryset.filter(
        uber_pickup_quote_id__isnull=False
      ).exclude(uber_pickup_quote_id='').filter(
        uber_pickup_quote_id__in=DeliveryQuote.objects.filter(service_type='drop_off').values('quote_id')
      )

    return queryset

class OrderProgressionInline(TabularInline):
  model = OrderProgression
  extra = 0
  fields = ('name', 'is_complete', 'sequence_no')
  ordering = ('sequence_no',)
  readonly_fields = ('name', 'sequence_no')
  tab=True

# @admin.register(OrderProgression)
# class OrderProgressionAdmin(ModelAdmin):
#   pass

@admin.register(Order)
class OrderAdmin(ModelAdmin):
  list_display = ('uuid','user','service_provider','status',
                  'created_at','updated_at',)
  list_display_links = ('uuid',)

  list_filter = (
    ('status',ChoicesDropdownFilter),
    ('created_at', DateFieldListFilter),
    ('created_at', RangeDateTimeFilter),
  )
  search_fields = ('uuid','user__full_name','user__email','service_provider__laundrymart_name',)
  date_hierarchy = 'created_at'
  show_facets = admin.ShowFacets.ALWAYS
  list_filter_sheet = False
  list_filter_submit = True
  fieldsets = (
    (
      'Basic Info',  # Default section without a title
      {
        "classes":["tab"],
        "fields": [
          "uuid", "user", "service_provider", "status",  # Main fields
        ],
      },
    ),
    (
      _("Address Information"),  # Tab title for Address
      {
        "classes": ["tab"],  # CSS class for tab styling
        "fields": [
          "pickup_address", "dropoff_address", "pickup_latitude", "pickup_longitude",
          "dropoff_latitude", "dropoff_longitude", "customer_note",
        ],
      },
    ),
    (
      _("Uber Tracking"),  # Tab title for Uber Tracking
      {
        "classes": ["tab"],  # CSS class for tab styling
        "fields": [
          "uber_pickup_quote_id", "uber_pickup_delivery_id", "uber_return_quote_id",
          "uber_parent_delivery_id", "uber_return_delivery_id",
        ],
      },
    ),
    (
      _("Stripe Information"),  # Tab title for Stripe
      {
        "classes": ["tab"],  # CSS class for tab styling
        "fields": [
          "stripe_customer_id", "stripe_default_pm_id",
        ],
      },
    ),
    (
      _("Pricing Information"),  # Tab title for Pricing
      {
        "classes": ["tab"],  # CSS class for tab styling
        "fields": [
          "insurance_amount", "weight_in_pounds", "service_charge_cents",
          "delivery_fee_cents", "final_total_cents",
        ],
      },
    ),
    (
      _("Timestamps"),  # Tab title for Timestamps
      {
        "classes": ["tab"],  # Optionally, collapse this section
        "fields": ["created_at", "updated_at"],
      },
    ),
  )
  inlines = [OrderProgressionInline]

  readonly_fields = (
    "uuid", "created_at", "updated_at",  # Make fields read-only
    "stripe_customer_id", "stripe_default_pm_id",
    "uber_pickup_quote_id", "uber_pickup_delivery_id",
    "uber_return_quote_id", "uber_parent_delivery_id", "uber_return_delivery_id",
  )

  def get_queryset(self, request):
    qs = super().get_queryset(request)
    if request.user.is_staff and not request.user.is_superuser:
      qs = qs.filter(service_provider__admin=request.user)  # Adjust if needed
    return qs.select_related('user', 'service_provider').prefetch_related('progressions')

  @admin.display(description='UUID')
  def uuid_link(self, obj):
    return obj.uuid

  def get_service_type_display(self, obj):
    try:
      return obj.get_service_type()
    except Exception:
      return "—"

  get_service_type_display.short_description = 'Service Type'