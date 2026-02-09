from django.contrib import admin
from django_private_chat2.models import DialogsModel, MessageModel
from unfold.admin import ModelAdmin

from messaging.models import Message,CustomerNotification, Room, VendorNotification

# Register your models here.
admin.site.register(Message)
admin.site.register(Room)
admin.site.register(CustomerNotification)

@admin.register(VendorNotification)
class VendorNotificationAdmin(ModelAdmin):
  pass

admin.site.unregister(DialogsModel)
@admin.register(DialogsModel)
class DialogsAdmin(ModelAdmin):
  pass

admin.site.unregister(MessageModel)
@admin.register(MessageModel)
class MessageModelAdmin(ModelAdmin):
  pass