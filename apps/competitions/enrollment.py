from datetime import timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
from django.db import transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework import serializers
from apps.accounts.models import User
from apps.clubs.models import Club
from apps.clubs.views import member, require_profile
from apps.tracking.models import ParticipantGoal
from .models import (
    Season,
    SeasonSettings,
    SeasonParticipant,
    ParticipantComponentTarget,
    SeasonPeriod,
)
from .management_serializers import SeasonRuleSerializer

GOALS = [
    {
        "key": "weight_loss",
        "category": "body",
        "name": "Weight loss",
        "unit": "kg",
        "direction": "decrease",
        "profile_field": "weight_kg",
        "min": 20,
        "max": 500,
    },
    {
        "key": "weight_gain",
        "category": "body",
        "name": "Weight gain",
        "unit": "kg",
        "direction": "increase",
        "profile_field": "weight_kg",
        "min": 20,
        "max": 500,
    },
    {
        "key": "weight_maintenance",
        "category": "body",
        "name": "Weight maintenance",
        "unit": "kg",
        "direction": "range",
        "profile_field": "weight_kg",
        "min": 20,
        "max": 500,
    },
    {
        "key": "muscle_gain",
        "category": "body",
        "name": "Muscle gain",
        "unit": "%",
        "direction": "increase",
        "profile_field": "muscle_percentage",
        "min": 0.01,
        "max": 100,
    },
    {
        "key": "body_fat_loss",
        "category": "body",
        "name": "Body-fat loss",
        "unit": "%",
        "direction": "decrease",
        "profile_field": "body_fat_percentage",
        "min": 0.01,
        "max": 100,
    },
    {
        "key": "running_distance",
        "category": "fitness",
        "name": "Running distance",
        "unit": "km",
        "direction": "increase",
        "default": 0,
        "min": 0,
        "max": 10000,
    },
    {
        "key": "running_performance",
        "category": "fitness",
        "name": "Running pace",
        "unit": "min/km",
        "direction": "decrease",
        "default": 20,
        "min": 0.001,
        "max": 1000,
    },
    {
        "key": "walking_distance",
        "category": "fitness",
        "name": "Walking distance",
        "unit": "km",
        "direction": "increase",
        "default": 0,
        "min": 0,
        "max": 10000,
    },
    {
        "key": "walking_performance",
        "category": "fitness",
        "name": "Walking pace",
        "unit": "min/km",
        "direction": "decrease",
        "default": 30,
        "min": 0.001,
        "max": 1000,
    },
    {
        "key": "pushups",
        "category": "fitness",
        "name": "Push-ups",
        "unit": "reps",
        "direction": "increase",
        "default": 0,
        "min": 0,
        "max": 100000,
    },
    {
        "key": "pullups",
        "category": "fitness",
        "name": "Pull-ups",
        "unit": "reps",
        "direction": "increase",
        "default": 0,
        "min": 0,
        "max": 100000,
    },
    {
        "key": "squats",
        "category": "fitness",
        "name": "Squats",
        "unit": "reps",
        "direction": "increase",
        "default": 0,
        "min": 0,
        "max": 100000,
    },
    {
        "key": "plank",
        "category": "fitness",
        "name": "Plank",
        "unit": "seconds",
        "direction": "increase",
        "default": 0,
        "min": 0,
        "max": 100000,
    },
]
CATALOG = {g["key"]: g for g in GOALS}


def today(season):
    return timezone.localdate(timezone=ZoneInfo(season.settings.timezone))


def ensure_periods(season):
    if not season.periods.exists():
        offset = 0
        number = 1
        while season.start_date + timedelta(days=offset) <= season.end_date:
            start = season.start_date + timedelta(days=offset)
            SeasonPeriod.objects.create(
                season=season,
                number=number,
                start_date=start,
                end_date=min(start + timedelta(days=6), season.end_date),
            )
            offset += 7
            number += 1
    covered = season.start_date
    for period in season.periods.order_by("start_date"):
        if period.start_date != covered or period.end_date < period.start_date:
            raise ValidationError(
                "Scoring periods must cover the season without gaps or overlap."
            )
        covered = period.end_date + timedelta(days=1)
    if covered != season.end_date + timedelta(days=1):
        raise ValidationError("Scoring periods must cover the whole season.")


def season_access(request, season_id, admin=False):
    season = get_object_or_404(
        Season.objects.select_related("competition__club", "settings"), pk=season_id
    )
    # Consistent lock order with club administration and rule management.
    Club.objects.select_for_update().get(pk=season.competition.club_id)
    member(season.competition.club, request.user, admin)
    # Lock only the Season row. Joining the optional reverse OneToOne settings
    # here creates an outer join that PostgreSQL cannot lock. Related objects
    # are loaded lazily by separate, non-locking queries when accessed.
    return Season.objects.select_for_update().get(pk=season_id)


def number(value, label, minimum=0, maximum=9999999):
    try:
        n = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError(f"{label}: enter a number.")
    if (
        not n.is_finite()
        or n < Decimal(str(minimum))
        or n > Decimal(str(maximum))
        or n.as_tuple().exponent < -3
    ):
        raise ValidationError(f"{label}: invalid value or more than 3 decimal places.")
    return n


def prepare_goals(raw, category, user, budget):
    if not isinstance(raw, list) or not raw:
        raise ValidationError(f"Select at least one {category} goal.")
    keys = [x.get("key") for x in raw if isinstance(x, dict)]
    if (
        len(keys) != len(raw)
        or not all(isinstance(key, str) for key in keys)
        or len(set(keys)) != len(keys)
    ):
        raise ValidationError("Each goal can be selected only once.")
    if len(set(keys) & {"weight_loss", "weight_gain", "weight_maintenance"}) > 1:
        raise ValidationError("Select only one weight goal: loss, gain or maintenance.")
    cents = int(budget * 100)
    share_cents, remainder = divmod(cents, len(raw))
    result = []
    for index, item in enumerate(raw):
        spec = CATALOG.get(item["key"])
        if not spec or spec["category"] != category:
            raise ValidationError("Invalid goal selection.")
        baseline = item.get("baseline")
        assumed = False
        field = spec.get("profile_field")
        if baseline in [None, ""]:
            baseline = getattr(user, field) if field else spec["default"]
            assumed = not field
        if baseline is None:
            raise ValidationError(f'Enter your current {spec["name"]} baseline.')
        baseline = number(
            baseline, spec["name"] + " baseline", spec["min"], spec["max"]
        )
        if spec["unit"] == "reps" and baseline != int(baseline):
            raise ValidationError("Repetitions must be whole numbers.")
        target = baseline
        low = high = None
        if spec["direction"] == "range":
            low = number(item.get("lower_limit"), "Lower weight limit", 20, 500)
            high = number(item.get("upper_limit"), "Upper weight limit", 20, 500)
            if low >= high:
                raise ValidationError(
                    "Maintenance lower limit must be less than upper limit."
                )
        else:
            target = number(
                item.get("target"), spec["name"] + " target", spec["min"], spec["max"]
            )
            if spec["direction"] == "increase" and target <= baseline:
                raise ValidationError(f'{spec["name"]}: target must exceed baseline.')
            if spec["direction"] == "decrease" and target >= baseline:
                raise ValidationError(f'{spec["name"]}: target must be below baseline.')
            if spec["unit"] == "reps" and target != int(target):
                raise ValidationError("Repetition targets must be whole numbers.")
        if field:
            if baseline.as_tuple().exponent < -2:
                raise ValidationError(
                    "Profile body measurements support at most two decimal places."
                )
            setattr(user, field, baseline)
        method = ""  # Retained for legacy rows; no method question is required.
        result.append(
            dict(
                goal_key=spec["key"],
                goal_type=category,
                description=spec["name"],
                baseline_value=baseline,
                target_value=target,
                unit=spec["unit"],
                method=method,
                max_points=Decimal(share_cents + (1 if index < remainder else 0)) / 100,
                baseline_assumed=assumed or bool(item.get("baseline_assumed", False)),
                lower_limit=low,
                upper_limit=high,
            )
        )
    return result


class RegistrationConfigView(APIView):
    @transaction.atomic
    def get(self, request, season_id):
        season = season_access(request, season_id)
        participant = season.participants.filter(user=request.user).first()
        return Response(
            {
                "season": {
                    "id": season.id,
                    "name": season.name,
                    "start_date": season.start_date,
                    "end_date": season.end_date,
                    "timezone": season.settings.timezone,
                },
                "published": bool(season.settings.locked_at),
                "registration_open": today(season) < season.start_date,
                "registered": bool(participant and participant.registration_locked_at),
                "legacy_participation": bool(
                    participant and not participant.registration_locked_at
                ),
                "body_goal_points": str(season.settings.body_goal_points),
                "fitness_goal_points": str(season.settings.fitness_goal_points),
                "goals": GOALS,
                "rules": SeasonRuleSerializer(
                    season.components.prefetch_related("depends_on").order_by("id"),
                    many=True,
                ).data,
                "profile_complete": request.user.profile_complete,
                "compound_policy": "Equal average of dependency weekly achievement percentages, multiplied by compound maximum points.",
            }
        )


class PublishSeasonView(APIView):
    @transaction.atomic
    def post(self, request, season_id):
        season = season_access(request, season_id, True)
        if season.settings.locked_at:
            raise ValidationError("Season rules are already published and locked.")
        if today(season) >= season.start_date:
            raise ValidationError("Publish the season before its start date.")
        rules = list(season.components.prefetch_related("depends_on"))
        if not any(
            r.rule_type == "consistency" and not r.depends_on.exists() for r in rules
        ):
            raise ValidationError(
                "Add at least one non-compound consistency rule first."
            )
        for rule in rules:
            if (
                rule.rule_type == "consistency"
                and rule.depends_on.filter(rule_type="personal_improvement").exists()
            ):
                raise ValidationError(
                    "Consistency rules can depend only on consistency rules."
                )
            if rule.metric == "compound" and not rule.depends_on.exists():
                raise ValidationError(
                    f"{rule.name}: compound rules need at least one dependency."
                )
        for key in ["body_goal_points", "fitness_goal_points"]:
            if key in request.data:
                setattr(
                    season.settings, key, number(request.data[key], key, 0, 9999.99)
                )
        if any(
            getattr(season.settings, key).as_tuple().exponent < -2
            for key in ["body_goal_points", "fitness_goal_points"]
        ):
            raise ValidationError(
                "Goal point budgets support at most two decimal places."
            )
        ensure_periods(season)
        season.settings.locked_at = timezone.now()
        season.settings.save()
        return Response(
            {"detail": "Rules published. Registration is open until the season starts."}
        )


class EnrollSeasonView(APIView):
    @transaction.atomic
    def post(self, request, season_id):
        season = season_access(request, season_id)
        user = User.objects.select_for_update().get(pk=request.user.pk)
        require_profile(user)
        if request.data.get("confirmed") is not True:
            raise ValidationError("Review and confirm the season lock warning.")
        if today(season) >= season.start_date:
            raise ValidationError("Registration closed when the season started.")
        if not season.settings.locked_at:
            raise ValidationError("The club admin must publish season rules first.")
        if season.participants.filter(user=user).exists():
            raise ValidationError(
                "You already have a participation record for this season. Your choices cannot be replaced."
            )
        body = prepare_goals(
            request.data.get("body_goals"),
            "body",
            user,
            season.settings.body_goal_points,
        )
        fitness = prepare_goals(
            request.data.get("fitness_goals"),
            "fitness",
            user,
            season.settings.fitness_goal_points,
        )
        leaves = {
            r.id: r
            for r in season.components.filter(rule_type="consistency")
            if not r.depends_on.exists()
        }
        inputs = request.data.get("targets")
        if not isinstance(inputs, list) or len(inputs) != len(leaves):
            raise ValidationError(
                "Set one personal target for every non-compound consistency rule."
            )
        ids = [x.get("rule_id") for x in inputs if isinstance(x, dict)]
        if (
            len(ids) != len(inputs)
            or not all(type(i) is int for i in ids)
            or len(set(ids)) != len(ids)
            or set(ids) != set(leaves)
        ):
            raise ValidationError("Target rules do not match this season.")
        targets = []
        for item in inputs:
            rule = leaves[item["rule_id"]]
            days = item.get("target_days")
            if (
                isinstance(days, bool)
                or not isinstance(days, int)
                or not 1 <= days <= 7
            ):
                raise ValidationError("Target days must be an integer between 1 and 7.")
            value = number(item.get("daily_target"), "Daily target", 0.001, 9999999)
            comparison = item.get("comparison", "gte")
            low = high = None
            if comparison not in ["gte", "lte", "range"]:
                raise ValidationError("Invalid comparison.")
            if comparison == "range":
                low = number(item.get("lower_bound"), "Lower target bound")
                high = number(item.get("upper_bound"), "Upper target bound")
                if not low <= value <= high or low >= high:
                    raise ValidationError(
                        "The daily target must be inside a valid lower/upper range."
                    )
            targets.append(
                dict(
                    season_component=rule,
                    target_days_per_week=days,
                    daily_target=value,
                    comparison=comparison,
                    lower_bound=low,
                    upper_bound=high,
                )
            )
        now = timezone.now()
        user.save(
            update_fields=["weight_kg", "muscle_percentage", "body_fat_percentage"]
        )
        snapshot = {
            r.id: {
                "points": str(r.max_points),
                "type": r.rule_type,
                "dependencies": list(r.depends_on.values_list("id", flat=True)),
                "name": r.name,
                "metric": r.metric,
                "cutoff": str(r.cutoff) if r.cutoff else None,
            }
            for r in season.components.all()
        }
        p = SeasonParticipant.objects.create(
            season=season,
            user=user,
            registration_locked_at=now,
            profile_snapshot={
                "height_cm": str(user.height_cm),
                "weight_kg": str(user.weight_kg),
                "muscle_percentage": (
                    str(user.muscle_percentage) if user.muscle_percentage else None
                ),
                "body_fat_percentage": (
                    str(user.body_fat_percentage) if user.body_fat_percentage else None
                ),
            },
            scoring_snapshot=snapshot,
        )
        for target in targets:
            ParticipantComponentTarget.objects.create(participant=p, **target)
        for goal in body + fitness:
            ParticipantGoal.objects.create(participant=p, locked_at=now, **goal)
        return Response(
            {
                "detail": "Registered. Your goals, baselines, targets and allocations are locked for this season.",
                "participation_id": p.id,
            },
            status=201,
        )
