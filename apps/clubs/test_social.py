from datetime import timedelta
from django.test import TestCase, override_settings
from django.utils import timezone
from . import tests as club_tests
from .models import ClubMembership, ClubPost
from apps.competitions.models import (
    Competition,
    Season,
    SeasonParticipant,
    SeasonSettings,
)


@override_settings(SECURE_SSL_REDIRECT=False)
class SocialTests(TestCase):
    def setUp(self):
        club_tests.ClubTests.setUp(self)
        competition = Competition.objects.create(club=self.club, name="Challenge")
        self.season = Season.objects.create(
            competition=competition,
            name="Season",
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=14),
        )
        SeasonSettings.objects.create(season=self.season)
        self.participant = SeasonParticipant.objects.create(
            season=self.season, user=self.user
        )
        self.analytics = (
            self.base + f"analytics/?user_id={self.user.id}&season_id={self.season.id}"
        )

    def test_default_private_even_from_admin(self):
        self.assertFalse(self.m.share_analytics)
        self.assertEqual(self.client.get(self.analytics).status_code, 403)
        response = self.client.get(self.base + f"members/{self.m.id}/profile/")
        self.assertFalse(response.data["analytics_available"])
        self.assertEqual(response.data["seasons"], [])
        self.assertNotIn("weight_kg", response.data)

    def test_consent_and_revocation(self):
        self.client.force_authenticate(self.user)
        self.assertEqual(
            self.client.patch(
                self.base + "privacy/", {"share_analytics": True}, format="json"
            ).status_code,
            200,
        )
        self.client.force_authenticate(self.admin)
        response = self.client.get(self.analytics)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.client.force_authenticate(self.user)
        self.client.patch(
            self.base + "privacy/", {"share_analytics": False}, format="json"
        )
        self.assertEqual(
            self.client.get(f"/api/seasons/{self.season.id}/analytics/").status_code,
            200,
        )
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(self.analytics).status_code, 403)

    def test_explicit_snapshot_does_not_enable_live_sharing(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            self.base + "posts/",
            {"include_analytics": True, "season_id": self.season.id},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.m.refresh_from_db()
        self.assertFalse(self.m.share_analytics)
        self.assertEqual(
            response.data["analytics_snapshot"]["season"]["id"], self.season.id
        )
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(self.base + "posts/").data["count"], 1)
        self.assertEqual(self.client.get(self.analytics).status_code, 403)

    def test_empty_or_forged_snapshot_rejected(self):
        response = self.client.post(
            self.base + "posts/",
            {"analytics_snapshot": {"secret": "forged"}},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ClubPost.objects.exists())

    def test_membership_and_delete_permissions(self):
        self.client.force_authenticate(self.user)
        response = self.client.post(
            self.base + "posts/", {"content": "A win"}, format="json"
        )
        post_id = response.data["id"]
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(self.base + "posts/").status_code, 403)
        membership = ClubMembership.objects.create(club=self.club, user=self.outsider)
        self.assertEqual(
            self.client.delete(self.base + f"posts/{post_id}/").status_code, 403
        )
        membership.delete()
        self.client.force_authenticate(self.admin)
        self.assertEqual(
            self.client.delete(self.base + f"posts/{post_id}/").status_code, 204
        )

    def test_cannot_publish_another_members_analytics(self):
        response = self.client.post(
            self.base + "posts/",
            {"include_analytics": True, "season_id": self.season.id},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

    def test_activity_snapshot_ownership_and_private_notes(self):
        from decimal import Decimal
        from apps.competitions.models import Component, SeasonComponent
        from apps.tracking.models import UserActivity

        component = Component.objects.create(name="Workout")
        rule = SeasonComponent.objects.create(
            season=self.season, component=component, max_points=25
        )
        activity = UserActivity.objects.create(
            participant=self.participant,
            season_component=rule,
            actual_value=1,
            activity="Private note",
            activity_date=timezone.localdate(),
            base_points=Decimal("8.33"),
            penalty_percent=0,
            awarded_points=Decimal("8.33"),
            target_days_snapshot=3,
            max_points_snapshot=25,
        )
        payload = {"include_activity": True, "activity_id": activity.id}
        self.assertEqual(
            self.client.post(self.base + "posts/", payload, format="json").status_code,
            404,
        )
        self.client.force_authenticate(self.user)
        response = self.client.post(self.base + "posts/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertNotIn("Private note", str(response.data))
        self.assertEqual(response.data["activity_snapshot"]["component"], "Workout")
        self.assertEqual(
            self.client.post(self.base + "posts/", payload, format="json").status_code,
            400,
        )

    def test_consent_does_not_cross_clubs(self):
        from .models import Club

        other = Club.objects.create(name="Another club")
        ClubMembership.objects.create(club=other, user=self.user, share_analytics=True)
        ClubMembership.objects.create(club=other, user=self.admin)
        self.assertEqual(self.client.get(self.analytics).status_code, 403)
        self.assertEqual(
            self.client.get(
                f"/api/clubs/{other.id}/analytics/?user_id={self.user.id}&season_id={self.season.id}"
            ).status_code,
            404,
        )
