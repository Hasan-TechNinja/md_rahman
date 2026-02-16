from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import path, reverse
from django.utils.html import format_html

from unfold.admin import ModelAdmin, TabularInline

from messaging.models import AdminPanelMessaging, Message, CustomerNotification, Room, VendorNotification
from messaging.views import RoomChatView

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


  # ← This is the key line

@admin.register(Room)
class RoomAdmin(ModelAdmin):
  list_display = ['id','live_chat', 'order__uuid', 'name', 'created_at', 'message_count', 'last_message_at']
  list_filter = ['created_at', 'name']
  search_fields = ['name', 'order__uuid']
  readonly_fields = ['created_at', 'updated_at']
  inlines = [MessageInline]

  def get_urls(self):
    from django.urls import path

    urls = super().get_urls()

    custom_urls = [
      path(
        'chat/<int:room_id>/',
        staff_member_required(
          RoomChatView.as_view(model_admin=self)  # ← critical line
        ),
        name='room_chat',
      ),
    ]
    return custom_urls + urls

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

  @admin.display(description="Live Chat")
  def live_chat(self, obj):
    url = reverse("admin:room_chat", args=[obj.id])
    return format_html(
      '<a href="{}" class="button">Open Chat</a>',
      url
    )



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
