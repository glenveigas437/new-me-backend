from django.contrib import admin
from .models import UserActivity, ParticipantGoal, GoalMeasurement


@admin.register(UserActivity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = [
        "participant",
        "season_component",
        "activity_date",
        "awarded_points",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ParticipantGoal)
class GoalAdmin(admin.ModelAdmin):
    def has_change_permission(self, request, obj=None):
        return (
            False
            if obj and obj.locked_at
            else super().has_change_permission(request, obj)
        )

    def has_delete_permission(self, request, obj=None):
        return self.has_change_permission(request, obj)


@admin.register(GoalMeasurement)
class MeasurementAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
