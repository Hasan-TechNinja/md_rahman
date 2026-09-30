from django.urls import path

from vendor.views import AcceptQuoteAPIView, DashboardAPIView, RejectQuoteAPIView, VendorOrderDetailAPIView, \
  VendorOrderReportAPIView, \
  VendorOrdersListAPIView, VendorSalesSummaryAPI, mark_order_as_completed, mark_order_as_ready, mark_order_as_received, \
  save_final_order_weight, VendorGlobalManifestAPIView
urlpatterns = [
  path('accept/<int:quote_id>', AcceptQuoteAPIView.as_view(), name='accept-reject'),
  path('reject/<int:quote_id>', RejectQuoteAPIView.as_view(), name='reject'),
  path('dashboard', DashboardAPIView.as_view(), name='dashboard'),
  path('order-list', VendorOrdersListAPIView.as_view(), name='order-list'),
  path('order-detail/<str:type>/<int:id>', VendorOrderDetailAPIView.as_view(), name='order-detail'),
  path('order-report', VendorOrderReportAPIView.as_view(), name='order-list'),
  path('sales-report/<int:user_id>/', VendorSalesSummaryAPI.as_view(), name='sales-report'),
  path('order-received/<int:order_id>', mark_order_as_received, name='order-received'),
  path('order-weighed/<int:order_id>', save_final_order_weight, name='order-weighed'),
  path('mark_as_ready/<int:order_id>', mark_order_as_ready, name='order-procession-completed'),
  path('mark_as_completed/<int:order_id>', mark_order_as_completed, name='order-picked-up-completed'),
  path('global-manifest', VendorGlobalManifestAPIView.as_view(), name='vendor-global-manifest'),

]