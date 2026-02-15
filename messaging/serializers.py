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
        if not request or not request.user:
            return obj.user.full_name or obj.user.phone_number or "Unknown"

        current_user = request.user

        # ── Platform support / super-admin chat (no order) ──
        if not hasattr(obj.room, 'order') or obj.room.order is None:
            # Super admin message → show as "Admin" or "Support"
            # Customer message → show customer's name
            if obj.user.is_superuser:
                return "Support Admin" if current_user.is_superuser else "Admin"
            else:
                # Customer message in support chat
                return obj.user.full_name or obj.user.phone_number or "Customer"

        # ── Normal order-based chat ──
        order = obj.room.order
        store = order.service_provider  # LaundrymartStore

        if obj.user == store.admin:
            return store.laundrymart_name or "LaundryMart Support"

        # Customer message
        return obj.user.full_name or obj.user.phone_number or "Customer"

    def get_sender_image(self, obj: Message):
        request = self.context.get('request')
        if not request:
            return None

        # ── Platform support / super-admin chat (no order) ──
        if not hasattr(obj.room, 'order') or obj.room.order is None:
            sender = obj.user

            # If sender is superuser → default admin avatar
            if sender.is_superuser:
                return "https://ui-avatars.com/api/?name=Admin&background=9810fa&color=fff&size=128&rounded=true"

            # If sender is customer → use their profile picture if available
            if sender.image and hasattr(sender.image, 'url'):
                return sender.image.url

            return None

        # ── Normal order-based chat ──
        order = obj.room.order
        store = order.service_provider

        if obj.user == store.admin and store.laundrymart_logo and hasattr(store.laundrymart_logo, 'url'):
            return store.laundrymart_logo.url

        if obj.user.image and hasattr(obj.user.image, 'url'):
            return obj.user.image.url

        return None

class RoomSerializer(serializers.ModelSerializer):
    other_user = serializers.SerializerMethodField()
    other_user_image = serializers.SerializerMethodField()
    unseen_count = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    last_message_preview = serializers.SerializerMethodField()
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
        if not request or not request.user:
            return "Unknown"

        current_user = request.user

        # ── Super admin / platform support case ──
        if not hasattr(obj, 'order') or obj.order is None:
            # This room is likely a direct support chat with super admin
            if current_user.is_superuser:
                return "Customer Support"  # super admin sees generic name
            else:
                return "Admin"             # regular user sees "Admin"

        # ── Normal order-based chat ──
        store = obj.order.service_provider

        if current_user == obj.order.user:
            # Customer view
            return store.laundrymart_name or "LaundryMart Support"
        else:
            # Staff / store admin view
            return obj.order.user.full_name or obj.order.user.phone_number or "Customer"

    def get_other_user_image(self, obj):
        request = self.context.get('request')
        if not request or not request.user:
            return None

        current_user = request.user

        # ── Super admin / platform support case ──
        if not hasattr(obj, 'order') or obj.order is None:
            # Use a default admin avatar (you can put this in static or settings)
            # Option 1: hardcoded default (recommended for reliability)
            return "https://ui-avatars.com/api/?name=Admin&background=9810fa&color=fff&size=128"
            # Option 2: from static files (if you have one)
            # return static('images/default-admin.png')   # but needs {% load static %} in template

        # ── Normal order-based chat ──
        store = obj.order.service_provider

        if current_user == obj.order.user:
            # Customer sees store logo
            if store.laundrymart_logo and hasattr(store.laundrymart_logo, 'url'):
                return store.laundrymart_logo.url
        else:
            # Staff sees customer image
            if obj.order.user.image and hasattr(obj.order.user.image, 'url'):
                return obj.order.user.image.url

        return None

    def get_unseen_count(self, obj):
        request = self.context.get('request')
        if not request or not request.user:
            return 0

        current_user = request.user

        # ── Super admin / platform support case ──
        if not hasattr(obj, 'order') or obj.order is None:
            # For super admin chats: count messages not seen by current user
            # Assuming super admin is identified by is_superuser
            if current_user.is_superuser:
                # Super admin sees unseen from customers
                return obj.messages.filter(seen=False).exclude(user=current_user).count()
            else:
                # Customer sees unseen from super admin
                # If you store super admin messages with a specific user or flag,
                # adjust here. For now — simplest: count all unseen not from self
                return obj.messages.filter(seen=False).exclude(user=current_user).count()

        # ── Normal order-based chat ──
        store = obj.order.service_provider

        if current_user == obj.order.user:
            # Customer: unseen messages from store staff (admin)
            return Message.objects.filter(
                room=obj,
                seen=False,
                user=store.admin
            ).count()
        else:
            # Staff: unseen from customer
            return Message.objects.filter(
                room=obj,
                seen=False,
                user=obj.order.user
            ).count()

    def get_last_message_preview(self, obj):
        last_message = obj.messages.order_by('-created_at').first()
        if not last_message:
            return "No messages yet"

        if last_message.text:
            text = last_message.text
            return text[:60] + "..." if len(text) > 60 else text
        if last_message.file:
            return "Attachment"
        return "Media"

    def get_last_message(self, obj):
        last = obj.messages.order_by('-created_at').first()
        if last:
            return last.text or (last.file.url if last.file else "")
        return None

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
