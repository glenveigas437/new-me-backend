from django.contrib import admin
from .models import Club, ClubMembership, ClubCode

admin.site.register([Club, ClubMembership])


@admin.register(ClubCode)
class ClubCodeAdmin(admin.ModelAdmin):
    list_display = ["club", "created_at", "expires_at", "revoked_at"]
    readonly_fields = [
        "club",
        "code",
        "created_by",
        "created_at",
        "expires_at",
        "revoked_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
