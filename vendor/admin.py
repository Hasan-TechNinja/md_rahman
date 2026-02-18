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
from django.utils.translation import gettext_lazy as _

from accounts.models import LaundrymartStore
from customer.models import OrderReport, OrderReportImage
from messaging.models import VendorNotification
from payment.models import LaundrymartPaymentMethod, Order, SalesReport
from payment.views import AddPaymentMethodView, SetupIntentCreateView, SetupIntentSuccessView
from uber.models import DeliveryQuote
from vendor.models import OrderTrack, VendorDashboard
from vendor.views import DeletePaymentMethodView, PaymentMethodsView, ReportSalesSummaryView, \
    SetDefaultPaymentMethodView

# Register your models here.


@admin.register(OrderTrack)
class OrderTrackAdmin(ModelAdmin):
    change_list_template = "admin_panels/vendor/ordertrack_custom_changelist.html"

@admin.register(LaundrymartPaymentMethod)   # ← pick any model that makes sense (or create a dummy model)
class VendorAdmin(ModelAdmin):
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

@admin.register(SalesReport)
class SalesReportAdmin(ModelAdmin):
    def get_urls(self):
        urls = super().get_urls()
        custom_urls =[ path('sales-summary',
             self.admin_site.admin_view(
                 ReportSalesSummaryView.as_view(model_admin=self)
             ),
             name='vendor_sales_summary'
             )]

        return custom_urls + urls


class OrderReportImageInline(TabularInline):
    model = OrderReportImage
    extra = 0

    # What fields to show
    fields = ('image', 'uploaded_at',)
    # Which ones are read-only
    readonly_fields = ('image', 'uploaded_at')

@admin.register(OrderReport)
class OrderReportAdmin(ModelAdmin):
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

        store_uids = list(laundry_marts.values_list('store_id', flat=True))

        # DeliveryQuote stats
        quote_stats = DeliveryQuote.objects.filter(
            external_store_id__in=store_uids,  # works if external_store_id is CharField with str(uuid)
            saved_at__date=today
        ).aggregate(
            total_quotes_today=Count('id'),
            pending_quotes=Count('id', filter=Q(status='pending')),
            rejected_quotes=Count('id', filter=Q(status='rejected')),
            delayed_quotes=Count('id', filter=Q(status='delayed')),
            # draft_quotes=Count('id', filter=Q(status='draft')),  # uncomment if needed
        )

        # Order stats
        order_stats = Order.objects.filter(
            service_provider__in=laundry_marts,
            created_at__date=today
        ).aggregate(
            total_orders=Count('id'),
            pending_setup=Count('id', filter=Q(status='pending_setup')),
            processing=Count('id', filter=Q(status='processing')),
            in_progress=Count('id', filter=Q(status__in=[
                'pickup_courier_scheduled', 'pickup_courier_assigned',
                'pickup_arriving_soon', 'picked_up_by_courier',
                'moving_towards_customer', 'moving_towards_laundrymart',
            ])),
            ready=Count('id', filter=Q(status__in=[
                'arrived_at_laundry', 'received', 'weighed',
                'charged', 'processing_completion', 'completed',
            ])),
            order_delayed=Count('id', filter=Q(status='wait_for_support')),
        )

        # ── Latest 5 notifications ──
        latest_notifications = VendorNotification.objects.filter(
            recipient__in=laundry_marts
        ).select_related('recipient').order_by('-created_at')[:5]

        latest_reports = OrderReport.objects.filter(
            # created_at__date=today,
            order__service_provider__admin=request.user  # Filter orders by LaundrymartStore's admin
        ).select_related('order').order_by('-created_at')[:5]
        print(latest_reports)

        # Prepare table data in the most common unfold pattern (headers + rows as lists)
        alert_table_data = {
            "headers": [
                _("Date"),
                _("Store"),
                _("Message"),
                _("Category"),

            ],
            "rows": []
        }
        latest_reports_table_data = {
            "headers": [
                _("Date"),
                _("store"),
                _("Issue"),
                _("Order"),
            ],
            "rows":[]
        }
        for report in latest_reports:
            latest_reports_table_data["rows"].append([
                report.created_at.strftime("%d %b %Y %H:%M"),  # Format the date
                getattr(report.order.service_provider, 'name', str(report.order.service_provider)),  # Store name
                report.issue_description,  # Issue description
                str(report.order.uuid),  # Order ID
            ])


        for notif in latest_notifications:
            # Safe handling if target_url exists (make message clickable)
            message = notif.text

            alert_table_data["rows"].append([
                notif.created_at.strftime("%d %b %H:%M"),
                getattr(notif.recipient, 'name', str(notif.recipient)),  # use .name if exists, else str()
                message,
                notif.get_category_display(),
            ])


        extra_context = extra_context or {}
        extra_context.update({
            'today_date': today,
            'quote_stats': quote_stats,
            'order_stats': order_stats,
            'store_count': laundry_marts.count(),
            'latest_notifications': latest_notifications,
            'alert_table_data': alert_table_data,
            'latest_reports_table_data': latest_reports_table_data,
        })

        return super().changelist_view(request, extra_context=extra_context)