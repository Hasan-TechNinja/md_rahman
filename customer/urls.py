from django.urls import path

from accounts.views import SecondaryLocationAPIView, SecondaryLocationModifyAPIView
from payment.views import ConfirmOrderAPIView, validate_saved_method
from uber.views import UberCreateQuoteAPIView
from . import views
from .views import ChooseForCustomer, CustomerOrderReportAPIView, CustomerOrdersListAPIView, customer_order_detail, CustomerGlobalManifestAPIView

urlpatterns = [
  path('vendors', views.VendorAPIView.as_view(), name='vendors'),
  path('review/<int:pk>', views.ReviewAPIView.as_view(), name='reviews'),
  path('get-quote', UberCreateQuoteAPIView.as_view(), name='get-quote'),
  path('locations', SecondaryLocationAPIView.as_view(), name='location'),
  path('location/<int:pk>', SecondaryLocationModifyAPIView.as_view(), name='location'),
  path('location', SecondaryLocationModifyAPIView.as_view(), name='location'),
  path('choose-for-customer', ChooseForCustomer.as_view(), name='choose-for-customer'),
  path('confirm-order', ConfirmOrderAPIView.as_view(), name='confirm-order'),
  path('charge-by-card', validate_saved_method, name='charge-by-card'),
  path('order-history', CustomerOrdersListAPIView.as_view(), name='order-history'),
  path('order-detail/<int:id>', customer_order_detail, name='order-detail'),
  path('order-report', CustomerOrderReportAPIView.as_view(), name='order-report'),
  path('global-manifest', CustomerGlobalManifestAPIView.as_view(), name='customer-global-manifest'),
  #
]