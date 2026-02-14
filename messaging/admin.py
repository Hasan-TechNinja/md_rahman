from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from unfold.admin import ModelAdmin, TabularInline

from messaging.models import AdminPanelMessaging, Message, CustomerNotification, Room, VendorNotification

# Register your models here.
admin.site.register(CustomerNotification)


@admin.register(VendorNotification)
class VendorNotificationAdmin(ModelAdmin):
  pass

class MessageInline(TabularInline):
  model = Message
  extra = 0  # no empty forms
  max_num = 10  # limit how many are shown
  ordering = ['-created_at']  # newest first
  fields = ['user', 'text', 'file', 'seen', 'created_at']
  readonly_fields = ['user', 'text', 'file', 'seen', 'created_at']
  verbose_name_plural = "Recent messages"

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    # Note: This is hacky and may show raw HTML tags in some admin areas
    self.verbose_name_plural = format_html(
      'Recent Messages <a href="..." style="margin-left:10px;">Enter in the live chat</a>'
    )

  # ← This is the key line

@admin.register(Room)
class RoomAdmin(ModelAdmin):
    list_display = ['id', 'order__uuid', 'name', 'created_at', 'message_count', 'last_message_at', 'view_messages_link']
    list_filter = ['created_at', 'name']
    search_fields = ['name', 'order__uuid']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [MessageInline]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        qs = qs.filter(participants=request.user)
        return qs.select_related('order').prefetch_related('participants')

    # Extra columns
    @admin.display(description="Messages")
    def message_count(self, obj):
        return obj.messages.count()

    @admin.display(description="Last message")
    def last_message_at(self, obj):
        last = obj.messages.order_by('-created_at').first()
        return last.created_at if last else "-"

    @admin.display(description="Chat")
    def view_messages_link(self, obj):
        url = reverse("admin:messaging_message_changelist") + f"?room__id__exact={obj.id}"
        return format_html('<a href="{}" target="_blank">View all messages →</a>', url)

    def get_inline_instances(self, request, obj=None):
      # We only need to customize when editing an existing Room
      if obj is None:
        return super().get_inline_instances(request, obj)

      # Override the inline title template context
      for inline_class in self.inlines:
        inline = inline_class(self.model, self.admin_site)
        inline.template = "admin/messaging/room/message_inline_title.html"  # ← custom template
        # Pass extra context to the inline
        inline.extra_context = {
          'chat_link_url': reverse("admin:messaging_message_changelist") + f"?room__id__exact={obj.id}",
          'room_name': str(obj),  # or obj.name or whatever you prefer
        }
      return super().get_inline_instances(request, obj)


@admin.register(Message)
class MessageAdmin(ModelAdmin):
    list_display = ['room', 'user', 'short_text', 'file', 'seen', 'created_at']
    list_filter = ['room', 'user', 'seen', 'created_at']
    search_fields = ['text', 'user__email', 'user__phone_number', 'room__name']
    raw_id_fields = ['room', 'user']    # better for large number of users/rooms
    date_hierarchy = 'created_at'

    def short_text(self, obj):
        return (obj.text[:60] + "...") if obj.text else "(file)"
    short_text.short_description = "Message"

    inlines = []  # usually no need for nested inlines here


@admin.register(AdminPanelMessaging)
class AdminPanelMessagingAdmin(ModelAdmin):
  change_list_template = "admin_panels/chat/chat_panel.html"
  def changelist_view(self, request, extra_context=None):
    pass