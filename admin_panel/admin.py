from django.contrib import admin
from django.db.models import Count, Sum
from django.utils import timezone
from solo.admin import SingletonModelAdmin

from unfold.admin import ModelAdmin
from django.utils.translation import gettext_lazy as _

from accounts.models import LaundrymartStore
from admin_panel.models import AdminDashboard, GlobalManifest, NotificationText, SlideImage
from payment.models import Order, VendorPayout


def tab_description(text: str) -> str:
  return (
    '<div class="text-gray-600 dark:text-gray-400 text-sm pl-3 leading-relaxed">'
    f'{text}'
    '</div>'
  )

# Register your models here.
@admin.register(GlobalManifest)
class GlobalManifestAdmin(ModelAdmin):

  fieldsets = (
    # ────────────────────────────────────────────────
    # Main Fees & Bag Defaults (always visible / first tab or no-tab section)
    # ────────────────────────────────────────────────
    (None, {
      'fields': (
        ('service_fee', 'insurance_fee',),
        ('customer_stripe_charge_in_percentage','customer_stripe_charge_added_cents'),
        ('payout_transaction_charge_in_percentage','payout_transaction_added_cents'),
      ),
      'description': _("Core fees applied across the platform."),
    }),

    # ────────────────────────────────────────────────
    # Bag Types Tab
    # ────────────────────────────────────────────────
    (_("Bag Types & Visuals"), {
      'classes': ('tab',),  # ← this enables the tab in supported themes
      'description': tab_description(
            "Define bag sizes, descriptions, and preview images shown to customers."
        ),
      'fields': (
        ('small_bag_text', 'small_bag_image'),
        ('medium_bag_text', 'medium_bag_image'),
        ('large_bag_text', 'large_bag_image'),
      ),
    }),

    # ────────────────────────────────────────────────
    # Customer App – Front Page / Navbar
    # ────────────────────────────────────────────────
    (_("Customer App – Front & Navigation"), {
      'classes': ('tab',),
      'description': tab_description("Greeting, service descriptions shown on home screen."),
      'fields': (
        'cust_navbar_text',
        'full_service_text',
        'drop_off_text',
        'pickup_text',
      ),
    }),

    # ────────────────────────────────────────────────
    # Customer App – More / Legal Section
    # ────────────────────────────────────────────────
    (_("Customer App – More & Legal"), {
      'classes': ('tab',),
      'description': tab_description("FAQ, policies, protections, account deletion info."),
      'fields': (
        'customer_faq',
        'customer_privacy_policy',
        'customer_terms_conditions',
        'customer_laundry_protections',
        'customer_account_delete_text',
      ),
    }),

    # ────────────────────────────────────────────────
    # Customer App – Invite Friends
    # ────────────────────────────────────────────────
    (_("Customer App – Referrals"), {
      'classes': ('tab',),
      'description': tab_description("Referral program texts, image, and credit config."),
      'fields': (
        'invite_top_text',
        'invite_image',
        'invite_share_link_text',
        'invite_get_credit_config',
      ),
    }),

    # ────────────────────────────────────────────────
    # Vendor App Section
    # ────────────────────────────────────────────────
    (_("Vendor App – Onboarding & Legal"), {
      'classes': ('tab',),
      'description': tab_description("Texts for laundry partners / vendors."),
      'fields': (
        'vendor_register_page_text',
        'vendor_order_history_info_text',
        'vendor_faq',
        'vendor_privacy_policy',
        'vendor_terms_conditions',
        'vendor_laundry_protection',
        'vendor_account_delete_text',
      ),
    }),

    # Optional: last tab with metadata
    (_("Metadata"), {
      'classes': ('tab', ),
      'fields': ('updated_at',),
      'description': tab_description("Last modification time – read-only."),
    }),
  )

  # Optional: make updated_at read-only
  readonly_fields = ('updated_at',)

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
      "description": tab_description("General status updates from submission to cancellation."),
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
      "description": tab_description("Notifications related to the driver traveling to the customer."),
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
      "description": tab_description("Updates while the laundry is at the facility."),
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
      "description": tab_description("Updates regarding the return of the clean laundry."),
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
      "description": tab_description("Alerts sent specifically to the LaundryMart owners/staff."),
      "fields": [
        'new_customer_message',
        'unread_message_reminder',
        'customer_waiting_reminder',
        'general_reply_reminder'
      ]
    }),
  )


@admin.register(AdminDashboard)  # or use a dummy model if you prefer no real model
class AdminDashboardAdmin(ModelAdmin):
  change_list_template = "admin_panels/super_admin/dashboard_changelist.html"

  # Optional: hide the default changelist table if you want pure dashboard
  list_display = []
  list_filter = []
  search_fields = []

  def changelist_view(self, request, extra_context=None):
    extra_context = extra_context or {}
    extra_context['today_date'] = timezone.now().date()
    extra_context['vendors'] = LaundrymartStore.objects.all().order_by('laundrymart_name')
    # You can pre-load default start/end date here if you want
    return super().changelist_view(request, extra_context)
