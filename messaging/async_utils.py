from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def broadcast_message(room_id, message_data):
  """Send a message to all websocket clients in the room"""
  channel_layer = get_channel_layer()
  group_name = f"chat_{room_id}"
  async_to_sync(channel_layer.group_send)(
    group_name,
    {
      "type": "chat_message",   # matches consumer method
      "message": message_data,
    }
  )
def broadcast_seen_status(room_id, message_ids, seen_by_user_id):
  channel_layer = get_channel_layer()
  group_name = f"chat_{room_id}"

  async_to_sync(channel_layer.group_send)(
    group_name,
    {
      "type": "messages_seen_update",
      "message_ids": message_ids,
      "seen_by": seen_by_user_id,
    }
  )