from django.contrib import admin
from django.db.models import Q
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import ChoicesDropdownFilter, DropdownFilter, RangeDateTimeFilter
from unfold.contrib.inlines.admin import NonrelatedTabularInline

from accounts.models import LaundrymartStore
from payment.models import Order
from uber.models import Delivery, DeliveryQuote, ManifestItem
from django.utils.translation import gettext_lazy as _
import logging
logger = logging.getLogger(__name__)
# Register your models here.
admin.site.register(Delivery)

class ManifestItemInline(TabularInline):
    model = ManifestItem
    extra = 0
    fields = ('size','quantity','weight','price','vat_percentage','dimensions',)
    #readonly_fields = ('quantity', 'size', 'weight', 'price')  # adjust based on your needs
    ordering = ('id',)
    show_change_link = False
    verbose_name_plural = _("Manifest Items")
    tab=True

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Important: only show manifest items linked to THIS DeliveryQuote
        # (since the model has multiple possible FKs, we must filter explicitly)
        obj = getattr(request, '_obj_for_inline', None)  # unfold/django trick for current object
        if obj:
            qs = qs.filter(Q(delivery_quote=obj) | Q(stripe_order=obj))
        return qs

    def has_change_permission(self, request, obj=None):
        """
        Allow changing manifest items when:
        - real superuser
        - hijacked session (support helping vendor)
        Otherwise fall back to normal group/object permissions
        """
        if request.user.is_superuser or getattr(request.user, 'is_hijacked', False):
            return True

        # Normal vendor/staff → use default permission check
        return super().has_change_permission(request, obj)

    def has_view_permission(self, request, obj=None):
        # Usually mirror change permission for inlines (or keep stricter)
        if request.user.is_superuser or getattr(request.user, 'is_hijacked', False):
            return True
        return super().has_view_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        """
        Protect calculated/sensitive fields for normal users,
        but allow editing most of them during support (superuser or hijacked).
        """
        always_readonly = [
            # These should almost never be manually changed
            # 'dimensions',  # if it's JSON computed elsewhere
        ]

        protected_fields = [
            'quantity',
            'size',
            'weight',
            'price',
            # 'vat_percentage',  # ← you can move to protected if support should edit it
            # 'dimensions',
        ]

        if request.user.is_superuser or getattr(request.user, 'is_hijacked', False):
            # Support session → only strictly system fields readonly
            return always_readonly

        # Normal vendor → keep your original protected fields readonly
        return always_readonly + protected_fields


class RelatedOrderInline(NonrelatedTabularInline):
    model = Order
    extra = 0
    max_num = 0                     # no "add another" button
    can_delete = False
    show_change_link = True         # optional: small view/change link per row

    fields = ('uuid_link', 'status', 'created_at')
    readonly_fields = ('uuid_link', 'status', 'created_at')

    verbose_name = "Related Order"
    verbose_name_plural = "Related Orders"
    tab=True

    # Required method for NonrelatedTabularInline / NonrelatedStackedInline
    def get_form_queryset(self, obj):
        """
        Return the queryset of Order objects related to this DeliveryQuote
        via the uber_pickup_quote_id field.
        """
        logger.info(obj.quote_id)

        # Optimized query - use the indexed field
        logger.info(Order.objects.filter(uber_pickup_quote_id=obj.quote_id))
        return Order.objects.filter(uber_pickup_quote_id=obj.quote_id)

    def save_new_instance(self, parent, instance):
        pass

    # Custom display method for clickable UUID
    @admin.display(description="Order UUID")
    def uuid_link(self, instance):
        if not instance.pk:
            return "—"
        url = f"/admin/payment/order/{instance.pk}/change/"
        return format_html(
            '<a href="{}" target="_blank">{}</a>',
            url,
            instance.uuid
        )



@admin.register(DeliveryQuote)
class DeliveryQuoteAdmin(ModelAdmin):
    list_display = ('quote_id','manifest_total_value','saved_at')
    list_display_links = ('quote_id',)
    show_facets = admin.ShowFacets.ALWAYS
    list_filter_sheet=False
    list_filter_submit = True

    list_filter = (
        ('saved_at', admin.DateFieldListFilter),
        ('saved_at', RangeDateTimeFilter),
    )

    search_fields = (
        'quote_id','external_store_id','customer__email',
        'customer__phone_number','customer__full_name',
        'pickup_address','dropoff_address',
    )

    date_hierarchy = 'saved_at'

    def has_change_permission(self, request, obj=None):
        # Allow change if:
        #   - real superuser (normal login)
        #   - this is a hijacked session (support helping vendor)
        if request.user.is_superuser or getattr(request.user, 'is_hijacked', False):
            return True

        # Otherwise fall back to normal permission checks
        # (group permissions, object-level perms, etc.)
        return super().has_change_permission(request, obj)

    def has_view_permission(self, request, obj=None):
        # Usually same logic as change — or keep stricter if you want
        if request.user.is_superuser or getattr(request.user, 'is_hijacked', False):
            return True
        return super().has_view_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        always_readonly = [
            'created',
            'expires',
            'saved_at',
        ]

        protected_fields = [
            'fee',
            'currency',
            'currency_type',
            'duration',
            'pickup_duration',
            'dropoff_eta',
            'pickup_ready_dt',
            'dropoff_deadline',
            'validation_status',
            'validation_pi_id',
            'validation_amount_cents',
        ]

        if request.user.is_superuser or getattr(request.user, 'is_hijacked', False):
            return always_readonly

        return always_readonly + protected_fields

    fieldsets = (
        (
            _("Basic Information"),
            {
                "classes": ["tab"],
                "fields": ["quote_id","service_type","status",
                           "customer","external_store_id","payment_method_id",
                           ],
            },
        ),
        (
            _("Addresses"),
            {
                "classes": ["tab"],
                "fields": ["pickup_address","pickup_latitude","pickup_longitude",
                           "pickup_phone_number","dropoff_address","dropoff_latitude",
                           "dropoff_longitude","dropoff_phone_number","customer_note",
                           ],
            },
        ),
        (
            _("Pricing & Insurance"),
            {
                "classes": ["tab"],
                "fields": [
                    "manifest_total_value",
                    "insurance_amount",
                    "fee",
                    "currency",
                    "currency_type",
                ],
            },
        ),
        (
            _("Validation & Payment"),
            {
                "classes": ["tab"],
                "fields": [
                    "validation_status",
                    "validation_pi_id",
                    "validation_amount_cents",
                ],
            },
        ),
        (
            _("Timings & ETA"),
            {
                "classes": ["tab"],
                "fields": [
                    "pickup_ready_dt",
                    "dropoff_eta",
                    "dropoff_deadline",
                    "duration",
                    "pickup_duration",
                ],
            },
        ),
        (
            _("Quote Lifecycle"),
            {
                "classes": ["tab"],
                "fields": [
                    "created",
                    "expires",
                    "saved_at",
                ],
            },
        ),
    )
    inlines = [ManifestItemInline,RelatedOrderInline ]
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Optional: restrict to user's related stores if needed (similar to Order)
        if request.user.is_staff and not request.user.is_superuser:
            qs = qs.filter(
                external_store_id__in=list(request.user.owned_stores.values_list('store_id', flat=True)), status='rejected'
            )
            # store_ids = list(request.user.owned_stores.values_list('store_id', flat=True))
            # logger.info("Filtering for store_ids:", store_ids)   # ← temporary debug

            # qs = qs.filter(external_store_id__in=store_ids)

        return qs.select_related('customer')
class ManifestItemAdmin(ModelAdmin):
    search_fields = ('delivery_quote__quote_id',)
admin.site.register(ManifestItem, ManifestItemAdmin)

