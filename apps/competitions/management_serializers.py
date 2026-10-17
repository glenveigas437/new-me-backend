from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.text import slugify
from uuid import uuid4
from rest_framework import serializers
from .models import Season, SeasonSettings, SeasonComponent, Component
from .rule_validation import validate_dependency_graph


class ManagedSeasonSerializer(serializers.ModelSerializer):
    rule_count = serializers.SerializerMethodField()
    rules_locked = serializers.SerializerMethodField()
    timezone = serializers.SerializerMethodField()

    class Meta:
        model = Season
        fields = [
            "id",
            "competition_id",
            "name",
            "start_date",
            "end_date",
            "rule_count",
            "rules_locked",
            "timezone",
        ]
        read_only_fields = [
            "id",
            "competition_id",
            "rule_count",
            "rules_locked",
            "timezone",
        ]

    def get_rule_count(self, obj):
        return obj.components.count()

    def get_rules_locked(self, obj):
        return bool(hasattr(obj, "settings") and obj.settings.locked_at)

    def get_timezone(self, obj):
        return obj.settings.timezone if hasattr(obj, "settings") else "Asia/Kolkata"

    def validate(self, attrs):
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start and end and end < start:
            raise serializers.ValidationError(
                {"end_date": "End date must be on or after start date."}
            )
        if self.instance and start and end:
            if (
                self.instance.periods.filter(start_date__lt=start).exists()
                or self.instance.periods.filter(end_date__gt=end).exists()
            ):
                raise serializers.ValidationError(
                    "Season dates must include all existing scoring periods."
                )
        return attrs


class SeasonRuleSerializer(serializers.ModelSerializer):
    points = serializers.DecimalField(
        source="max_points", max_digits=6, decimal_places=2, min_value=Decimal(0)
    )
    type = serializers.ChoiceField(
        source="rule_type", choices=SeasonComponent.RuleType.choices
    )
    name = serializers.CharField(max_length=100)
    depends_on = serializers.PrimaryKeyRelatedField(
        many=True, queryset=SeasonComponent.objects.all(), required=False
    )
    dependency_names = serializers.SerializerMethodField()

    class Meta:
        model = SeasonComponent
        fields = [
            "id",
            "season_id",
            "name",
            "points",
            "type",
            "cutoff",
            "metric",
            "depends_on",
            "dependency_names",
        ]
        read_only_fields = ["id", "season_id", "dependency_names"]

    def get_dependency_names(self, obj):
        return [r.name or r.component.name for r in obj.depends_on.all()]

    def validate_metric(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Choose or enter a metric.")
        return value

    def validate(self, attrs):
        season = self.context["season"]
        if "name" in attrs:
            name = attrs["name"].strip()
            if not name:
                raise serializers.ValidationError({"name": "Name is required."})
            if (
                season.components.filter(name__iexact=name)
                .exclude(pk=getattr(self.instance, "pk", None))
                .exists()
            ):
                raise serializers.ValidationError(
                    {"name": "A rule with this name already exists in this season."}
                )
            attrs["name"] = name
        if "depends_on" in attrs:
            try:
                validate_dependency_graph(
                    season.id,
                    getattr(self.instance, "pk", None),
                    [r.id for r in attrs["depends_on"]],
                )
            except DjangoValidationError as e:
                raise serializers.ValidationError({"depends_on": e.messages})
        return attrs

    def create(self, validated_data):
        deps = validated_data.pop("depends_on", [])
        component = Component.objects.create(
            code="rule-" + uuid4().hex, name=validated_data["name"]
        )
        rule = SeasonComponent.objects.create(
            season=self.context["season"], component=component, **validated_data
        )
        rule.depends_on.set(deps)
        return rule

    def update(self, instance, validated_data):
        deps = validated_data.pop("depends_on", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        instance.save()
        if deps is not None:
            instance.depends_on.set(deps)
        return instance
