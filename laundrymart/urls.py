"""
URL configuration for laundrymart project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from laundrymart import settings
from django_private_chat2 import urls as django_private_chat2_urls

from payment.views import AddPaymentMethodView, SetupIntentCreateView
from uber.views import uber_delivery_status_webhook
from vendor.views import DeletePaymentMethodView, PaymentMethodsView, SetDefaultPaymentMethodView
def get_vendor_urls():
    return [
        path('payment-methods/', PaymentMethodsView.as_view(), name='vendor_payment_methods'),
        path('payment-methods/add/', AddPaymentMethodView.as_view(), name='vendor_add_payment_method'),
        path('payment-methods/create-setup-intent/', SetupIntentCreateView.as_view(), name='create_setup_intent'),
        path('payment-methods/delete/<int:pk>/', DeletePaymentMethodView.as_view(), name='vendor_delete_payment_method'),
        path('payment-methods/set-default/<int:pk>/', SetDefaultPaymentMethodView.as_view(), name='vendor_set_default_payment_method'),
    ]

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/api/',include('accounts.urls')),
    path('customers/api/',include('customer.urls')),
    path('message/api/',include('messaging.urls')),
    path('payment/api/',include('payment.urls')),
    path('vendor/api/',include('vendor.urls')),
    #path('api-auth/', include('rest_framework.urls')),
    path(r'^', include(django_private_chat2_urls)),
    path('webhook/delivery-status',uber_delivery_status_webhook, name='uber_delivery_status_webhook'),

    # path('webhook/request-sent', stripe_webhook_confirm_order, name='webhook-request-sent'),

    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    # Optional UI:
    path('api/schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
