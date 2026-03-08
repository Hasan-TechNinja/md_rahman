from django.contrib import admin
from django.contrib.admin import DateFieldListFilter, SimpleListFilter
from django.db.models import Q
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from django.utils.translation import gettext_lazy as _
from unfold.contrib.filters.admin import ChoicesDropdownFilter, RangeDateTimeFilter
from unfold.decorators import display

from payment.models import Order, OrderProgression, Payment, PendingStripeOrder
from uber.admin import ManifestItemInline
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
class SimplifiedStatusFilter(SimpleListFilter):
  """
  Custom filter that groups many statuses into: Processing, Ready, Completed, Wait for support
  """
  title = 'Status Group'
  parameter_name = 'status_group'

  def lookups(self, request, model_admin):
    return (
      ('processing', 'Processing'),
      ('ready', 'Ready for pickup / return'),
      ('completed', 'Completed'),
      ('wait_support_or_canceled', 'Wait for support / Canceled'),
    )

  def queryset(self, request, queryset):
    if self.value() is None:
      return queryset

    # You can override get_service_type() if needed, but here we use a safe fallback
    def get_service_type(obj):
      try:
        # Assuming your get_service_type() method exists and returns display value
        return obj.get_service_type()
      except Exception:
        return None

    val = self.value()

    if val == 'processing':
      exclude = {'completed', 'canceled', 'wait_for_support',
                 'picked_up_by_customer', 'dropping_of_soon'}  # add more final states if needed

      # Most statuses are processing by default
      return queryset.exclude(status__in=exclude)

    elif val == 'ready':
      # "Ready" depends on service type
      qs_full_or_pickup = queryset.filter(
        status='return_scheduled',
      ).filter(  # optional: ensure it's full_service or pickup
        # You can improve this condition later if needed
      )

      qs_dropoff = queryset.filter(
        status__in=['arrived_at_laundry', 'weighed', 'charged']
      )

      # Combine both
      return qs_full_or_pickup | qs_dropoff

    elif val == 'completed':
      return queryset.filter(status='completed')

    elif val == 'wait_support_or_canceled':
      return queryset.filter(status__in=['wait_for_support', 'canceled'])

    return queryset

@admin.register(Order)
class OrderAdmin(ModelAdmin):

    def get_list_display(self, request):
      is_superuser = request.user.is_superuser
      display = []

      if is_superuser:
        # superuser sees real status instead of vendor display
        display = ['uuid', 'user', 'service_provider', 'status',
                   'created_at', 'updated_at', 'estimated_value',
                   'final_total_cents', ]
      elif request.user.is_staff and not request.user.is_superuser:
        display = ['uuid', 'user', 'service_provider', 'vendor_status_display',
                   'created_at', 'updated_at', 'estimated_value',
                   'final_total_cents', ]
      return display

    list_display_links = ('uuid',)

    # list_filter = (
    #     SimplifiedStatusFilter,
    #     ('created_at', DateFieldListFilter),
    #     ('created_at', RangeDateTimeFilter),
    # )
    def get_list_filter(self, request):
      if request.user.is_superuser:
          filters = (
              'status',
              ('created_at', DateFieldListFilter),
              ('created_at', RangeDateTimeFilter),
          )

      elif request.user.is_staff and not request.user.is_superuser:
          filters = (
              SimplifiedStatusFilter,
              ('created_at', DateFieldListFilter),
              ('created_at', RangeDateTimeFilter),
          )
      return filters
    search_fields = (
        'uuid',
        'user__full_name',
        'user__email',
        'service_provider__laundrymart_name',
    )
    date_hierarchy = 'created_at'
    show_facets = admin.ShowFacets.ALWAYS
    list_filter_sheet = False
    list_filter_submit = True
    def get_readonly_fields(self, request, obj=None):
        always_readonly = [
            'created_at',
            'updated_at',
            'uuid'
        ]



        if request.user.is_superuser or getattr(request.user, 'is_hijacked', False):
            return always_readonly

        return always_readonly

    # ────────────────────────────────────────────────
    #  The important change is here
    # ────────────────────────────────────────────────
    def get_fieldsets(self, request, obj=None):
        is_super = request.user.is_superuser or getattr(request.user, 'is_hijacked', False)

        # Choose which status field to show
        status_field = "status" if is_super else "vendor_status_display"

        fieldsets = (
            (
                'Basic Info',
                {
                    "classes": ["tab"],
                    "fields": [
                        "uuid",
                        "user",
                        "service_provider",
                        status_field,           # ← dynamic choice
                    ],
                },
            ),
            (
                _("Address Information"),
                {
                    "classes": ["tab"],
                    "fields": [
                        "pickup_address",
                        "dropoff_address",
                        "pickup_latitude",
                        "pickup_longitude",
                        "dropoff_latitude",
                        "dropoff_longitude",
                        "customer_note",
                    ],
                },
            ),
            (
                _("Uber Tracking"),
                {
                    "classes": ["tab"],
                    "fields": [
                        "uber_pickup_quote_id",
                        "uber_pickup_delivery_id",
                        "uber_return_quote_id",
                        "uber_parent_delivery_id",
                        "uber_return_delivery_id",
                    ],
                },
            ),
            (
                _("Stripe Information"),
                {
                    "classes": ["tab"],
                    "fields": [
                        "stripe_customer_id",
                        "stripe_default_pm_id",
                    ],
                },
            ),
            (
                _("Pricing Information"),
                {
                    "classes": ["tab"],
                    "fields": [
                        "insurance_amount",
                        "estimated_value",
                        "weight_in_pounds",
                        "service_charge_cents",
                        "delivery_fee_cents",
                        "final_total_cents",
                    ],
                },
            ),
            (
                _("Timestamps"),
                {
                    "classes": ["tab"],
                    "fields": ["created_at", "updated_at"],
                },
            ),
        )

        return fieldsets

    # ────────────────────────────────────────────────
    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser or getattr(request.user, 'is_hijacked', False):
            return True
        return super().has_change_permission(request, obj)


    @admin.display(description='Status', ordering='status')
    def vendor_status_display(self, obj):
        status = obj.status or ''

        if status == 'completed':
            badge = 'success'
            label = 'Completed'
        elif status in ('wait_for_support', 'canceled'):
            badge = 'danger'
            label = 'Needs Attention' if status == 'wait_for_support' else 'Canceled'
        elif status == 'return_scheduled':
            badge = 'primary'
            label = 'Ready for Return'
        elif status in ('arrived_at_laundry', 'weighed', 'charged'):
            badge = 'info'
            label = 'Ready at Laundry'
        else:
            badge = 'warning'
            label = 'Processing'

        return format_html(
            '<span class="badge bg-{}">{}</span>',
            badge,
            label
        )

    inlines = [OrderProgressionInline, ManifestItemInline]

    readonly_fields = (
        "uuid",
        "created_at",
        "updated_at",
        "stripe_customer_id",
        "stripe_default_pm_id",
        "uber_pickup_quote_id",
        "uber_pickup_delivery_id",
        "uber_return_quote_id",
        "uber_parent_delivery_id",
        "uber_return_delivery_id",
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_staff and not request.user.is_superuser:
            qs = qs.filter(service_provider__admin=request.user)
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
