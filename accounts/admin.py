from django.contrib import admin
from .models import LaundrymartStore, Service, User
# Register your models here.

class UserAdmin(admin.ModelAdmin):
    list_display = ('email', 'first_name', 'is_staff', 'is_active')
    search_fields = ('email', 'full_name',)
    
admin.site.register(User, UserAdmin)

@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
  def formfield_for_foreignkey(self, db_field, request, **kwargs):
    if db_field.name == "vendor":
      kwargs["queryset"] = User.objects.filter(is_staff=True)
    return super().formfield_for_foreignkey(db_field, request, **kwargs)

class LaundrymartStoreAdmin(admin.ModelAdmin):
    list_display = ('laundrymart_name','store_id')
    search_fields = ('admin', 'laundrymart_name',)
    list_editable = ('laundrymart_name',)
    list_display_links = ('store_id',)
admin.site.register(LaundrymartStore, LaundrymartStoreAdmin)