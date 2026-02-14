from django.contrib import admin

from customer.models import OutOfServiceCustomers, Review

# Register your models here.
admin.site.register(Review)
admin.site.register(OutOfServiceCustomers)
