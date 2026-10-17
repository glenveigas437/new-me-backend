from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from apps.accounts.models import User
from apps.clubs.models import Club, ClubMembership
from apps.tracking.models import ParticipantGoal, GoalMeasurement, UserActivity
from apps.tracking.services import score_participant
from .models import (
    Competition,
    Season,
    SeasonSettings,
    Component,
    SeasonComponent,
    SeasonParticipant,
)


@override_settings(SECURE_SSL_REDIRECT=False)
class EnrollmentTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="owner",
            email="owner@a.test",
            password="Strong!123456",
            first_name="Owner",
            last_name="Tester",
            date_of_birth=date(1990, 1, 1),
            height_cm=175,
            weight_kg=80,
        )
        self.user = User.objects.create_user(
            username="member",
            email="member@a.test",
            password="Strong!123456",
            first_name="Member",
            last_name="Tester",
            date_of_birth=date(1995, 1, 1),
            height_cm=170,
            weight_kg=75,
        )
        self.club = Club.objects.create(name="Club")
        ClubMembership.objects.create(club=self.club, user=self.admin, role="admin")
        ClubMembership.objects.create(club=self.club, user=self.user)
        comp = Competition.objects.create(club=self.club, name="Challenge")
        self.start = timezone.localdate() + timedelta(days=2)
        self.season = Season.objects.create(
            competition=comp,
            name="Season",
            start_date=self.start,
            end_date=self.start + timedelta(days=20),
        )
        SeasonSettings.objects.create(season=self.season)
        self.rules = []
        for key, name, points, metric in [
            ("workout", "Workouts", 25, "sessions"),
            ("nutrition", "Nutrition", 15, "kcal"),
            ("water", "Water", 15, "litres"),
            ("compound", "Activity", 5, "compound"),
        ]:
            c = Component.objects.create(code=key, name=name)
            self.rules.append(
                SeasonComponent.objects.create(
                    season=self.season,
                    component=c,
                    name=name,
                    max_points=points,
                    metric=metric,
                )
            )
        self.rules[3].depends_on.set(self.rules[:3])
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.url = f"/api/seasons/{self.season.id}/"

    def publish(self):
        self.client.force_authenticate(self.admin)
        r = self.client.post(
            self.url + "publish/", {"body_goal_points": 15, "fitness_goal_points": 15}
        )
        self.assertEqual(r.status_code, 200, r.data)
        self.client.force_authenticate(self.user)

    def payload(self):
        return {
            "confirmed": True,
            "body_goals": [
                {
                    "key": "weight_loss",
                    "baseline": "75",
                    "target": "70",
                    "method": "Same scale",
                }
            ],
            "fitness_goals": [
                {
                    "key": "pushups",
                    "baseline": None,
                    "target": "20",
                    "method": "Same technique",
                },
                {
                    "key": "running_performance",
                    "baseline": None,
                    "target": "10",
                    "method": "Same 1 km route",
                },
            ],
            "targets": [
                {
                    "rule_id": self.rules[0].id,
                    "daily_target": "1",
                    "target_days": 3,
                    "comparison": "gte",
                },
                {
                    "rule_id": self.rules[1].id,
                    "daily_target": "2000",
                    "target_days": 5,
                    "comparison": "range",
                    "lower_bound": "1900",
                    "upper_bound": "2100",
                },
                {
                    "rule_id": self.rules[2].id,
                    "daily_target": "3",
                    "target_days": 7,
                    "comparison": "gte",
                },
            ],
        }

    def enroll(self, payload=None):
        self.publish()
        r = self.client.post(
            self.url + "enroll/", payload or self.payload(), format="json"
        )
        self.assertEqual(r.status_code, 201, r.data)
        return SeasonParticipant.objects.get(pk=r.data["participation_id"])

    def clock(self, offset=0):
        return patch(
            "django.utils.timezone.now",
            return_value=datetime.combine(
                self.start + timedelta(days=offset),
                time(18),
                tzinfo=ZoneInfo("Asia/Kolkata"),
            ),
        )

    def log(self, p, rule, quantity, offset=0):
        with self.clock(offset):
            return self.client.post(
                "/api/activities/",
                {
                    "participant": p.id,
                    "season_component": rule.id,
                    "activity_date": str(self.start + timedelta(days=offset)),
                    "actual_value": quantity,
                },
            )

    def test_profile_gate_create_join_and_completion(self):
        self.user.height_cm = None
        self.user.save()
        self.client.force_authenticate(self.user)
        self.assertEqual(
            self.client.get("/api/auth/me/").data["profile_complete"], False
        )
        self.assertEqual(
            self.client.post("/api/clubs/", {"name": "No"}).status_code, 400
        )
        self.assertEqual(
            self.client.post("/api/clubs/join/", {"code": "anything"}).status_code, 400
        )
        self.client.patch("/api/auth/me/", {"height_cm": "170"})
        self.user.refresh_from_db()
        self.assertTrue(self.user.profile_complete)
        self.assertEqual(
            self.client.post("/api/clubs/", {"name": "Yes"}).status_code, 201
        )

    def test_publication_generates_periods_and_freezes_rules(self):
        self.publish()
        self.assertEqual(self.season.periods.count(), 3)
        self.season.refresh_from_db()
        self.assertIsNotNone(self.season.settings.locked_at)

    def test_member_cannot_publish(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.post(self.url + "publish/", {}).status_code, 403)

    def test_registration_requires_published_and_confirmed(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(
            self.client.post(
                self.url + "enroll/", self.payload(), format="json"
            ).status_code,
            400,
        )
        self.publish()
        p = self.payload()
        p["confirmed"] = False
        self.assertEqual(
            self.client.post(self.url + "enroll/", p, format="json").status_code, 400
        )

    def test_multiple_goals_default_baselines_and_split(self):
        p = self.enroll()
        self.assertIsNotNone(p.registration_locked_at)
        goals = {g.goal_key: g for g in p.goals.all()}
        self.assertEqual(goals["pushups"].baseline_value, 0)
        self.assertTrue(goals["pushups"].baseline_assumed)
        self.assertEqual(goals["running_performance"].baseline_value, 20)
        self.assertEqual(goals["pushups"].max_points, Decimal("7.5"))
        self.assertEqual(sum(g.max_points for g in p.goals.all()), 30)

    def test_duplicate_registration_rejected(self):
        self.enroll()
        self.assertEqual(
            self.client.post(
                self.url + "enroll/", self.payload(), format="json"
            ).status_code,
            400,
        )

    def test_registration_closes_on_start(self):
        self.publish()
        with self.clock():
            self.assertEqual(
                self.client.post(
                    self.url + "enroll/", self.payload(), format="json"
                ).status_code,
                400,
            )

    def test_exclusive_weight_selection_and_invalid_direction(self):
        self.publish()
        p = self.payload()
        p["body_goals"].append(
            {"key": "weight_gain", "baseline": "75", "target": "80", "method": "Scale"}
        )
        self.assertEqual(
            self.client.post(self.url + "enroll/", p, format="json").status_code, 400
        )
        p = self.payload()
        p["body_goals"][0]["target"] = "80"
        self.assertEqual(
            self.client.post(self.url + "enroll/", p, format="json").status_code, 400
        )

    def test_missing_muscle_value_collected_and_saved(self):
        p = self.payload()
        p["body_goals"] = [
            {
                "key": "muscle_gain",
                "baseline": "35",
                "target": "38",
                "method": "Same device",
            }
        ]
        record = self.enroll(p)
        self.user.refresh_from_db()
        self.assertEqual(self.user.muscle_percentage, 35)
        self.assertEqual(record.goals.get(goal_key="muscle_gain").unit, "%")

    def test_missing_body_percentage_cannot_default_zero(self):
        self.publish()
        p = self.payload()
        p["body_goals"] = [
            {
                "key": "body_fat_loss",
                "baseline": None,
                "target": "20",
                "method": "Same device",
            }
        ]
        self.assertEqual(
            self.client.post(self.url + "enroll/", p, format="json").status_code, 400
        )
        self.assertFalse(self.season.participants.exists())

    def test_profile_edits_do_not_change_locked_baseline(self):
        p = self.enroll()
        self.client.patch("/api/auth/me/", {"weight_kg": "74"})
        self.assertEqual(p.goals.get(goal_key="weight_loss").baseline_value, 75)
        self.assertEqual(Decimal(p.profile_snapshot["weight_kg"]), Decimal(75))

    def test_actual_quantities_and_fourth_workout_zero(self):
        p = self.enroll()
        for day in range(4):
            r = self.log(p, self.rules[0], "1", day)
            self.assertEqual(r.status_code, 201, r.data)
            self.assertEqual(
                Decimal(r.data["awarded_points"]),
                0 if day == 3 else Decimal("8.333333"),
            )
        with self.clock(3):
            self.assertEqual(
                score_participant(p)["weekly_breakdown"][0]["components"][0]["earned"],
                "25.00",
            )

    def test_nutrition_range_and_water_quantity(self):
        p = self.enroll()
        r = self.log(p, self.rules[1], "1900")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Decimal(r.data["awarded_points"]), 3)
        r = self.log(p, self.rules[2], "2")
        self.assertEqual(Decimal(r.data["awarded_points"]), 0)
        self.assertFalse(r.data["achieved"])

    def test_compound_is_average_dependency_completion(self):
        p = self.enroll()
        self.log(p, self.rules[0], "1")
        self.log(p, self.rules[1], "2000")
        self.log(p, self.rules[2], "3")
        with self.clock():
            score = score_participant(p)
        c = score["weekly_breakdown"][0]["components"][-1]
        expected = (Decimal(1) / 3 + Decimal(1) / 5 + Decimal(1) / 7) / 3 * 5
        self.assertEqual(c["earned"], str(expected.quantize(Decimal(".01"))))
        self.assertEqual(self.log(p, self.rules[3], "1").status_code, 400)

    def test_weekly_measurement_lock_and_baseline_preserved(self):
        p = self.enroll()
        g = p.goals.get(goal_key="weight_loss")
        with self.clock():
            r = self.client.post(
                "/api/measurements/",
                {"goal": g.id, "value": "74", "measurement_date": str(self.start)},
            )
            self.assertEqual(r.status_code, 201, r.data)
        with self.clock(1):
            self.assertEqual(
                self.client.post(
                    "/api/measurements/",
                    {
                        "goal": g.id,
                        "value": "73",
                        "measurement_date": str(self.start + timedelta(days=1)),
                    },
                ).status_code,
                400,
            )
        with self.clock(7):
            self.assertEqual(
                self.client.post(
                    "/api/measurements/",
                    {
                        "goal": g.id,
                        "value": "73",
                        "measurement_date": str(self.start + timedelta(days=7)),
                    },
                ).status_code,
                201,
            )
        g.refresh_from_db()
        self.assertEqual(g.baseline_value, 75)

    def test_maintenance_in_range_and_missing_week_zero(self):
        payload = self.payload()
        payload["body_goals"] = [
            {
                "key": "weight_maintenance",
                "baseline": "75",
                "lower_limit": "74",
                "upper_limit": "76",
                "method": "Same scale",
            }
        ]
        p = self.enroll(payload)
        g = p.goals.get(goal_key="weight_maintenance")
        with self.clock():
            self.client.post(
                "/api/measurements/",
                {"goal": g.id, "value": "75", "measurement_date": str(self.start)},
            )
            self.assertEqual(score_participant(p)["improvement"], "15.00")
        with self.clock(7):
            self.assertEqual(score_participant(p)["improvement"], "7.50")

    def test_leaderboard_does_not_expose_target_details(self):
        p = self.enroll()
        with self.clock():
            r = self.client.get(f"/api/seasons/{self.season.id}/leaderboard/")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("weekly_breakdown", r.data[0])
        self.assertNotIn("baseline", str(r.data))

    def test_all_targets_required_and_duplicates_rejected(self):
        self.publish()
        p = self.payload()
        p["targets"] = p["targets"][:1]
        self.assertEqual(
            self.client.post(self.url + "enroll/", p, format="json").status_code, 400
        )
        p = self.payload()
        p["targets"][1] = p["targets"][0]
        self.assertEqual(
            self.client.post(self.url + "enroll/", p, format="json").status_code, 400
        )

    def test_config_private_to_current_club_members(self):
        other = User.objects.create_user(
            username="stranger", email="stranger@a.test", password="Strong!123456"
        )
        self.client.force_authenticate(other)
        self.assertEqual(self.client.get(self.url + "registration/").status_code, 403)

    def test_small_budget_split_stays_nonnegative_and_exact(self):
        self.client.post(
            self.url + "publish/",
            {"body_goal_points": "0.03", "fitness_goal_points": "0.03"},
        )
        self.client.force_authenticate(self.user)
        payload = self.payload()
        payload["fitness_goals"] = [
            {"key": key, "baseline": None, "target": 10, "method": "Same test"}
            for key in ["pushups", "pullups", "squats", "plank", "running_distance"]
        ]
        r = self.client.post(self.url + "enroll/", payload, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        p = SeasonParticipant.objects.get(pk=r.data["participation_id"])
        points = [g.max_points for g in p.goals.filter(goal_type="fitness")]
        self.assertEqual(sum(points), Decimal(".03"))
        self.assertTrue(all(x >= 0 for x in points))

    def test_malformed_goal_or_target_ids_rejected(self):
        self.publish()
        payload = self.payload()
        payload["targets"][0]["rule_id"] = []
        self.assertEqual(
            self.client.post(self.url + "enroll/", payload, format="json").status_code,
            400,
        )
        payload = self.payload()
        payload["body_goals"][0]["key"] = []
        self.assertEqual(
            self.client.post(self.url + "enroll/", payload, format="json").status_code,
            400,
        )

    def test_registration_locks_compile_without_nullable_joins_on_postgresql(self):
        from django.db.models.query import QuerySet
        from django.db.backends.postgresql.base import DatabaseWrapper

        pg = DatabaseWrapper(
            {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": "compile_only",
                "OPTIONS": {},
                "TIME_ZONE": None,
                "AUTOCOMMIT": False,
            },
            alias="compile_only",
        )
        pg.get_autocommit = lambda: False
        statements = []
        original = QuerySet._fetch_all

        def inspect(queryset):
            if queryset.model is Season and queryset.query.select_for_update:
                sql, _ = queryset.query.get_compiler(connection=pg).as_sql()
                statements.append(sql)
            return original(queryset)

        self.publish()
        with patch.object(QuerySet, "_fetch_all", inspect):
            response = self.client.get(self.url + "registration/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(statements)
        for sql in statements:
            self.assertIn("FOR UPDATE", sql)
            self.assertNotIn("LEFT OUTER JOIN", sql)
