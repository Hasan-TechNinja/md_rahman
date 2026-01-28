from django.db.models.signals import post_save, pre_save, pre_delete
from django.dispatch import receiver
from .models import User

@receiver(post_save, sender=User)
def create_admin_chatroom(sender, instance, created, **kwargs):
  if created and not instance.is_staff:
    from messaging.models import Room
    superusers = User.objects.filter(is_superuser=True)
    participants = [instance] + list(superusers)
    room, created = Room.objects.get_or_create(name='Admin Chatroom', participants=participants)


