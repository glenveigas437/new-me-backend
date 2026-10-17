from datetime import date, datetime, timedelta, time
from decimal import Decimal as D
from zoneinfo import ZoneInfo
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from apps.accounts.models import User
from apps.clubs.models import Club, ClubMembership
from apps.competitions.models import *
from .models import *
from .services import calculate_activity_points, score_participant, goal_score


@override_settings(SECURE_SSL_REDIRECT=False)
class BetterMeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="alex",
            email="alex@example.test",
            password="Strong-test!142",
            height_cm=175,
            weight_kg=75,
        )
        self.other = User.objects.create_user(
            username="other", email="other@example.test", password="Strong-test!142"
        )
        self.club = Club.objects.create(name="Test Club")
        ClubMembership.objects.create(user=self.other, club=self.club)
        ClubMembership.objects.create(user=self.user, club=self.club)
        competition = Competition.objects.create(
            club=self.club, name="Test Competition"
        )
        self.day = timezone.localdate()
        self.season = Season.objects.create(
            competition=competition,
            name="Test",
            start_date=self.day - timedelta(days=7),
            end_date=self.day + timedelta(days=6),
        )
        self.settings = SeasonSettings.objects.create(
            season=self.season, late_penalty_percent=20, locked_at=timezone.now()
        )
        self.p = SeasonParticipant.objects.create(user=self.user, season=self.season)
        self.p2 = SeasonParticipant.objects.create(user=self.other, season=self.season)
        component = Component.objects.create(code="workout", name="Workout")
        self.rule = SeasonComponent.objects.create(
            season=self.season, component=component, max_points=25
        )
        self.target = ParticipantComponentTarget.objects.create(
            participant=self.p, season_component=self.rule, target_days_per_week=5
        )
        for n in range(2):
            SeasonPeriod.objects.create(
                season=self.season,
                number=n + 1,
                start_date=self.season.start_date + timedelta(days=n * 7),
                end_date=self.season.start_date + timedelta(days=n * 7 + 6),
            )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def add_log(self, day, points=5, penalty=0):
        return UserActivity.objects.create(
            participant=self.p,
            season_component=self.rule,
            activity_date=day,
            base_points=5,
            penalty_percent=penalty,
            awarded_points=points,
            target_days_snapshot=5,
            max_points_snapshot=25,
        )

    def test_bmi(self):
        self.assertEqual(self.user.bmi, D("24.5"))

    def test_bmi_missing(self):
        self.assertIsNone(self.other.bmi)

    def test_requires_authentication(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get("/api/activities/").status_code, 401)

    def test_jwt_login_and_private_profile(self):
        c = APIClient()
        r = c.post(
            "/api/auth/login/", {"username": "alex", "password": "Strong-test!142"}
        )
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("refresh", r.data)
        self.assertTrue(r.cookies["betterme_refresh"]["httponly"])
        c.credentials(HTTP_AUTHORIZATION="Bearer " + r.data["access"])
        self.assertEqual(c.get("/api/auth/me/").data["id"], self.user.id)

    def test_refresh_and_logout_revokes_refresh(self):
        c = APIClient()
        c.post("/api/auth/login/", {"username": "alex", "password": "Strong-test!142"})
        self.assertEqual(c.post("/api/auth/refresh/").status_code, 200)
        c.post("/api/auth/logout/")
        self.assertEqual(c.post("/api/auth/refresh/").status_code, 401)

    def test_login_requires_csrf(self):
        c = APIClient(enforce_csrf_checks=True)
        self.assertEqual(
            c.post(
                "/api/auth/login/", {"username": "alex", "password": "Strong-test!142"}
            ).status_code,
            403,
        )
        c.get("/api/auth/csrf/")
        c.credentials(HTTP_X_CSRFTOKEN=c.cookies["csrftoken"].value)
        self.assertEqual(
            c.post(
                "/api/auth/login/", {"username": "alex", "password": "Strong-test!142"}
            ).status_code,
            200,
        )

    def test_weak_registration_password(self):
        r = self.client.post(
            "/api/auth/register/",
            {"username": "new", "email": "new@example.test", "password": "12345678"},
        )
        self.assertEqual(r.status_code, 400)

    def test_points_at_deadline(self):
        at = datetime.combine(
            self.day, time(23, 59, 59), tzinfo=ZoneInfo("Asia/Kolkata")
        )
        self.assertEqual(
            calculate_activity_points(self.target, self.day, at), (D(5), D(0), D(5))
        )
        self.assertEqual(
            calculate_activity_points(self.target, self.day, at + timedelta(seconds=1))[
                2
            ],
            D(4),
        )

    def test_six_days_capped_and_missing_period_zero(self):
        for n in range(6):
            self.add_log(self.season.start_date + timedelta(days=n))
        self.assertEqual(score_participant(self.p)["consistency"], "12.50")

    def test_extra_timely_day_replaces_late_day(self):
        for n in range(5):
            self.add_log(self.season.start_date + timedelta(days=n), 4, 20)
        self.add_log(self.season.start_date + timedelta(days=5), 5)
        self.assertEqual(score_participant(self.p)["consistency"], "10.50")

    def test_create_duplicate_and_future(self):
        payload = {
            "participant": self.p.id,
            "season_component": self.rule.id,
            "activity_date": str(self.day),
        }
        self.assertEqual(self.client.post("/api/activities/", payload).status_code, 201)
        self.assertEqual(self.client.post("/api/activities/", payload).status_code, 400)
        payload["activity_date"] = str(self.day + timedelta(days=1))
        self.assertEqual(self.client.post("/api/activities/", payload).status_code, 400)

    def test_cannot_log_for_someone_else(self):
        r = self.client.post(
            "/api/activities/",
            {
                "participant": self.p2.id,
                "season_component": self.rule.id,
                "activity_date": str(self.day),
            },
        )
        self.assertEqual(r.status_code, 400)

    def test_private_log_filter(self):
        self.add_log(self.day)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get("/api/activities/").data, [])

    def test_goal_bands_and_lower_is_better(self):
        g = ParticipantGoal.objects.create(
            participant=self.p,
            goal_type="body",
            description="Waist",
            baseline_value=100,
            target_value=90,
            unit="cm",
            method="Tape",
            locked_at=timezone.now(),
        )
        m = GoalMeasurement.objects.create(goal=g, value=100, measurement_date=self.day)
        for value, expected in [
            (101, 0),
            (100, 0),
            (D("99.95"), 3),
            (D("97.5"), 6),
            (95, 9),
            (D("92.5"), 12),
            (90, 15),
            (89, 15),
        ]:
            m.value = value
            m.save()
            self.assertEqual(goal_score(g), expected)

    def test_goal_privacy(self):
        g = ParticipantGoal.objects.create(
            participant=self.p2,
            goal_type="fitness",
            description="Run",
            baseline_value=35,
            target_value=30,
            unit="min",
            method="Route",
            locked_at=timezone.now(),
        )
        self.assertEqual(
            self.client.post(
                "/api/measurements/",
                {"goal": g.id, "value": "33", "measurement_date": str(self.day)},
            ).status_code,
            400,
        )

    def test_leaderboard_no_measurements_and_shared_rank(self):
        r = self.client.get(f"/api/seasons/{self.season.id}/leaderboard/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x["rank"] for x in r.data], [1, 1])
        self.assertNotIn("weight_kg", str(r.data))
        self.assertNotIn("baseline", str(r.data))

    def test_nonmember_cannot_see_leaderboard(self):
        stranger = User.objects.create_user(
            username="stranger", email="stranger@example.test", password="Unrelated!142"
        )
        self.client.force_authenticate(stranger)
        self.assertEqual(
            self.client.get(f"/api/seasons/{self.season.id}/leaderboard/").status_code,
            404,
        )

    def test_invalid_measurements(self):
        self.assertEqual(
            self.client.patch("/api/auth/me/", {"height_cm": 0}).status_code, 400
        )
