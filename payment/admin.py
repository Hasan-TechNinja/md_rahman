from django.contrib import admin
from unfold.admin import ModelAdmin

from payment.models import Order, OrderProgression, Payment, PendingStripeOrder

# Register your models here.
admin.site.register(Payment)
admin.site.register(PendingStripeOrder)
@admin.register(Order)
class OrderAdmin(ModelAdmin):
  pass
admin.site.register(OrderProgression)