from datetime import timedelta
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from apps.accounts.models import User
from apps.competitions.models import (
    Competition,
    Season,
    SeasonParticipant,
    SeasonSettings,
)
from .models import Club, ClubMembership, ClubCode


@override_settings(SECURE_SSL_REDIRECT=False)
class ClubTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin", email="a@example.test", password="Strong!45678"
        )
        self.user = User.objects.create_user(
            username="member", email="b@example.test", password="Strong!45678"
        )
        self.outsider = User.objects.create_user(
            username="outsider", email="c@example.test", password="Strong!45678"
        )
        from datetime import date

        for user in [self.admin, self.user, self.outsider]:
            user.first_name = user.username
            user.last_name = "Tester"
            user.date_of_birth = date(1995, 1, 1)
            user.height_cm = 175
            user.weight_kg = 75
            user.save()
        self.club = Club.objects.create(name="Fitness")
        self.a = ClubMembership.objects.create(
            club=self.club, user=self.admin, role="admin"
        )
        self.m = ClubMembership.objects.create(club=self.club, user=self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.base = f"/api/clubs/{self.club.id}/"

    def test_creation_makes_creator_admin(self):
        r = self.client.post("/api/clubs/", {"name": "New Club"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(
            ClubMembership.objects.get(club_id=r.data["id"], user=self.admin).role,
            "admin",
        )
        self.assertFalse(User.objects.get(pk=self.admin.pk).is_staff)

    def test_join_and_duplicate_join(self):
        code = self.client.post(self.base + "codes/", {}).data["code"]
        self.client.force_authenticate(self.outsider)
        self.assertEqual(
            self.client.post("/api/clubs/join/", {"code": code.lower()}).status_code,
            201,
        )
        self.assertEqual(
            self.client.post("/api/clubs/join/", {"code": code}).status_code, 200
        )
        self.assertEqual(
            ClubMembership.objects.filter(user=self.outsider, club=self.club).count(), 1
        )

    def test_expiry_rotation_revocation(self):
        old = self.client.post(self.base + "codes/", {}).data["code"]
        new = self.client.post(self.base + "codes/", {"valid_days": 1}).data
        self.client.force_authenticate(self.outsider)
        self.assertEqual(
            self.client.post("/api/clubs/join/", {"code": old}).status_code, 400
        )
        ClubCode.objects.filter(pk=new["id"]).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(
            self.client.post("/api/clubs/join/", {"code": new["code"]}).status_code, 400
        )
        self.client.force_authenticate(self.admin)
        code = self.client.post(self.base + "codes/", {}).data
        self.assertEqual(
            self.client.delete(self.base + f"codes/{code['id']}/").status_code, 204
        )
        self.client.force_authenticate(self.outsider)
        self.assertEqual(
            self.client.post("/api/clubs/join/", {"code": code["code"]}).status_code,
            400,
        )

    def test_members_cannot_administer_or_see_codes(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.patch(self.base, {"name": "Bad"}).status_code, 403)
        self.assertEqual(self.client.get(self.base + "codes/").status_code, 403)
        self.assertEqual(self.client.post(self.base + "codes/", {}).status_code, 403)
        self.assertEqual(
            self.client.post(self.base + "competitions/", {"name": "Bad"}).status_code,
            403,
        )
        self.assertEqual(
            self.client.patch(
                self.base + f"members/{self.m.id}/", {"role": "admin"}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.delete(self.base + f"members/{self.a.id}/").status_code, 403
        )

    def test_promoted_member_can_manage_club(self):
        self.assertEqual(
            self.client.patch(
                self.base + f"members/{self.m.id}/", {"role": "admin"}
            ).status_code,
            200,
        )
        self.client.force_authenticate(self.user)
        self.assertEqual(
            self.client.patch(
                self.base,
                {"name": "Renamed", "settings_data": {"note": "hi"}},
                format="json",
            ).status_code,
            200,
        )
        r = self.client.post(self.base + "competitions/", {"name": "Challenge"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(
            self.client.patch(
                self.base + f"competitions/{r.data['id']}/", {"name": "New name"}
            ).status_code,
            200,
        )

    def test_last_admin_protection(self):
        self.assertEqual(
            self.client.delete(self.base + f"members/{self.a.id}/").status_code, 400
        )
        self.assertEqual(
            self.client.patch(
                self.base + f"members/{self.a.id}/", {"role": "member"}
            ).status_code,
            400,
        )
        self.client.patch(self.base + f"members/{self.m.id}/", {"role": "admin"})
        self.assertEqual(
            self.client.delete(self.base + f"members/{self.a.id}/").status_code, 204
        )

    def test_cross_club_membership_and_competition_blocked(self):
        club = Club.objects.create(name="Other")
        membership = ClubMembership.objects.create(club=club, user=self.outsider)
        competition = Competition.objects.create(club=club, name="Other challenge")
        self.assertEqual(
            self.client.delete(self.base + f"members/{membership.id}/").status_code, 404
        )
        self.assertEqual(
            self.client.patch(
                self.base + f"competitions/{competition.id}/", {"name": "bad"}
            ).status_code,
            404,
        )

    def test_removed_member_loses_season_access(self):
        c = Competition.objects.create(club=self.club, name="Challenge")
        season = Season.objects.create(
            competition=c,
            name="Season",
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=7),
        )
        SeasonSettings.objects.create(season=season)
        p = SeasonParticipant.objects.create(season=season, user=self.user)
        self.assertEqual(
            self.client.delete(self.base + f"members/{self.m.id}/").status_code, 204
        )
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get("/api/seasons/").data, [])
        self.assertEqual(
            self.client.get(f"/api/seasons/{season.id}/leaderboard/").status_code, 404
        )
        self.assertEqual(self.client.get("/api/activities/").data, [])
        self.assertEqual(self.client.get("/api/measurements/").data, [])
        self.assertTrue(SeasonParticipant.objects.filter(pk=p.pk).exists())
        self.assertEqual(self.client.get(self.base).status_code, 403)

    def test_outsider_cannot_list_members(self):
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get("/api/clubs/").data, [])
        self.assertEqual(self.client.get(self.base + "members/").status_code, 403)

    def test_invalid_json_and_days(self):
        self.assertEqual(
            self.client.patch(
                self.base, {"settings_data": []}, format="json"
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(self.base + "codes/", {"valid_days": 31}).status_code, 400
        )
