from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class BetterMeUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Measurements", {"fields": ("height_cm", "weight_kg", "date_of_birth")}),
    )
