from rest_framework import serializers
from .models import Season, SeasonParticipant
from apps.tracking.services import score_participant


class SeasonSerializer(serializers.ModelSerializer):
    club_name = serializers.CharField(source="competition.club.name")
    club_id = serializers.IntegerField(source="competition.club_id", read_only=True)
    competition_name = serializers.CharField(source="competition.name")
    participation_id = serializers.SerializerMethodField()
    components = serializers.SerializerMethodField()
    goals = serializers.SerializerMethodField()
    score = serializers.SerializerMethodField()
    registration_locked_at = serializers.SerializerMethodField()

    def get_registration_locked_at(self, obj):
        p = self.participant(obj)
        return p.registration_locked_at if p else None

    class Meta:
        model = Season
        fields = [
            "id",
            "name",
            "start_date",
            "end_date",
            "club_name",
            "club_id",
            "competition_name",
            "participation_id",
            "components",
            "goals",
            "score",
            "registration_locked_at",
        ]

    def participant(self, obj):
        return obj.participants.filter(user=self.context["request"].user).first()

    def get_participation_id(self, obj):
        p = self.participant(obj)
        return p.id if p else None

    def get_components(self, obj):
        p = self.participant(obj)
        if not p:
            return []
        return [
            {
                "id": t.season_component_id,
                "name": t.season_component.name or t.season_component.component.name,
                "max_points": str(t.season_component.max_points),
                "target_days": t.target_days_per_week,
                "daily_target": str(t.daily_target),
                "metric": t.season_component.metric,
                "comparison": t.comparison,
                "lower_bound": (
                    str(t.lower_bound) if t.lower_bound is not None else None
                ),
                "upper_bound": (
                    str(t.upper_bound) if t.upper_bound is not None else None
                ),
            }
            for t in p.targets.select_related("season_component__component")
        ]

    def get_goals(self, obj):
        p = self.participant(obj)
        if not p:
            return []
        return [
            {
                "id": g.id,
                "key": g.goal_key,
                "max_points": str(g.max_points),
                "baseline_assumed": g.baseline_assumed,
                "lower_limit": str(g.lower_limit) if g.lower_limit else None,
                "upper_limit": str(g.upper_limit) if g.upper_limit else None,
                "measurements": [
                    {
                        "date": str(m.measurement_date),
                        "value": str(m.value),
                        "period": m.period_id,
                    }
                    for m in g.measurements.all()
                ],
                "type": g.goal_type,
                "description": g.description,
                "baseline": str(g.baseline_value),
                "target": str(g.target_value),
                "unit": g.unit,
                "locked": bool(g.locked_at),
                "latest": (
                    str(g.measurements.first().value)
                    if g.measurements.exists()
                    else None
                ),
            }
            for g in p.goals.all()
        ]

    def get_score(self, obj):
        p = self.participant(obj)
        return score_participant(p) if p and hasattr(obj, "settings") else None
