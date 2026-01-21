from django.contrib import admin

from payment.models import Order, OrderProgression, Payment, PendingStripeOrder

# Register your models here.
admin.site.register(Payment)
admin.site.register(PendingStripeOrder)
admin.site.register(Order)
admin.site.register(OrderProgression)