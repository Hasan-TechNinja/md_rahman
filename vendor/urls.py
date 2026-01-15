from django.urls import path

from vendor.views import AcceptQuoteAPIView, DashboardAPIView, VendorOrderReportAPIView, VendorOrdersListAPIView, \
  mark_order_as_received, save_final_order_weight

urlpatterns = [
  path('accept/<int:quote_id>', AcceptQuoteAPIView.as_view(), name='accept-reject'),
  path('dashboard', DashboardAPIView.as_view(), name='dashboard'),
  path('order-list', VendorOrdersListAPIView.as_view(), name='order-list'),
  path('order-report', VendorOrderReportAPIView.as_view(), name='order-list'),
  path('order-received/<int:order_id>', mark_order_as_received, name='order-received'),
  path('order-weighed/<int:order_id>', save_final_order_weight, name='order-weighed'),

]