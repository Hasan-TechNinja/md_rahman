import json
from channels.generic.websocket import AsyncWebsocketConsumer, AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from .models import Room, Message
from .serializers import MessageSerializer


class ChatConsumer(AsyncWebsocketConsumer):
  async def connect(self):
    self.room_id = self.scope['url_route']['kwargs']['room_id']
    self.room_group_name = f"chat_{self.room_id}"
    self.user = self.scope['user']

    if self.user.is_anonymous:
      await self.close()
      return

    # Verify user has access
    has_access = await self.check_room_access()
    if not has_access:
      await self.close()
      return

    await self.channel_layer.group_add(self.room_group_name, self.channel_name)
    await self.accept()

  async def disconnect(self, close_code):
    await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

  async def receive(self, text_data):
    try:
      text_data_json = json.loads(text_data)
      message_type = text_data_json.get("type", "chat_message")

      if message_type == "chat_message":
        message_text = text_data_json.get("message", "")
        if not message_text.strip():
          await self.send(text_data=json.dumps({
            "type": "error",
            "message": "Message cannot be empty"
          }))
          return

        # Save message to DB
        message = await self.save_message(message_text)
        if message:
          message_data = await self.serialize_message(message)

          # Broadcast (same as API)
          await self.channel_layer.group_send(
            self.room_group_name,
            {
              "type": "chat_message",
              "message": message_data,
            }
          )

    except Exception as e:
      await self.send(text_data=json.dumps({
        "type": "error",
        "message": str(e)
      }))

  async def chat_message(self, event):
    """Receive broadcast and send to client"""
    await self.send(text_data=json.dumps({
      "type": "chat_message",
      "message": event["message"],
    }))

  async def messages_seen_update(self, event):
    """
    Handles broadcasting seen message updates to WebSocket clients.
    """
    await self.send(text_data=json.dumps({
      "type": "messages_seen_update",
      "message_ids": event["message_ids"],
      "seen_by": event["seen_by"],
    }))

  @database_sync_to_async
  def check_room_access(self):
    try:
      room = Room.objects.get(id=self.room_id)
      return room.participants.filter(id=self.user.id).exists()
    except Room.DoesNotExist:
      return False

  @database_sync_to_async
  def save_message(self, text):
    return Message.objects.create(room_id=self.room_id, user=self.user, text=text)

  @database_sync_to_async
  def serialize_message(self, message):
    serializer = MessageSerializer(message, context={"user": self.scope["user"]})
    return serializer.data