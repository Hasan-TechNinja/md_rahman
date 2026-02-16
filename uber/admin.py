from django.contrib import admin
from unfold.admin import ModelAdmin

from accounts.models import LaundrymartStore
from uber.models import Delivery, DeliveryQuote, ManifestItem
from django.utils.translation import gettext_lazy as _
# Register your models here.
admin.site.register(Delivery)


@admin.register(DeliveryQuote)
class DeliveryQuoteAdmin(ModelAdmin):
    list_display = ('quote_id','service_type','status','fee',
                    'currency','external_store_id','saved_at',
                    )
    list_display_links = ('quote_id',)

    list_filter = ('service_type','status','validation_status',
                   'currency',('saved_at', admin.DateFieldListFilter),
                   ('expires', admin.DateFieldListFilter),
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

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Optional: restrict to user's related stores if needed (similar to Order)
        if request.user.is_staff and not request.user.is_superuser:
            qs = qs.filter(
                external_store_id__in=list(request.user.owned_stores.values_list('store_id', flat=True))
            )
            # store_ids = list(request.user.owned_stores.values_list('store_id', flat=True))
            # print("Filtering for store_ids:", store_ids)   # ← temporary debug

            # qs = qs.filter(external_store_id__in=store_ids)

        return qs.select_related('customer')
class ManifestItemAdmin(admin.ModelAdmin):
    search_fields = ('delivery_quote__quote_id',)
admin.site.register(ManifestItem, ManifestItemAdmin)

