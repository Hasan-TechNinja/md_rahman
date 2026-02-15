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
            return obj.user.full_name or obj.user.phone_number or "Unknown"

        order = obj.room.order
        store = order.service_provider  # LaundrymartStore

        # If the message sender is the admin/owner of this store
        if obj.user == store.admin:
            return store.laundrymart_name or "LaundryMart Support"

        # Otherwise it's the customer
        return obj.user.full_name or obj.user.phone_number or "Customer"

    def get_sender_image(self, obj: Message):
        request = self.context.get('request')
        if not request or not hasattr(obj.room, 'order'):
            return None

        order = obj.room.order
        store = order.service_provider

        # If sender is store admin → return store logo
        if obj.user == store.admin and store.laundrymart_logo:
            return store.laundrymart_logo.url if hasattr(store.laundrymart_logo, 'url') else None

        # If sender is customer → return user profile image
        if obj.user.image:
            return obj.user.image.url if hasattr(obj.user.image, 'url') else None

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

        # If current user is the customer → show store name
        if current_user == obj.order.user:
            return store.laundrymart_name or "LaundryMart Support"

        # If current user is staff (store admin) → show customer name
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
                return store.laundrymart_logo.url if hasattr(store.laundrymart_logo, 'url') else None
        else:
            # Staff sees customer image
            if obj.order.user.image:
                return obj.order.user.image.url if hasattr(obj.order.user.image, 'url') else None
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

        if current_user == obj.order.user:
            # Customer: unseen messages from store staff (admin)
            unseen = Message.objects.filter(
                room=obj,
                seen=False,
                user=store.admin  # ← key change
            ).count()
        else:
            # Staff: unseen from customer
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
