from decimal import Decimal

import humanize
from django.contrib import admin
from django.contrib.admin.views.main import ChangeList
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Count, Q
from django.urls import include, path, reverse
from django.utils import timezone
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from unfold.sites import UnfoldAdminSite

from accounts.models import LaundrymartStore
from customer.models import OrderReport, OrderReportImage
from payment.models import LaundrymartPaymentMethod, Order
from payment.views import AddPaymentMethodView, SetupIntentCreateView, SetupIntentSuccessView
from uber.models import DeliveryQuote
from vendor.models import OrderTrack, VendorDashboard
from vendor.views import DeletePaymentMethodView, PaymentMethodsView, SetDefaultPaymentMethodView

# Register your models here.


@admin.register(OrderTrack)
class OrderTrackAdmin(ModelAdmin):
    change_list_template = "admin_panels/vendor/ordertrack_custom_changelist.html"

@admin.register(LaundrymartPaymentMethod)   # ← pick any model that makes sense (or create a dummy model)
class VendorPaymentAdmin(ModelAdmin):
    # We only use this class to attach custom URLs — no change list needed

    def get_urls(self):
        urls = super().get_urls()

        custom_urls = [
            path(
                'vendor/payment-methods/',
                self.admin_site.admin_view(
                    PaymentMethodsView.as_view(model_admin=self)  # ← pass model_admin=self HERE
                ),
                name='vendor_payment_methods',
            ),
            path(
                'vendor/payment-methods/add/',
                self.admin_site.admin_view(
                    AddPaymentMethodView.as_view(model_admin=self)
                ),
                name='vendor_add_payment_method',
            ),
            path(
                'vendor/payment-methods/create-setup-intent/',
                self.admin_site.admin_view(
                    SetupIntentCreateView.as_view(model_admin=self)
                ),
                name='create_setup_intent',
            ),
            path(
                'vendor/payment-methods/delete/<int:pk>/',
                self.admin_site.admin_view(
                    DeletePaymentMethodView.as_view(model_admin=self)
                ),
                name='vendor_delete_payment_method',
            ),
            path(
                'vendor/payment-methods/setup-success/',
                SetupIntentSuccessView.as_view(),
                name='vendor_payment_method_setup_success',
            ),
        ]

        return custom_urls + urls


class OrderReportImageInline(TabularInline):
    model = OrderReportImage
    extra = 0

    # What fields to show
    fields = ('image', 'uploaded_at',)
    # Which ones are read-only
    readonly_fields = ('image', 'uploaded_at')

@admin.register(OrderReport)
class OrderReportAdmin(admin.ModelAdmin):
    list_display = ('user', 'order_link','order__service_provider', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__full_name', 'user__email', 'issue_description')
    readonly_fields = ('user', 'order_link', 'delivery_quote', 'created_at')
    fields = ('user', 'order_link', 'delivery_quote', 'created_at', 'issue_description')

    inlines = [OrderReportImageInline]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Apply service-provider restriction ONLY for non-superusers
        if not request.user.is_superuser:
            qs = qs.filter(order__service_provider__admin=request.user).exclude(order__isnull=True)

        return qs

    @admin.display(description="Order", ordering='order__id')
    def order_link(self, obj):
        if obj.order:
            url = reverse("admin:payment_order_change", args=(obj.order.id,))
            return format_html('<a href="{}">{}</a>', url, obj.order)
        return "—"  # this case should now never appear because of the exclude

@admin.register(VendorDashboard)
class VendorDashboardAdmin(ModelAdmin):
    change_list_template = "admin_panels/vendor/dashboard_custom_changelist.html"

    def changelist_view(self, request, extra_context=None):
        today = timezone.now().date()

        # ── Vendor-specific filtering ──
        laundry_marts = LaundrymartStore.objects.filter(admin=request.user)
        store_uids = laundry_marts.values_list('store_id', flat=True)

        print(store_uids)
        store_uids_str = [str(uid) for uid in store_uids]
        print("Trying with string UUIDs:", store_uids_str)
        print(DeliveryQuote.objects.filter(external_store_id__in=store_uids_str))

        # DeliveryQuote stats — only for stores this admin manages
        quote_stats = DeliveryQuote.objects.filter(
            external_store_id__in=store_uids_str,
            saved_at__date=today

        ).aggregate(
            total_quotes_today=Count('id'),
            pending_quotes=Count('id', filter=Q(status='pending')),
            rejected_quotes=Count('id', filter=Q(status='rejected')),
            delayed_quotes=Count('id', filter=Q(status='delayed')),
            draft_quotes=Count('id', filter=Q(status='draft')),
        )
        print(quote_stats)

        # Order stats — also scoped to the admin's laundry marts
        print('orders by the laundrymart', Order.objects.filter(service_provider__in=laundry_marts))
        order_stats = Order.objects.filter(
            service_provider__in=laundry_marts,  # assuming service_provider is ForeignKey to LaundrymartStore
            created_at__date=today
        ).aggregate(
            total_orders=Count('id'),
            pending_setup=Count('id', filter=Q(status='pending_setup')),
            processing=Count('id', filter=Q(status='processing')),
            in_progress=Count('pk', filter=Q(status__in=[
                'pickup_courier_scheduled', 'pickup_courier_assigned',
                'pickup_arriving_soon', 'picked_up_by_courier',
                'moving_towards_customer', 'moving_towards_laundrymart',
            ])),
            ready=Count('pk', filter=Q(status__in=[
                'arrived_at_laundry', 'received', 'weighed',
                'charged', 'processing_completion', 'completed',
            ])),
            order_delayed=Count('pk', filter=Q(status='wait_for_support')),
        )

        extra_context = extra_context or {}
        extra_context.update({
            'today_date': today,
            'quote_stats': quote_stats,
            'order_stats': order_stats,
            'store_count': laundry_marts.count(),  # optional — for display
        })

        return super().changelist_view(request, extra_context=extra_context)