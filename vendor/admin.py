import json
from decimal import Decimal

import humanize
from django.contrib import admin
from django.contrib.admin.views.main import ChangeList
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Count, DecimalField, ExpressionWrapper, F, IntegerField, Q, Sum, Value
from django.db.models.functions import Cast, Coalesce, TruncDay, TruncMonth
from django.urls import include, path, reverse
from django.utils import timezone
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from django.utils.translation import gettext_lazy as _
from unfold.components import BaseComponent, register_component

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
    readonly_fields = ('uploaded_at', )

@admin.register(OrderReport)
class OrderReportAdmin(ModelAdmin):
    list_display = ('user', 'order_link', 'order__service_provider')
    list_filter = ('created_at',)
    search_fields = ('user__full_name', 'user__email', 'issue_description')

    # Remove 'order_link' from here — it's not a model field
    fields = ('user', 'order', 'delivery_quote', 'created_at', 'issue_description')

    # If you want to show the order link in the change form as readonly text/link:
    readonly_fields = ('created_at', 'display_order_link')

    inlines = [OrderReportImageInline]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if not (request.user.is_superuser or getattr(request.user, 'is_hijacked', False)):
            qs = qs.filter(order__service_provider__admin=request.user).exclude(order__isnull=True)

        return qs

    def has_view_permission(self, request, obj=None):
        if request.user.is_superuser or getattr(request.user, 'is_hijacked', False):
            return True
        return super().has_view_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser or getattr(request.user, 'is_hijacked', False):
            return True
        return super().has_change_permission(request, obj)

    def has_add_permission(self, request):
        if request.user.is_superuser or getattr(request.user, 'is_hijacked', False):
            return True
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        if request.user.is_superuser or getattr(request.user, 'is_hijacked', False):
            return True
        return super().has_delete_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        always_readonly = ['created_at']

        protected_fields = []  # add more if needed, e.g. ['user', 'order']

        if request.user.is_superuser or getattr(request.user, 'is_hijacked', False):
            return always_readonly

        return always_readonly + protected_fields

    # Keep your nice link for list view
    @admin.display(description="Order", ordering='order__id')
    def order_link(self, obj):
        if obj.order:
            url = reverse("admin:payment_order_change", args=(obj.order.id,))
            return format_html('<a href="{}">{}</a>', url, obj.order)
        return "—"

    # Optional: show the link also in the change form (as readonly)
    @admin.display(description="Order link")
    def display_order_link(self, obj):
        if obj.order:
            url = reverse("admin:payment_order_change", args=(obj.order.id,))
            return format_html('<a href="{}" target="_blank">{}</a>', url, obj.order)
        return "No order linked"


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

# @register_component
# class VendorSalesChartComponent(BaseComponent):
#
#     def get_context_data(self, **kwargs):
#         context = super().get_context_data(**kwargs)
#         request = self.request
#
#         if not request or not request.user.is_authenticated:
#             chartjs_data = {"labels": [], "datasets": []}
#         else:
#             user = request.user
#
#             qs = Order.objects.all()
#
#             # Current month default
#             now = timezone.now()
#             qs = qs.filter(created_at__year=now.year, created_at__month=now.month)
#
#             # Vendor filter
#             if user.is_staff and not user.is_superuser:
#                 try:
#                     owned_store_ids = list(user.owned_stores.all().values_list('id', flat=True))
#                     if owned_store_ids:
#                         qs = qs.filter(service_provider__id__in=owned_store_ids)
#                     else:
#                         qs = qs.none()
#                 except Exception:
#                     qs = qs.none()
#             else:
#                 qs = qs.none()
#
#             # Aggregated query with revenue fallback
#             print(qs)
#             qs = (
#                 Order.objects
#
#                 .annotate(day=TruncDay('created_at'))
#
#                 # Then group by that day and compute aggregates
#                 .values('day')
#                 .annotate(
#                     order_count=Count('id'),  # ← renamed for clarity
#
#                     revenue_cents=Sum(  # ← use Sum() instead of Coalesce per row
#                         Coalesce(
#                             'final_total_cents',
#                             Cast(
#                                 ExpressionWrapper(
#                                     F('estimated_value'),
#                                     output_field=DecimalField(max_digits=12, decimal_places=0)
#                                 ),
#                                 output_field=IntegerField()
#                             ),
#                             Value(0, output_field=IntegerField())
#                         )
#                     )
#                 )
#                 .order_by('day')
#             )
#
#             # Now qs will have ONE row per unique day
#             print(qs)
#
#             labels = [row['day'].strftime('%d/%m/%Y') for row in qs]
#             order_data = [row['order_count'] for row in qs]  # ← now correct: [1, 4, 4] etc.
#             revenue_data = [float(row['revenue_cents'] or 0) / 100 for row in qs]
#             print("Labels:", labels)
#             print("Orders data:", order_data)  # [1, 2, 1, 4, 4]
#             print("Revenue data:", revenue_data)  # should be like [5500.0, 13000.0, 3500.0, 10500.0, 23427.0]
#
#             chartjs_data = {
#                 "labels": labels,
#                 "datasets": [
#                     {
#                         "label": "Orders",
#                         "data": order_data,
#                         "borderColor": "var(--color-primary-700)",
#                         "backgroundColor": "rgba(59, 130, 246, 0.15)",
#                         "fill": True,
#                         "tension": 0.3,
#                         "pointRadius": 4,
#                         "pointBackgroundColor": "#fff",
#                         "pointBorderColor": "var(--color-primary-700)",
#                         "pointBorderWidth": 2,
#                         "type": "line",
#                         "yAxisID": "y-orders",  # ← name it
#                     },
#                     {
#                         "label": "Revenue (USD)",
#                         "data": revenue_data,
#                         "borderColor": "var(--color-primary-200)",
#                         "backgroundColor": "rgba(100, 116, 139, 0.12)",
#                         "fill": True,
#                         "tension": 0.3,
#                         "pointRadius": 4,
#                         "pointBackgroundColor": "#fff",
#                         "pointBorderColor": "var(--color-primary-200)",
#                         "pointBorderWidth": 2,
#
#
#                         "type": "line",
#                         "yAxisID": "y-revenue",  # ← different name
#                     }
#                 ]
#             }
#             context.update({
#                 "height": 340,
#                 "data": json.dumps(chartjs_data),
#                 "chart_options": json.dumps({
#                     "scales": {
#                         "y-orders": {
#                             "type": "linear",
#                             "position": "left",
#                             "beginAtZero": True,
#                             "title": {
#                                 "display": True,
#                                 "text": "Number of Orders"
#                             },
#                             "grid": {
#                                 "drawOnChartArea": True
#                             }
#                         },
#                         "y-revenue": {
#                             "type": "linear",
#                             "position": "right",
#                             "beginAtZero": True,
#                             "title": {
#                                 "display": True,
#                                 "text": "Revenue (USD)"
#                             },
#                             "grid": {
#                                 "drawOnChartArea": False  # avoid double grid lines
#                             }
#                         },
#                         "x": {
#                             "title": {
#                                 "display": True,
#                                 "text": "Date"
#                             }
#                         }
#                     }
#                 })
#             })
#
#         context.update({
#             "height": 340,
#             "data": json.dumps(chartjs_data),
#         })
#         print("JSON being sent:", json.dumps(chartjs_data, indent=2))
#
#         return context

from vendor.models import OrderReport, OrderReportImage
@admin.register(OrderReport)
class OrderReportAdmin(ModelAdmin):
    pass
@admin.register(OrderReportImage)
class OrderReportImageAdmin(ModelAdmin):
    pass