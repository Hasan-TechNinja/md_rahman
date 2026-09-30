from django.db import models

from accounts.models import LaundrymartStore
from payment.models import Order
from uber.models import DeliveryQuote


# Create your models here.
class OrderReport(models.Model):
  laundrymart = models.ForeignKey(LaundrymartStore, on_delete=models.CASCADE,null=True, blank=True, related_name='vendor_filed_reports')
  delivery_quote=models.OneToOneField(DeliveryQuote, on_delete=models.CASCADE, null=True, blank=True,related_name='vendor_filed_report')
  order=models.OneToOneField(Order, on_delete=models.CASCADE, related_name='vendor_filed_report')
  issue_description = models.TextField()

  created_at = models.DateTimeField(auto_now_add=True)

class OrderReportImage(models.Model):
  report = models.ForeignKey(OrderReport, on_delete=models.CASCADE, related_name='images')
  image = models.ImageField(upload_to='order_laundrymart_report_images/')
  uploaded_at = models.DateTimeField(auto_now_add=True)
  def __str__(self):
    return f"Image for Report {self.report.id} uploaded at {self.uploaded_at}"

class OrderTrack(Order):
  class Meta:
    proxy = True
    verbose_name = "Track order"
    verbose_name_plural = "Track orders"


class VendorDashboard(models.Model):
  pass