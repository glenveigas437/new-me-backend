from datetime import timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from apps.accounts.models import User
from apps.clubs.models import Club, ClubMembership
from apps.competitions.models import (
    Competition,
    Season,
    SeasonSettings,
    SeasonComponent,
    Component,
    SeasonPeriod,
    SeasonParticipant,
    ParticipantComponentTarget,
)
from apps.tracking.models import ParticipantGoal, UserActivity
from apps.tracking.services import calculate_activity_points


class Command(BaseCommand):
    help = "Create isolated, fictional local demo data. Never run on a production database."

    def add_arguments(self, parser):
        parser.add_argument("--password", required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        from django.conf import settings

        if not settings.DEBUG:
            raise CommandError("Demo seeding is allowed only with DEBUG=True.")
        if User.objects.filter(username="demo").exists():
            raise CommandError("Demo already exists; no data changed.")
        now = timezone.now()
        start = timezone.localdate() - timedelta(days=13)
        club = Club.objects.create(name="The Better Club")
        comp = Competition.objects.create(club=club, name="Better Me 90")
        season = Season.objects.create(
            competition=comp,
            name="Season 01 · A fresh start",
            start_date=start,
            end_date=start + timedelta(days=89),
        )
        SeasonSettings.objects.create(
            season=season,
            late_penalty_percent=20,
            logging_grace_days=1,
            locked_at=now,
            settings_data={
                "weekly_aggregation": "average",
                "extra_days_policy": "best_target_days",
                "partial_week_policy": "full_target",
                "improvement_scoring": "latest_measurement_provisional",
            },
        )
        for n, offset in enumerate(range(0, 90, 7), 1):
            SeasonPeriod.objects.create(
                season=season,
                number=n,
                start_date=start + timedelta(days=offset),
                end_date=min(start + timedelta(days=offset + 6), season.end_date),
            )
        rules = []
        for code, name, points, target in [
            ("workout", "Workout", 25, 5),
            ("nutrition", "Nutrition adherence", 15, 7),
            ("hydration", "Hydration", 10, 7),
            ("sleep", "Sleep", 10, 7),
            ("activity", "Activity", 5, 7),
            ("check-in", "Daily accountability", 5, 7),
        ]:
            component, _ = Component.objects.get_or_create(
                code=code, defaults={"name": name}
            )
            rules.append(
                (
                    SeasonComponent.objects.create(
                        season=season, component=component, max_points=points
                    ),
                    target,
                )
            )
        for index, (username, first, last) in enumerate(
            [
                ("demo", "Alex", "Morgan"),
                ("riley", "Riley", "Chen"),
                ("jordan", "Jordan", "Patel"),
                ("sam", "Sam", "Taylor"),
            ]
        ):
            user = User.objects.create_user(
                username=username,
                email=username + "@example.test",
                password=options["password"],
                first_name=first,
                last_name=last,
                date_of_birth=__import__("datetime").date(1995, 1, 1),
                height_cm=175,
                weight_kg=75,
                is_staff=index == 0,
                is_superuser=index == 0,
            )
            ClubMembership.objects.create(
                club=club, user=user, role="admin" if index == 0 else "member"
            )
            p = SeasonParticipant.objects.create(season=season, user=user)
            for rule, target in rules:
                t = ParticipantComponentTarget.objects.create(
                    participant=p, season_component=rule, target_days_per_week=target
                )
                for offset in range(0, 12 - index * 2):
                    day = start + timedelta(days=offset)
                    base, penalty, awarded = calculate_activity_points(
                        t,
                        day,
                        now=timezone.make_aware(
                            __import__("datetime").datetime.combine(
                                day, __import__("datetime").time(18)
                            )
                        ),
                    )
                    UserActivity.objects.create(
                        participant=p,
                        season_component=rule,
                        activity_date=day,
                        activity="Demo activity",
                        base_points=base,
                        penalty_percent=penalty,
                        awarded_points=awarded,
                        target_days_snapshot=target,
                        max_points_snapshot=rule.max_points,
                    )
            ParticipantGoal.objects.create(
                participant=p,
                goal_type="body",
                description="Improve waist measurement",
                baseline_value=90,
                target_value=86,
                unit="cm",
                method="Same tape, same conditions",
                locked_at=now,
            )
            ParticipantGoal.objects.create(
                participant=p,
                goal_type="fitness",
                description="Improve 5 km completion time",
                baseline_value=35,
                target_value=30,
                unit="minutes",
                method="Same route and timing method",
                locked_at=now,
            )
        self.stdout.write(
            self.style.SUCCESS(
                "Demo created. Sign in as demo using your supplied password."
            )
        )
