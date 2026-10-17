from decimal import Decimal
from django.utils import timezone
from .services import score_participant, goal_score, fmt


def participant_analytics(participant):
    season = participant.season
    goals = []
    for goal in participant.goals.prefetch_related("measurements"):
        history = [
            {"date": str(m.measurement_date), "value": str(m.value)}
            for m in goal.measurements.all()
        ]
        latest = history[0]["value"] if history else str(goal.baseline_value)
        if goal.goal_key == "weight_maintenance":
            percent = (
                (goal_score(goal) / goal.max_points * 100)
                if goal.max_points
                else Decimal(0)
            )
        else:
            distance = goal.target_value - goal.baseline_value
            percent = (
                max(
                    Decimal(0),
                    min(
                        Decimal(100),
                        (Decimal(latest) - goal.baseline_value) / distance * 100,
                    ),
                )
                if distance
                else Decimal(0)
            )
        goals.append(
            {
                "id": goal.id,
                "name": goal.description,
                "category": goal.goal_type,
                "key": goal.goal_key,
                "unit": goal.unit,
                "baseline": str(goal.baseline_value),
                "target": str(goal.target_value),
                "lower_limit": (
                    str(goal.lower_limit) if goal.lower_limit is not None else None
                ),
                "upper_limit": (
                    str(goal.upper_limit) if goal.upper_limit is not None else None
                ),
                "latest": latest,
                "progress_percent": fmt(percent),
                "earned_points": fmt(goal_score(goal)),
                "maximum_points": str(goal.max_points),
                "history": list(reversed(history)),
            }
        )
    activity_days = {}
    for log in participant.activities.all():
        key = str(log.activity_date)
        day = activity_days.setdefault(
            key, {"date": key, "entries": 0, "achieved": 0, "points": Decimal(0)}
        )
        day["entries"] += 1
        day["achieved"] += int(log.achieved)
        day["points"] += log.awarded_points
    days = [
        {**value, "points": fmt(value["points"])}
        for _, value in sorted(activity_days.items())
    ]
    return {
        "season": {
            "id": season.id,
            "name": season.name,
            "start_date": str(season.start_date),
            "end_date": str(season.end_date),
        },
        "generated_at": timezone.now().isoformat(),
        "score": score_participant(participant),
        "goals": goals,
        "activity_days": days,
    }
