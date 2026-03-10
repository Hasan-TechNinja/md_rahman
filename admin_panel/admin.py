from django.contrib import admin
from solo.admin import SingletonModelAdmin

from unfold.admin import ModelAdmin

from admin_panel.models import GlobalManifest, NotificationText, SlideImage


# Register your models here.
@admin.register(GlobalManifest)
class GlobalManifestAdmin(ModelAdmin):
  pass

@admin.register(SlideImage)
class SlideImageAdmin(ModelAdmin):
  list_display = ('id', 'image', )
  list_editable = ('image',)
  ordering_field = "order_index"
  hide_ordering_field = True


@admin.register(NotificationText)
class NotificationTextAdmin(ModelAdmin):
  fieldsets = (
    ('Order Lifecycle', {
      "classes": ["tab"],
      "description": "General status updates from submission to cancellation.",
      "fields": [
        'order_submitted',
        'order_accepted',
        'order_declined',
        'order_reassigned',
        'order_canceled_general',
        'order_canceled_by_vendor',
        'order_canceled_by_customer'
      ]
    }),
    ('Pickup Phase', {
      "classes": ["tab"],
      "description": "Notifications related to the driver traveling to the customer.",
      "fields": [
        'driver_assigned_pickup',
        'driver_en_route_pickup',
        'driver_arrived_pickup',
        'pickup_success',
        'pickup_access_issue',
        'pickup_delayed'
      ]
    }),
    ('Processing Phase', {
      "classes": ["tab"],
      "description": "Updates while the laundry is at the facility.",
      "fields": [
        'laundry_received',
        'processing_started',
        'processing_finished',
        'ready_for_delivery_or_pickup',
        'processing_delayed'
      ]
    }),
    ('Delivery Phase', {
      "classes": ["tab"],
      "description": "Updates regarding the return of the clean laundry.",
      "fields": [
        'customer_picked_up',
        'driver_assigned_delivery',
        'driver_en_route_delivery',
        'driver_arrived_delivery',
        'delivery_success'
      ]
    }),
    ('Payments & Billing', {
      "classes": ["tab"],
      "fields": [
        'payment_authorized',
        'payment_failed',
        'weight_adjustment'
      ]
    }),
    ('Post-Order & Reviews', {
      "classes": ["tab"],
      "fields": [
        'rate_vendor',
        'rate_driver',
        'leave_review'
      ]
    }),
    ('Vendor Notifications', {
      "classes": ["tab"],
      "description": "Alerts sent specifically to the LaundryMart owners/staff.",
      "fields": [
        'new_customer_message',
        'unread_message_reminder',
        'customer_waiting_reminder',
        'general_reply_reminder'
      ]
    }),
  )
