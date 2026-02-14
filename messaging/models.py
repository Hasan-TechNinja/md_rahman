from django.db import models

from accounts.models import LaundrymartStore, User
from payment.models import Order


# Create your models here.
NOTIFICATION_CATEGORY_CHOICES=[
	('Normal', 'Normal'),
	('Important', 'Important'),
	('Promotional', 'Promotional'),
]
class CustomerNotification(models.Model):
	category = models.CharField(choices=NOTIFICATION_CATEGORY_CHOICES, default='Normal', max_length=255)
	custom_title=models.CharField(blank=True, null=True, max_length=255)
	recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
	text = models.TextField(blank=False, null=False, max_length=1000)
	target_url = models.CharField(max_length=255, null=True, blank=True)
	additional_info= models.JSONField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)
	is_read = models.BooleanField(default=False)
	seen = models.BooleanField(default=False)

	def __str__(self):
		return self.text
	class Meta:
		ordering = ['-created_at']

class VendorNotification(models.Model):
	category = models.CharField(choices=NOTIFICATION_CATEGORY_CHOICES, default='Normal', max_length=255)
	recipient = models.ForeignKey(LaundrymartStore, on_delete=models.CASCADE, related_name="vendor_notifications")
	text = models.TextField(blank=False, null=False, max_length=1000)
	target_url = models.CharField(max_length=255, null=True, blank=True)
	additional_info= models.JSONField(null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)
	is_read = models.BooleanField(default=False)
	seen = models.BooleanField(default=False)

	def __str__(self):
		return self.text
	class Meta:
		ordering = ['-created_at']

class Room(models.Model):
	order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="room", null=True, blank=True)
	name = models.CharField(max_length=255, null=True, blank=True)
	participants = models.ManyToManyField(User, related_name='rooms')
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)
	def __str__(self):
		return f'{self.name}-{self.id}'

class Message(models.Model):
	room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="messages")
	text = models.TextField(blank=True, null=True, max_length=1000)
	file = models.FileField(blank=True, null=True, upload_to="messages")
	user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="messages")
	seen = models.BooleanField(default=False)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	def __str__(self):
		return f"Message({self.user} in {self.room})-{self.id}"

class AdminPanelMessaging(models.Model):
	pass
	class Meta:
		verbose_name = 'Admin Panel Messaging'
		verbose_name_plural = 'Admin Panel Messaging'