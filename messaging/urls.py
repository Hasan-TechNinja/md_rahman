from django.urls import path

from messaging.views import CustomerNotificationAPIView, MessageAPIView, RoomAPIView, admin_chat_room

urlpatterns = [
	path('message/<int:room_id>', MessageAPIView.as_view(), name='message-send'),
	path('room', RoomAPIView.as_view(), name='message-list'),
	path('customer-admin-room/<str:order_id>', admin_chat_room, name='admin-chat-room'),
	path('customer-notifications', CustomerNotificationAPIView.as_view(), name='vendor-notifications'),
	path('customer-notifications/<int:notification_id>/<str:action>',CustomerNotificationAPIView.as_view(),name='vendor-notification-modify-action'),

]