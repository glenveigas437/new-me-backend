from django.contrib import admin
from django import forms
from .rule_validation import validate_dependency_graph
from django.core.exceptions import ValidationError
from .models import (
    Competition,
    Season,
    SeasonSettings,
    Component,
    SeasonComponent,
    SeasonPeriod,
    SeasonParticipant,
    ParticipantComponentTarget,
)


class LockedAdmin(admin.ModelAdmin):
    def has_change_permission(self, request, obj=None):
        if obj:
            season = obj.season if hasattr(obj, "season") else obj.participant.season
            if hasattr(season, "settings") and season.settings.locked_at:
                return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_change_permission(request, obj)

    def has_add_permission(self, request):
        return super().has_add_permission(request)

    def save_model(self, request, obj, form, change):
        season = obj.season if hasattr(obj, "season") else obj.participant.season
        if hasattr(season, "settings") and season.settings.locked_at:
            raise ValidationError("Season rules are locked.")
        super().save_model(request, obj, form, change)


@admin.register(SeasonSettings)
class SettingsAdmin(admin.ModelAdmin):
    def has_change_permission(self, request, obj=None):
        return (
            False
            if obj and obj.locked_at
            else super().has_change_permission(request, obj)
        )

    def has_delete_permission(self, request, obj=None):
        return self.has_change_permission(request, obj)


class RuleForm(forms.ModelForm):
    class Meta:
        model = SeasonComponent
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        season = cleaned.get("season")
        deps = cleaned.get("depends_on")
        if season and deps is not None:
            validate_dependency_graph(season.id, self.instance.pk, [x.id for x in deps])
        return cleaned


@admin.register(SeasonComponent)
class SeasonRuleAdmin(LockedAdmin):
    form = RuleForm
    list_display = ["name", "season", "rule_type", "max_points", "metric", "cutoff"]


for model in [SeasonPeriod, ParticipantComponentTarget]:
    admin.site.register(model, LockedAdmin)
admin.site.register([Competition, Season, Component, SeasonParticipant])
