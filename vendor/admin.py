from decimal import Decimal

import humanize
from django.contrib import admin
from django.contrib.admin.views.main import ChangeList
from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from payment.models import Order
from uber.models import DeliveryQuote
from vendor.models import OrderReport, OrderReportImage, OrderTrack

# Register your models here.
admin.site.register(OrderReportImage)
admin.site.register(OrderReport)

@admin.register(OrderTrack)
class OrderTrackAdmin(ModelAdmin):
    change_list_template = "admin_panels/vendor/ordertrack_custom_changelist.html"
