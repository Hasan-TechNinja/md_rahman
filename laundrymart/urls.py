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

from uber.views import uber_delivery_status_webhook

urlpatterns = [
    path('admin/', admin.site.urls),
    path('hijack/', include('hijack.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
    path('accounts/api/',include('accounts.urls')),
    path('customers/api/',include('customer.urls')),
    path('message/api/',include('messaging.urls')),
    path('payment/api/',include('payment.urls')),
    path('vendor/api/',include('vendor.urls')),
    #path('api-auth/', include('rest_framework.urls')),
    path('webhook/delivery-status',uber_delivery_status_webhook, name='uber_delivery_status_webhook'),

    # path('webhook/request-sent', stripe_webhook_confirm_order, name='webhook-request-sent'),

    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    # Optional UI:
    path('api/schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
