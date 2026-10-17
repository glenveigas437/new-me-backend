from zoneinfo import ZoneInfo
from apps.clubs.models import ClubMembership
from django.utils import timezone
from rest_framework import serializers
from apps.competitions.models import (
    SeasonParticipant,
    ParticipantComponentTarget,
    SeasonPeriod,
)
from .models import UserActivity, GoalMeasurement
from .services import calculate_activity_points


class ActivitySerializer(serializers.ModelSerializer):
    component_name = serializers.SerializerMethodField()

    def get_component_name(self, obj):
        return obj.season_component.name or obj.season_component.component.name

    class Meta:
        model = UserActivity
        fields = [
            "id",
            "participant",
            "season_component",
            "component_name",
            "activity",
            "activity_date",
            "actual_value",
            "achieved",
            "logged_at",
            "base_points",
            "penalty_percent",
            "awarded_points",
        ]
        read_only_fields = [
            "id",
            "logged_at",
            "base_points",
            "penalty_percent",
            "awarded_points",
            "achieved",
        ]
        validators = []

    def validate(self, attrs):
        participant = attrs["participant"]
        if not ClubMembership.objects.filter(
            club_id=participant.season.competition.club_id,
            user=self.context["request"].user,
        ).exists():
            raise serializers.ValidationError(
                "Your club membership is no longer active."
            )
        component = attrs["season_component"]
        day = attrs["activity_date"]
        if component.rule_type != "consistency" or component.depends_on.exists():
            raise serializers.ValidationError(
                "Compound rules are calculated automatically. Personal goals use weekly progress."
            )
        if participant.user_id != self.context["request"].user.id:
            raise serializers.ValidationError("You can log only your own activities.")
        if participant.season_id != component.season_id:
            raise serializers.ValidationError("Component belongs to another season.")
        try:
            settings = participant.season.settings
        except Exception:
            raise serializers.ValidationError(
                "Season settings have not been configured."
            )
        if day > timezone.localdate(timezone=ZoneInfo(settings.timezone)):
            raise serializers.ValidationError("Future activities cannot be logged.")
        if not participant.season.start_date <= day <= participant.season.end_date:
            raise serializers.ValidationError("Activity date is outside the season.")
        if not SeasonPeriod.objects.filter(
            season=participant.season, start_date__lte=day, end_date__gte=day
        ).exists():
            raise serializers.ValidationError("No scoring period covers this date.")
        if not settings.locked_at:
            raise serializers.ValidationError(
                "Organizer must lock season rules before logging starts."
            )
        try:
            self.target = ParticipantComponentTarget.objects.get(
                participant=participant, season_component=component
            )
        except ParticipantComponentTarget.DoesNotExist:
            raise serializers.ValidationError(
                "Organizer must set your component target first."
            )
        if UserActivity.objects.filter(
            participant=participant, season_component=component, activity_date=day
        ).exists():
            raise serializers.ValidationError(
                "Already logged for this component and date."
            )
        return attrs

    def create(self, validated_data):
        from apps.competitions.models import SeasonParticipant
        from django.db import transaction

        with transaction.atomic():
            # Lock the participant before rechecking duplicates and the weekly award count.
            participant = SeasonParticipant.objects.select_for_update().get(
                pk=validated_data["participant"].pk
            )
            target = self.target
            day = validated_data["activity_date"]
            if participant.activities.filter(
                season_component=target.season_component, activity_date=day
            ).exists():
                raise serializers.ValidationError(
                    "Already logged for this component and date."
                )
            actual = validated_data.get("actual_value", 1)
            if (
                participant.registration_locked_at
                and "actual_value" not in validated_data
            ):
                raise serializers.ValidationError(
                    "Enter the actual quantity completed."
                )
            achieved = (
                (target.lower_bound <= actual <= target.upper_bound)
                if target.comparison == "range"
                else (
                    actual <= target.daily_target
                    if target.comparison == "lte"
                    else actual >= target.daily_target
                )
            )
            base, penalty, awarded = calculate_activity_points(target, day)
            if participant.registration_locked_at:
                period = SeasonPeriod.objects.get(
                    season=participant.season, start_date__lte=day, end_date__gte=day
                )
                completed = participant.activities.filter(
                    season_component=target.season_component,
                    activity_date__gte=period.start_date,
                    activity_date__lte=period.end_date,
                    achieved=True,
                ).count()
                if completed >= target.target_days_per_week:
                    awarded = 0
            if not achieved:
                awarded = 0
            return UserActivity.objects.create(
                **validated_data,
                achieved=achieved,
                base_points=base,
                penalty_percent=penalty,
                awarded_points=awarded,
                target_days_snapshot=target.target_days_per_week,
                max_points_snapshot=target.season_component.max_points
            )


class MeasurementSerializer(serializers.ModelSerializer):
    class Meta:
        model = GoalMeasurement
        fields = ["id", "goal", "value", "measurement_date", "logged_at", "period"]
        read_only_fields = ["id", "logged_at", "period"]

    def validate(self, attrs):
        goal = attrs["goal"]
        season = goal.participant.season
        if goal.participant.user_id != self.context["request"].user.id:
            raise serializers.ValidationError("This goal is private.")
        if not ClubMembership.objects.filter(
            club_id=season.competition.club_id, user=self.context["request"].user
        ).exists():
            raise serializers.ValidationError(
                "Your club membership is no longer active."
            )
        if not goal.locked_at:
            raise serializers.ValidationError(
                "Your goal must be approved and locked first."
            )
        if (
            not season.start_date
            <= attrs["measurement_date"]
            <= min(
                season.end_date,
                timezone.localdate(timezone=ZoneInfo(season.settings.timezone)),
            )
        ):
            raise serializers.ValidationError(
                "Measurement date is outside the allowed range."
            )
        if goal.goal_key:
            from apps.competitions.enrollment import CATALOG

            spec = CATALOG[goal.goal_key]
            value = attrs["value"]
            if (
                value < spec["min"]
                or value > spec["max"]
                or (spec["unit"] == "reps" and value != int(value))
            ):
                raise serializers.ValidationError(
                    "Measurement is outside the valid range for this goal."
                )
            period = SeasonPeriod.objects.filter(
                season=season,
                start_date__lte=attrs["measurement_date"],
                end_date__gte=attrs["measurement_date"],
            ).first()
            if not period:
                raise serializers.ValidationError("No scoring period covers this date.")
            if goal.measurements.filter(period=period).exists():
                raise serializers.ValidationError(
                    "This goal already has a check-in for this week."
                )
            attrs["period"] = period
        return attrs

    def create(self, validated_data):
        from django.db import transaction
        from .models import ParticipantGoal

        with transaction.atomic():
            goal = ParticipantGoal.objects.select_for_update().get(
                pk=validated_data["goal"].pk
            )
            if (
                validated_data.get("period")
                and goal.measurements.filter(period=validated_data["period"]).exists()
            ):
                raise serializers.ValidationError(
                    "This goal already has a check-in for this week."
                )
            return GoalMeasurement.objects.create(**validated_data)
