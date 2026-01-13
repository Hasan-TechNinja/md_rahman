from rest_framework import serializers

from messaging.models import CustomerNotification, Message, Room, VendorNotification


class MessageSerializer(serializers.ModelSerializer):
    user = serializers.StringRelatedField(read_only=True)  # Keep for internal/debug if needed
    sender_display = serializers.SerializerMethodField()   # This is what the frontend will use
    sender_image = serializers.SerializerMethodField()     # Optional: company logo or staff image

    class Meta:
        model = Message
        fields = [
            'id', 'text', 'user', 'sender_display', 'sender_image',
            'room', 'file', 'created_at', 'updated_at', 'seen'
        ]
        read_only_fields = ['created_at', 'updated_at', 'seen', 'room', 'user']

    def get_sender_display(self, obj: Message):
        request = self.context.get('request')
        if not request or not hasattr(obj.room, 'order'):
            return obj.user.full_name or "Unknown"

        order = obj.room.order
        store = order.service_provider  # Your LaundrymartStore instance

        # If the message is from anyone belonging to this store → show company name
        if obj.user.laundrymart_store == store:
            return store.laundrymart_name or "LaundryMart Support"

        # Otherwise it's the customer
        return obj.user.full_name or obj.user.phone_number or "Customer"

    def get_sender_image(self, obj: Message):
        request = self.context.get('request')
        if not request:
            return None

        order = getattr(obj.room, 'order', None)
        if not order:
            return None

        store = order.service_provider

        # Store-side message → you can return store logo if you have one
        if obj.user.laundrymart_store == store and store.laundrymart_logo:  # assuming store has image field
            return store.laundrymart_logo
        # Customer message → return their profile image
        if obj.user.image:
            return obj.user.image

        return None

class RoomSerializer(serializers.ModelSerializer):
    other_user = serializers.SerializerMethodField()
    other_user_image = serializers.SerializerMethodField()
    unseen_count = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    last_message_preview = serializers.SerializerMethodField()  # nicer preview
    order_id = serializers.CharField(source='order.uuid', read_only=True)

    class Meta:
        model = Room
        fields = [
            'id', 'order', 'order_id', 'name', 'participants', 'created_at',
            'other_user', 'other_user_image', 'unseen_count', 'updated_at',
            'last_message', 'last_message_preview'
        ]
        read_only_fields = ['participants', 'name', 'created_at', 'updated_at']

    def get_other_user(self, obj):
        request = self.context.get('request')
        if not request or not request.user or not hasattr(obj, 'order'):
            return None

        current_user = request.user
        store = obj.order.service_provider

        # If current user is the customer → show company name
        if current_user == obj.order.user:
            return store.laundrymart_name or "LaundryMart Support"

        # If current user is staff → show customer name
        return obj.order.user.full_name or obj.order.user.phone_number or "Customer"

    def get_other_user_image(self, obj):
        request = self.context.get('request')
        if not request or not hasattr(obj, 'order'):
            return None

        current_user = request.user
        store = obj.order.service_provider

        if current_user == obj.order.user:
            # Customer sees store logo
            if store.laundrymart_logo:
                # Ensure we return the URL for the image
                return store.laundrymart_logo.url if store.laundrymart_logo else None
        else:
            # Staff sees customer image
            if obj.order.user.image:
                # Ensure we return the URL for the image
                return obj.order.user.image.url if obj.order.user.image else None
        return None

    def get_last_message_preview(self, obj):
        last_message = obj.messages.order_by('-created_at').first()
        if not last_message:
            return "No messages yet"

        if last_message.text:
            return last_message.text[:60] + "..." if len(last_message.text) > 60 else last_message.text
        if last_message.file:
            return "Attachment"
        return "Media"

    def get_last_message(self, obj):
        # Keep old field for backward compatibility
        last = obj.messages.order_by('-created_at').first()
        if last:
            return last.text or (last.file.url if last.file else "")
        return None

    def get_unseen_count(self, obj):
        request = self.context.get('request')
        if not request or not request.user:
            return 0

        current_user = request.user
        store = obj.order.service_provider

        # Unseen messages sent by the *other side*
        if current_user == obj.order.user:
            # Customer: count unseen from store staff
            unseen = Message.objects.filter(
                room=obj,
                seen=False,
                user__laundrymart_store=store
            ).count()
        else:
            # Staff: count unseen from customer
            unseen = Message.objects.filter(
                room=obj,
                seen=False,
                user=obj.order.user
            ).count()

        return unseen

class VendorNotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = VendorNotification
        fields = [
            'id', 'category', 'recipient', 'text', 'target_url',
            'additional_info', 'created_at', 'updated_at', 'is_read', 'seen'
        ]
        read_only_fields = ['created_at', 'updated_at', 'is_read', 'seen', 'recipient']

class CustomerNotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerNotification
        fields = [
            'id', 'category', 'recipient', 'text', 'target_url',
            'additional_info', 'created_at', 'updated_at', 'is_read', 'seen'
        ]
        read_only_fields = ['created_at', 'updated_at', 'is_read', 'seen', 'recipient']
