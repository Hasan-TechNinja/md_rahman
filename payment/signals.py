from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from messaging.models import Room
from payment.models import Order


@receiver(post_save, sender=Order)
def create_order_room(sender, instance, created, **kwargs):
    if not created:
        return

    # Use atomic transaction to ensure room + participants are created together
    with transaction.atomic():
        # Create the one-to-one room for this order
        room = Room.objects.create(
            order=instance,
            name=f"Order #{instance.id} Chat"
        )

        # Add the customer
        room.participants.add(instance.user)

        # Add the store admin/owner if exists
        service_provider = instance.service_provider  # assuming this is the LaundrymartStore instance
        if service_provider.admin:
            room.participants.add(service_provider.admin)
