from django.urls import path

from . import views
from .views import super_admin_stats_api

urlpatterns = [
path('super-admin-stats/', super_admin_stats_api, name='super_admin_stats')
  #
]