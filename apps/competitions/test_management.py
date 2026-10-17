from datetime import timedelta, time, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo
from django.test import TestCase, override_settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.test import APIClient
from apps.accounts.models import User
from apps.clubs.models import Club, ClubMembership
from apps.tracking.models import UserActivity
from apps.tracking.services import calculate_activity_points
from .models import (
    Competition,
    Season,
    SeasonSettings,
    Component,
    SeasonComponent,
    SeasonParticipant,
    ParticipantComponentTarget,
)


@override_settings(SECURE_SSL_REDIRECT=False)
class SeasonManagementTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="owner", email="owner@example.test", password="Strong!123456"
        )
        self.member = User.objects.create_user(
            username="member", email="member@example.test", password="Strong!123456"
        )
        self.outsider = User.objects.create_user(
            username="outsider", email="out@example.test", password="Strong!123456"
        )
        self.club = Club.objects.create(name="Fitness Club")
        ClubMembership.objects.create(club=self.club, user=self.admin, role="admin")
        ClubMembership.objects.create(club=self.club, user=self.member)
        self.competition = Competition.objects.create(
            club=self.club, name="Fitness Challenge"
        )
        self.root = (
            f"/api/clubs/{self.club.id}/competitions/{self.competition.id}/seasons/"
        )
        self.day = timezone.localdate()
        self.season = Season.objects.create(
            competition=self.competition,
            name="Season 1",
            start_date=self.day,
            end_date=self.day + timedelta(days=89),
        )
        SeasonSettings.objects.create(season=self.season)
        self.rules = self.root + f"{self.season.id}/rules/"
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def payload(self, name="Workouts", deps=None):
        return {
            "name": name,
            "points": "25.00",
            "type": "consistency",
            "cutoff": "21:00",
            "metric": "time",
            "depends_on": deps or [],
        }

    def rule(self, name, deps=None):
        r = self.client.post(self.rules, self.payload(name, deps), format="json")
        self.assertEqual(r.status_code, 201, r.data)
        return r.data

    def test_admin_creates_season_and_default_settings(self):
        r = self.client.post(
            self.root,
            {
                "name": "Season 2",
                "start_date": str(self.day),
                "end_date": str(self.day + timedelta(days=90)),
            },
        )
        self.assertEqual(r.status_code, 201)
        self.assertTrue(SeasonSettings.objects.filter(season_id=r.data["id"]).exists())

    def test_invalid_dates(self):
        r = self.client.post(
            self.root,
            {
                "name": "Bad",
                "start_date": str(self.day),
                "end_date": str(self.day - timedelta(days=1)),
            },
        )
        self.assertEqual(r.status_code, 400)

    def test_edit_season_dates(self):
        r = self.client.patch(
            self.root + f"{self.season.id}/",
            {"name": "Renamed", "end_date": str(self.day + timedelta(days=99))},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["name"], "Renamed")

    def test_member_read_only(self):
        self.rule("Workouts")
        self.client.force_authenticate(self.member)
        self.assertEqual(self.client.get(self.root).status_code, 200)
        self.assertEqual(self.client.get(self.rules).status_code, 200)
        self.assertEqual(
            self.client.post(self.rules, self.payload(), format="json").status_code, 403
        )
        self.assertEqual(self.client.post(self.root, {}).status_code, 403)

    def test_outsider_denied(self):
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(self.root).status_code, 403)
        self.assertEqual(self.client.get(self.rules).status_code, 403)

    def test_fields_roundtrip(self):
        data = self.rule("Hydration")
        self.assertEqual(data["cutoff"], "21:00:00")
        self.assertEqual(data["points"], "25.00")
        row = SeasonComponent.objects.get(pk=data["id"])
        self.assertEqual(row.season_id, self.season.id)
        self.assertEqual(row.metric, "time")

    def test_dependencies_and_direct_cycle(self):
        workouts = self.rule("Workouts")
        nutrition = self.rule("Nutrition")
        hydration = self.rule("Hydration")
        activity = self.rule(
            "Activity", [workouts["id"], nutrition["id"], hydration["id"]]
        )
        self.assertCountEqual(
            activity["dependency_names"], ["Workouts", "Nutrition", "Hydration"]
        )
        r = self.client.patch(
            self.rules + f"{workouts['id']}/",
            {"depends_on": [activity["id"]]},
            format="json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("Circular dependency", str(r.data))
        self.assertFalse(
            SeasonComponent.objects.get(pk=workouts["id"]).depends_on.exists()
        )

    def test_indirect_cycle(self):
        a = self.rule("A")
        b = self.rule("B", [a["id"]])
        c = self.rule("C", [b["id"]])
        r = self.client.patch(
            self.rules + f"{a['id']}/", {"depends_on": [c["id"]]}, format="json"
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("Circular dependency", str(r.data))

    def test_self_dependency(self):
        a = self.rule("A")
        r = self.client.patch(
            self.rules + f"{a['id']}/", {"depends_on": [a["id"]]}, format="json"
        )
        self.assertEqual(r.status_code, 400)

    def test_cross_season_dependency(self):
        other = Season.objects.create(
            competition=self.competition,
            name="Other",
            start_date=self.day,
            end_date=self.day,
        )
        c = Component.objects.create(code="other", name="Other")
        rule = SeasonComponent.objects.create(
            season=other, component=c, name="Other", max_points=5
        )
        r = self.client.post(self.rules, self.payload("A", [rule.id]), format="json")
        self.assertEqual(r.status_code, 400)

    def test_same_name_in_different_seasons_allowed(self):
        self.rule("Workouts")
        self.assertEqual(
            self.client.post(
                self.rules, self.payload("workouts"), format="json"
            ).status_code,
            400,
        )
        other = self.client.post(
            self.root,
            {"name": "Other", "start_date": str(self.day), "end_date": str(self.day)},
        ).data
        r = self.client.post(
            self.root + f"{other['id']}/rules/", self.payload("Workouts"), format="json"
        )
        self.assertEqual(r.status_code, 201)

    def test_personal_improvement_and_nullable_cutoff(self):
        p = self.payload("Weight gain")
        p.update(type="personal_improvement", metric="kgs", cutoff=None)
        r = self.client.post(self.rules, p, format="json")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data["type"], "personal_improvement")
        self.assertIsNone(r.data["cutoff"])

    def test_negative_points_invalid_time_and_type(self):
        for field, value in [
            ("points", "-1"),
            ("cutoff", "25:99"),
            ("type", "invalid"),
            ("metric", ""),
        ]:
            p = self.payload()
            p[field] = value
            self.assertEqual(
                self.client.post(self.rules, p, format="json").status_code, 400
            )

    def test_edited_edges_replace_old_edges(self):
        a = self.rule("A")
        b = self.rule("B", [a["id"]])
        self.assertEqual(
            self.client.patch(
                self.rules + f"{b['id']}/", {"depends_on": []}, format="json"
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.patch(
                self.rules + f"{a['id']}/", {"depends_on": [b["id"]]}, format="json"
            ).status_code,
            200,
        )

    def test_delete_protects_dependents(self):
        a = self.rule("A")
        b = self.rule("B", [a["id"]])
        self.assertEqual(
            self.client.delete(self.rules + f"{a['id']}/").status_code, 400
        )
        self.assertEqual(
            self.client.delete(self.rules + f"{b['id']}/").status_code, 204
        )
        self.assertEqual(
            self.client.delete(self.rules + f"{a['id']}/").status_code, 204
        )

    def test_locked_season_rejects_writes(self):
        a = self.rule("A")
        self.season.settings.locked_at = timezone.now()
        self.season.settings.save()
        self.assertEqual(
            self.client.post(self.rules, self.payload("B"), format="json").status_code,
            400,
        )
        self.assertEqual(
            self.client.patch(self.rules + f"{a['id']}/", {"points": "40"}).status_code,
            400,
        )
        self.assertEqual(
            self.client.delete(self.rules + f"{a['id']}/").status_code, 400
        )
        self.assertEqual(
            self.client.patch(
                self.root + f"{self.season.id}/", {"name": "No"}
            ).status_code,
            400,
        )

    def test_cannot_access_other_club_season_by_url(self):
        club = Club.objects.create(name="Private")
        comp = Competition.objects.create(club=club, name="Private")
        s = Season.objects.create(
            competition=comp, name="Private", start_date=self.day, end_date=self.day
        )
        self.assertEqual(self.client.get(self.root + f"{s.id}/rules/").status_code, 404)

    def test_model_m2m_also_rejects_cycle(self):
        a = self.rule("A")
        b = self.rule("B", [a["id"]])
        with self.assertRaises(ValidationError):
            with transaction.atomic():
                SeasonComponent.objects.get(pk=a["id"]).depends_on.add(b["id"])

    def test_rule_cutoff_used_for_late_deduction(self):
        a = self.rule("A")
        rule = SeasonComponent.objects.get(pk=a["id"])
        p = SeasonParticipant.objects.create(season=self.season, user=self.admin)
        target = ParticipantComponentTarget.objects.create(
            participant=p, season_component=rule, target_days_per_week=5
        )
        settings = self.season.settings
        settings.late_penalty_percent = 20
        settings.save()
        now = datetime.combine(self.day, time(22), tzinfo=ZoneInfo("Asia/Kolkata"))
        self.assertEqual(
            calculate_activity_points(target, self.day, now)[2], Decimal("4")
        )
