from decimal import Decimal
from datetime import time
from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError


class Competition(models.Model):
    club = models.ForeignKey(
        "clubs.Club", on_delete=models.CASCADE, related_name="competitions"
    )
    name = models.CharField(max_length=255)

    def __str__(self):
        return self.name


class Season(models.Model):
    competition = models.ForeignKey(
        Competition, on_delete=models.CASCADE, related_name="seasons"
    )
    name = models.CharField(max_length=255)
    start_date = models.DateField()
    end_date = models.DateField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="season_dates_ordered",
            )
        ]

    def __str__(self):
        return self.name


class SeasonSettings(models.Model):
    body_goal_points = models.DecimalField(
        max_digits=6, decimal_places=2, default=15, validators=[MinValueValidator(0)]
    )
    fitness_goal_points = models.DecimalField(
        max_digits=6, decimal_places=2, default=15, validators=[MinValueValidator(0)]
    )
    season = models.OneToOneField(
        Season, on_delete=models.CASCADE, related_name="settings"
    )
    timezone = models.CharField(max_length=64, default="Asia/Kolkata")
    logging_cutoff_time = models.TimeField(default=time(23, 59, 59))
    logging_grace_days = models.PositiveSmallIntegerField(default=0)
    late_penalty_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    settings_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Extra configuration, not duplicate point allocations.",
    )
    locked_at = models.DateTimeField(null=True, blank=True)

    def clean(self):
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValidationError({"timezone": "Use a valid IANA timezone."})


class Component(models.Model):
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class SeasonComponent(models.Model):
    class RuleType(models.TextChoices):
        CONSISTENCY = "consistency", "Consistency"
        PERSONAL_IMPROVEMENT = "personal_improvement", "Personal improvement"

    name = models.CharField(max_length=100, blank=True, default="")
    rule_type = models.CharField(
        max_length=24, choices=RuleType.choices, default=RuleType.CONSISTENCY
    )
    cutoff = models.TimeField(
        null=True,
        blank=True,
        help_text="Daily logging cutoff in the season timezone. Blank inherits the season cutoff.",
    )
    metric = models.CharField(max_length=32, default="days")
    depends_on = models.ManyToManyField(
        "self", symmetrical=False, blank=True, related_name="dependent_rules"
    )

    season = models.ForeignKey(
        Season, on_delete=models.CASCADE, related_name="components"
    )
    component = models.ForeignKey(Component, on_delete=models.PROTECT)
    max_points = models.DecimalField(
        max_digits=6, decimal_places=2, validators=[MinValueValidator(0)]
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["season", "component"], name="unique_season_component"
            )
        ]


class SeasonPeriod(models.Model):
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name="periods")
    number = models.PositiveSmallIntegerField()
    start_date = models.DateField()
    end_date = models.DateField()

    class Meta:
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(
                fields=["season", "number"], name="unique_season_period"
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F("start_date")),
                name="period_dates_ordered",
            ),
        ]

    def clean(self):
        if self.start_date and self.end_date and self.season_id:
            if (
                self.start_date < self.season.start_date
                or self.end_date > self.season.end_date
            ):
                raise ValidationError("Period must lie inside season.")
            if (
                SeasonPeriod.objects.filter(
                    season_id=self.season_id,
                    start_date__lte=self.end_date,
                    end_date__gte=self.start_date,
                )
                .exclude(pk=self.pk)
                .exists()
            ):
                raise ValidationError("Periods must not overlap.")


class SeasonParticipant(models.Model):
    registration_locked_at = models.DateTimeField(null=True, blank=True)
    profile_snapshot = models.JSONField(default=dict, blank=True)
    scoring_snapshot = models.JSONField(default=dict, blank=True)
    season = models.ForeignKey(
        Season, on_delete=models.CASCADE, related_name="participants"
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["season", "user"], name="unique_season_participant"
            )
        ]


class ParticipantComponentTarget(models.Model):
    daily_target = models.DecimalField(
        max_digits=10,
        decimal_places=3,
        default=1,
        validators=[MinValueValidator(Decimal("0.001"))],
    )
    comparison = models.CharField(
        max_length=10,
        choices=[("gte", "At least"), ("lte", "At most"), ("range", "Within range")],
        default="gte",
    )
    lower_bound = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True
    )
    upper_bound = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True
    )
    participant = models.ForeignKey(
        SeasonParticipant, on_delete=models.CASCADE, related_name="targets"
    )
    season_component = models.ForeignKey(SeasonComponent, on_delete=models.PROTECT)
    target_days_per_week = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(7)]
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["participant", "season_component"],
                name="unique_participant_target",
            )
        ]

    def clean(self):
        if (
            self.participant_id
            and self.season_component_id
            and self.participant.season_id != self.season_component.season_id
        ):
            raise ValidationError(
                "Target and component must belong to the same season."
            )
