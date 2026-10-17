from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo
from django.utils import timezone
from apps.competitions.models import SeasonPeriod

D = Decimal


def calculate_activity_points(target, day, now=None):
    settings = target.participant.season.settings
    cutoff = datetime.combine(
        day + timedelta(days=settings.logging_grace_days),
        target.season_component.cutoff or settings.logging_cutoff_time,
        tzinfo=ZoneInfo(settings.timezone),
    )
    base = target.season_component.max_points / D(target.target_days_per_week)
    penalty = (
        settings.late_penalty_percent if (now or timezone.now()) > cutoff else D(0)
    )
    return base, penalty, base * (1 - penalty / D(100))


def goal_score(goal):
    latest = goal.measurements.first()
    if not latest or not goal.locked_at:
        return D(0)
    if goal.goal_key == "weight_maintenance":
        # Maintenance rewards weekly check-ins inside the agreed band, including missing weeks as zero.
        season = goal.participant.season
        today = timezone.localdate(timezone=ZoneInfo(season.settings.timezone))
        periods = list(season.periods.filter(start_date__lte=today))
        if not periods:
            return D(0)
        inside = 0
        for period in periods:
            entry = goal.measurements.filter(
                measurement_date__gte=period.start_date,
                measurement_date__lte=min(today, period.end_date),
            ).first()
            if entry and goal.lower_limit <= entry.value <= goal.upper_limit:
                inside += 1
        return goal.max_points * D(inside) / len(periods)
    denominator = goal.target_value - goal.baseline_value
    if not denominator:
        return D(0)
    progress = (latest.value - goal.baseline_value) / denominator * 100
    fraction = (
        D(0)
        if progress <= 0
        else (
            D(".2")
            if progress < 25
            else (
                D(".4")
                if progress < 50
                else D(".6") if progress < 75 else D(".8") if progress < 100 else D(1)
            )
        )
    )
    return goal.max_points * fraction


def score_participant(participant, as_of=None):
    season = participant.season
    today = as_of or timezone.localdate(timezone=ZoneInfo(season.settings.timezone))
    periods = list(season.periods.filter(start_date__lte=today))
    rules = list(
        season.components.filter(rule_type="consistency").prefetch_related("depends_on")
    )
    targets = {
        t.season_component_id: t
        for t in participant.targets.select_related("season_component")
    }
    snapshots = (
        participant.scoring_snapshot if participant.registration_locked_at else {}
    )

    def maximum(rule):
        return D(snapshots.get(str(rule.id), {}).get("points", str(rule.max_points)))

    totals = []
    breakdown = []
    for period in periods:
        earned = {}
        for rule in rules:
            if rule.depends_on.exists():
                continue
            target = targets.get(rule.id)
            if not target:
                earned[rule.id] = D(0)
                continue
            logs = participant.activities.filter(
                season_component=rule,
                activity_date__gte=period.start_date,
                activity_date__lte=min(period.end_date, today),
                achieved=True,
            )
            if participant.registration_locked_at:
                logs = logs.order_by("logged_at", "id")
            else:
                logs = logs.order_by("-awarded_points", "activity_date")
            earned[rule.id] = min(
                sum(
                    (l.awarded_points for l in logs[: target.target_days_per_week]),
                    D(0),
                ),
                maximum(rule),
            )
        visiting = set()

        def resolve(rule):
            if rule.id in earned:
                return earned[rule.id]
            if rule.id in visiting:
                return D(0)  # graph validation normally makes this unreachable
            visiting.add(rule.id)
            deps = [d for d in rule.depends_on.all() if d.rule_type == "consistency"]
            fractions = [
                min(resolve(d) / maximum(d), D(1)) if maximum(d) > 0 else D(0)
                for d in deps
            ]
            earned[rule.id] = (
                maximum(rule) * sum(fractions, D(0)) / len(fractions)
                if fractions
                else D(0)
            )
            visiting.remove(rule.id)
            return earned[rule.id]

        for rule in rules:
            resolve(rule)
        total = sum(earned.values(), D(0))
        totals.append(total)
        breakdown.append(
            {
                "period": period.number,
                "start_date": str(period.start_date),
                "end_date": str(period.end_date),
                "total": fmt(total),
                "components": [
                    {
                        "id": r.id,
                        "name": r.name or r.component.name,
                        "earned": fmt(earned.get(r.id, D(0))),
                        "maximum": fmt(maximum(r)),
                        "compound": r.depends_on.exists(),
                    }
                    for r in rules
                ],
            }
        )
    consistency = sum(totals, D(0)) / len(totals) if totals else D(0)
    improvement = sum((goal_score(g) for g in participant.goals.all()), D(0))
    max_total = sum((maximum(r) for r in rules), D(0)) + sum(
        (g.max_points for g in participant.goals.all()), D(0)
    )
    return {
        "consistency": fmt(consistency),
        "improvement": fmt(improvement),
        "total": fmt(consistency + improvement),
        "maximum": fmt(max_total),
        "provisional": today <= season.end_date,
        "periods_counted": len(totals),
        "weekly_breakdown": breakdown,
    }


def fmt(value):
    return str(value.quantize(D(".01"), rounding=ROUND_HALF_UP))
