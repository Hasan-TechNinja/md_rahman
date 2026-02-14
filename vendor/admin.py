from decimal import Decimal

import humanize
from django.contrib import admin
from django.contrib.admin.views.main import ChangeList
from django.core.exceptions import ObjectDoesNotExist
from django.urls import include, path, reverse
from django.utils import timezone
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from unfold.sites import UnfoldAdminSite

from payment.models import LaundrymartPaymentMethod, Order
from payment.views import AddPaymentMethodView, SetupIntentCreateView, SetupIntentSuccessView
from uber.models import DeliveryQuote
from vendor.models import OrderReport, OrderReportImage, OrderTrack
from vendor.views import DeletePaymentMethodView, PaymentMethodsView, SetDefaultPaymentMethodView

# Register your models here.
admin.site.register(OrderReportImage)
admin.site.register(OrderReport)

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
