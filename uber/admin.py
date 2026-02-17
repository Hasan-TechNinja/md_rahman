from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import ChoicesDropdownFilter, DropdownFilter, RangeDateTimeFilter
from unfold.contrib.inlines.admin import NonrelatedTabularInline

from accounts.models import LaundrymartStore
from payment.models import Order
from uber.models import Delivery, DeliveryQuote, ManifestItem
from django.utils.translation import gettext_lazy as _
# Register your models here.
admin.site.register(Delivery)

class ManifestItemInline(TabularInline):
    model = ManifestItem
    extra = 0
    fields = ('size','quantity','weight','price','vat_percentage','dimensions',)
    readonly_fields = ('quantity', 'size', 'weight', 'price')  # adjust based on your needs
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
            qs = qs.filter(delivery_quote=obj)
        return qs


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
        print(obj.quote_id)

        # Optimized query - use the indexed field
        print(Order.objects.filter(uber_pickup_quote_id=obj.quote_id))
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
    list_display = ('external_store_id','manifest_total_value',
                    'currency','saved_at',
                    )
    list_display_links = ('external_store_id',)
    show_facets = admin.ShowFacets.ALWAYS
    list_filter_sheet=False
    list_filter_submit = True

    list_filter = (('saved_at', admin.DateFieldListFilter),
                   ('saved_at', RangeDateTimeFilter),
                   )

    search_fields = ('quote_id','external_store_id','customer__email',
                     'customer__phone_number','customer__full_name',
                     'pickup_address','dropoff_address',)

    date_hierarchy = 'saved_at'

    readonly_fields = ('quote_id','fee','currency','currency_type',
                       'duration','pickup_duration','dropoff_eta','pickup_ready_dt',
                       'dropoff_deadline','created','expires','saved_at','validation_status',
                       'validation_pi_id','validation_amount_cents',
                       )

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
            # print("Filtering for store_ids:", store_ids)   # ← temporary debug

            # qs = qs.filter(external_store_id__in=store_ids)

        return qs.select_related('customer')
class ManifestItemAdmin(admin.ModelAdmin):
    search_fields = ('delivery_quote__quote_id',)
admin.site.register(ManifestItem, ManifestItemAdmin)

