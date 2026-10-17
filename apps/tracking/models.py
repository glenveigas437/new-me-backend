from django.db import models
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError


class UserActivity(models.Model):
    actual_value = models.DecimalField(
        max_digits=10, decimal_places=3, default=1, validators=[MinValueValidator(0)]
    )
    achieved = models.BooleanField(default=True, editable=False)
    participant = models.ForeignKey(
        "competitions.SeasonParticipant",
        on_delete=models.CASCADE,
        related_name="activities",
    )
    season_component = models.ForeignKey(
        "competitions.SeasonComponent", on_delete=models.PROTECT
    )
    activity = models.CharField(max_length=255, blank=True)
    activity_date = models.DateField()
    logged_at = models.DateTimeField(auto_now_add=True)
    base_points = models.DecimalField(max_digits=10, decimal_places=6, editable=False)
    penalty_percent = models.DecimalField(
        max_digits=5, decimal_places=2, editable=False
    )
    awarded_points = models.DecimalField(
        max_digits=10, decimal_places=6, editable=False
    )
    target_days_snapshot = models.PositiveSmallIntegerField(editable=False)
    max_points_snapshot = models.DecimalField(
        max_digits=6, decimal_places=2, editable=False
    )

    class Meta:
        ordering = ["-activity_date", "-logged_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["participant", "season_component", "activity_date"],
                name="one_component_per_day",
            )
        ]


class ParticipantGoal(models.Model):
    goal_key = models.CharField(max_length=40, null=True, blank=True)
    baseline_assumed = models.BooleanField(default=False)
    lower_limit = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True
    )
    upper_limit = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True
    )
    participant = models.ForeignKey(
        "competitions.SeasonParticipant", on_delete=models.CASCADE, related_name="goals"
    )
    goal_type = models.CharField(
        max_length=10, choices=[("body", "Body"), ("fitness", "Fitness")]
    )
    description = models.CharField(max_length=255)
    baseline_value = models.DecimalField(max_digits=10, decimal_places=3)
    target_value = models.DecimalField(max_digits=10, decimal_places=3)
    unit = models.CharField(max_length=30)
    method = models.CharField(max_length=255, blank=True, default="")
    max_points = models.DecimalField(
        max_digits=6, decimal_places=2, default=15, validators=[MinValueValidator(0)]
    )
    locked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["participant", "goal_key"],
                name="unique_participant_goal_key",
                condition=models.Q(goal_key__isnull=False),
            ),
            models.CheckConstraint(
                condition=models.Q(
                    goal_key="weight_maintenance", goal_key__isnull=False
                )
                | ~models.Q(target_value=models.F("baseline_value")),
                name="goal_target_differs",
            ),
        ]


class GoalMeasurement(models.Model):
    period = models.ForeignKey(
        "competitions.SeasonPeriod", on_delete=models.PROTECT, null=True, blank=True
    )

    goal = models.ForeignKey(
        ParticipantGoal, on_delete=models.CASCADE, related_name="measurements"
    )
    value = models.DecimalField(max_digits=10, decimal_places=3)
    measurement_date = models.DateField()
    logged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-measurement_date", "-logged_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["goal", "period"],
                condition=models.Q(period__isnull=False),
                name="one_goal_measurement_per_period",
            ),
            models.UniqueConstraint(
                fields=["goal", "measurement_date"], name="one_goal_measurement_per_day"
            ),
        ]
