from pathlib import Path
from django.conf import settings
from django.contrib import admin
from django.http import FileResponse, HttpResponse, Http404
from django.urls import path, re_path, include
from apps.accounts.views import (
    RegisterView,
    ProfileView,
    LoginView,
    RefreshView,
    LogoutView,
    CsrfView,
)
from apps.competitions.views import SeasonListView, LeaderboardView
from apps.tracking.views import ActivityListCreateView, MeasurementListCreateView


def frontend(request, path=""):
    root = settings.FRONTEND_DIST_DIR
    if path.startswith(("api/", "admin/", "static/")):
        raise Http404
    if path in [
        "sw.js",
        "manifest.webmanifest",
        "logo.svg",
        "icon-192.png",
        "icon-512.png",
        "apple-touch-icon.png",
    ]:
        file = root / path
        if not file.exists():
            raise Http404
        types = {
            ".js": "application/javascript",
            ".webmanifest": "application/manifest+json",
            ".svg": "image/svg+xml",
            ".png": "image/png",
        }
        response = FileResponse(file.open("rb"), content_type=types.get(file.suffix))
        response["Cache-Control"] = "no-cache"
        return response
    if not (root / "index.html").exists():
        return HttpResponse(
            "BetterMe API is running. Start Vite on port 5173, or build the frontend.",
            content_type="text/plain",
        )
    response = FileResponse((root / "index.html").open("rb"), content_type="text/html")
    response["Cache-Control"] = "no-cache"
    return response


from apps.competitions.enrollment import (
    RegistrationConfigView,
    PublishSeasonView,
    EnrollSeasonView,
)

from apps.clubs.social import OwnSeasonAnalyticsView

urlpatterns = [
    path("api/seasons/<int:season_id>/analytics/",OwnSeasonAnalyticsView.as_view()),
    path("api/seasons/<int:season_id>/registration/", RegistrationConfigView.as_view()),
    path("api/seasons/<int:season_id>/publish/", PublishSeasonView.as_view()),
    path("api/seasons/<int:season_id>/enroll/", EnrollSeasonView.as_view()),
    path("admin/", admin.site.urls),
    path("api/auth/csrf/", CsrfView.as_view()),
    path("api/auth/register/", RegisterView.as_view()),
    path("api/auth/login/", LoginView.as_view()),
    path("api/auth/refresh/", RefreshView.as_view()),
    path("api/auth/logout/", LogoutView.as_view()),
    path("api/auth/me/", ProfileView.as_view()),
    path("api/clubs/", include("apps.clubs.urls")),
    path("api/seasons/", SeasonListView.as_view()),
    path("api/seasons/<int:pk>/leaderboard/", LeaderboardView.as_view()),
    path("api/activities/", ActivityListCreateView.as_view()),
    path("api/measurements/", MeasurementListCreateView.as_view()),
    re_path(r"^(?P<path>.*)$", frontend),
]
