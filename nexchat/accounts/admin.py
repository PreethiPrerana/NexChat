from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "email", "display_name", "is_staff", "date_joined")
    fieldsets = BaseUserAdmin.fieldsets + (
        ("NexChat", {"fields": ("display_name",)}),
    )