from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import OuterRef, Subquery
from django.shortcuts import get_object_or_404, render
from django.views.generic import TemplateView
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import AccessToken
from unfold.views import UnfoldModelAdminViewMixin

from accounts.models import User
from laundrymart.permissions import IsCustomer
from messaging.async_utils import broadcast_message, broadcast_seen_status
from messaging.models import CustomerNotification, Message, Room, VendorNotification
from messaging.serializers import CustomerNotificationSerializer, MessageSerializer, RoomSerializer, \
  VendorNotificationSerializer


# Create your views here.
class MessageAPIView(APIView):
  permission_classes = [IsAuthenticated]

  @extend_schema(request=MessageSerializer, responses=MessageSerializer)
  def post(self, request, room_id):
    room = get_object_or_404(Room, id=room_id)

    # Ensure user is a participant
    if not room.participants.filter(id=request.user.id).exists():
      return Response({"detail": "Not allowed in this room."}, status=status.HTTP_403_FORBIDDEN)

    serializer = MessageSerializer(data=request.data)
    if serializer.is_valid():
      message = serializer.save(user=request.user, room=room)  # 👈 explicitly set user + room

      message_data = MessageSerializer(message, context={'request':request}).data
      broadcast_message(room.id, message_data)

      return Response(message_data, status=status.HTTP_201_CREATED)

    errors = serializer.errors
    field, messages = next(iter(errors.items()))
    readable_field = field.replace('_', ' ').capitalize()
    first_message = messages[0] if isinstance(messages, list) else messages
    error_message = f"{readable_field}: {first_message}"
    return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)

  def get(self, request, room_id):
    room = get_object_or_404(Room, id=room_id)

    if not room.participants.filter(id=request.user.id).exists():
      return Response({"detail": "Not allowed in this room."}, status=403)

    messages = Message.objects.filter(room=room).order_by("created_at")
    if not messages.exists():
      return Response({"messages": [],"message": "No message yet"},status=200)

    # Find unseen messages sent by others
    unseen_messages = messages.filter(seen=False).exclude(user=request.user)
    unseen_ids = list(unseen_messages.values_list("id", flat=True))

    # Mark them as seen
    unseen_messages.update(seen=True)

    # Broadcast the update to all WebSocket clients in the room
    if unseen_ids:
      broadcast_seen_status(room.id, unseen_ids, request.user.id)

    serializer = MessageSerializer(messages, many=True, context={"request": request})
    return Response(serializer.data, status=200)

class RoomAPIView(APIView):
  permission_classes = [IsAuthenticated]
  def get(self, request):
    user = request.user
    latest_message = Message.objects.filter(room=OuterRef('pk')).order_by('-created_at')
    rooms = (
      Room.objects.filter(participants=user)
      .annotate(latest_message_time=Subquery(latest_message.values('created_at')[:1]))
      .order_by('-latest_message_time', '-created_at')# fallback: order by room creation if no messages
    ).exclude(order=None)
    serializer = RoomSerializer(rooms, many=True, context={'request': request})
    return Response(serializer.data, status=status.HTTP_200_OK)

@api_view(['GET'])
@permission_classes([IsCustomer])
def admin_chat_room(request):
  user = request.user
  super_users= User.objects.filter(is_superuser=True)
  participants = [user, super_users]
  rooms = Room.objects.filter(participants=participants)
  serializer = RoomSerializer(rooms, many=True, context={'request': request})
  return Response(serializer.data, status=status.HTTP_200_OK)

class CustomerNotificationAPIView(APIView):
  permission_classes = [IsCustomer]

  def get(self, request):
    user = request.user

    user.notifications.filter(seen=False).update(seen=True)

    notifications = user.notifications.all()

    serializer = CustomerNotificationSerializer(notifications, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)

  def delete(self, request):
    user = request.user

    user.notifications.all().delete()

    return Response({"message": "All notifications deleted."}, status=status.HTTP_200_OK)

class CustomerNotificationModifyAPIView(APIView):
  permission_classes = [IsAuthenticated]

  def patch(self, request, notification_id, action='mark_as_read'):
    user = request.user


    notification = get_object_or_404(
      CustomerNotification,
      id=notification_id,
      recipient=user  # ensures ownership in the same query
    )
    if action == "mark_as_read" or action is None:
      notification.is_read = True
      notification.save()
      return Response({"message": "Notification marked as read."}, status=status.HTTP_200_OK)
    elif action == "delete":
      notification.delete()
      return Response({"message": "Notification deleted."}, status=status.HTTP_200_OK)
    else:
      return Response({"error": "Invalid action."}, status=status.HTTP_400_BAD_REQUEST)

class RoomChatView(LoginRequiredMixin, UnfoldModelAdminViewMixin, TemplateView):
  """
  Full-screen WhatsApp-style chat panel for a specific room.
  Only accessible to participants of that room.
  """
  title = "Live Chat"
  template_name = "admin_panels/chat/chat_panel.html"  # your existing template
  permission_required = ()  # already handled by staff + participant check

  def dispatch(self, request, *args, **kwargs):
    # Early security: must be staff (admin access)
    if not request.user.is_staff:
      raise PermissionDenied("Only staff members can access this chat panel.")
    return super().dispatch(request, *args, **kwargs)

  def get_context_data(self, **kwargs):
    context = super().get_context_data(**kwargs)

    room_id = self.kwargs.get('room_id')
    room = get_object_or_404(
      Room,
      id=room_id,
      participants=self.request.user  # only rooms where current admin is participant
    )
    try:
      token = str(AccessToken.for_user(self.request.user))
      context['access_token'] = token
    except Exception:
      context['access_token'] = ''  # fallback

    context.update({
      'title': f"Chat — {room.name or f'Room {room.id}'}",
      'room': room,
      'room_id_json': str(room.id),
      'current_user_id': self.request.user.id,
      'current_user_name': self.request.user.full_name or self.request.user.username,
      'current_user_email': self.request.user.email,
      'api_base': '/message/api/',
      # Add any other context your template needs
    })
    print(context)

    return context