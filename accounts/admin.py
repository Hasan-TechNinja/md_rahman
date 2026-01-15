from django.contrib import admin
from .models import LaundrymartStore, Service, User
# Register your models here.

class UserAdmin(admin.ModelAdmin):
    list_display = ('email', 'first_name', 'is_staff', 'is_active')
    search_fields = ('email', 'full_name',)
    
admin.site.register(User, UserAdmin)

admin.site.register(Service)


class LaundrymartStoreAdmin(admin.ModelAdmin):
    list_display = ('laundrymart_name','store_id')
    search_fields = ('admin', 'laundrymart_name',)
    list_editable = ('laundrymart_name',)
    list_display_links = ('store_id',)
admin.site.register(LaundrymartStore, LaundrymartStoreAdmin)