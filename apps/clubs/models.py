from django.conf import settings
from django.db import models


class Club(models.Model):
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=60, default="fitness")
    description = models.TextField(blank=True)
    settings_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class ClubMembership(models.Model):
    share_analytics = models.BooleanField(default=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(
        max_length=12,
        choices=[("admin", "Admin"), ("member", "Member")],
        default="member",
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "club"], name="unique_club_membership"
            )
        ]


class ClubCode(models.Model):
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="codes")
    code = models.CharField(max_length=16, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "club_codes"
        ordering = ["-created_at"]


class ClubPost(models.Model):
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="posts")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="club_posts"
    )
    content = models.TextField(blank=True, max_length=3000)
    activity = models.ForeignKey(
        "tracking.UserActivity", on_delete=models.SET_NULL, null=True, blank=True
    )
    activity_snapshot = models.JSONField(null=True, blank=True)
    analytics_snapshot = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["club", "author", "activity"],
                condition=models.Q(activity__isnull=False),
                name="one_post_per_activity",
            )
        ]
