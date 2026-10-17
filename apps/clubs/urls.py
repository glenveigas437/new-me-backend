from django.urls import path
from .views import (
    ClubListCreateView,
    ClubDetailView,
    ClubJoinView,
    ClubMembersView,
    ClubMemberDetailView,
    ClubCodesView,
    ClubCodeDetailView,
    ClubCompetitionsView,
    ClubCompetitionDetailView,
)

from apps.competitions.management_views import (
    CompetitionSeasonsView,
    ManagedSeasonDetailView,
    SeasonRulesView,
    SeasonRuleDetailView,
)

from .social import (
    ClubPrivacyView,
    MemberProfileView,
    ClubAnalyticsView,
    ClubFeedView,
    ClubPostDetailView,
)

urlpatterns = [
    path("<int:pk>/privacy/", ClubPrivacyView.as_view()),
    path("<int:pk>/members/<int:membership_id>/profile/", MemberProfileView.as_view()),
    path("<int:pk>/analytics/", ClubAnalyticsView.as_view()),
    path("<int:pk>/posts/", ClubFeedView.as_view()),
    path("<int:pk>/posts/<int:post_id>/", ClubPostDetailView.as_view()),
    path(
        "<int:pk>/competitions/<int:competition_id>/seasons/",
        CompetitionSeasonsView.as_view(),
    ),
    path(
        "<int:pk>/competitions/<int:competition_id>/seasons/<int:season_id>/",
        ManagedSeasonDetailView.as_view(),
    ),
    path(
        "<int:pk>/competitions/<int:competition_id>/seasons/<int:season_id>/rules/",
        SeasonRulesView.as_view(),
    ),
    path(
        "<int:pk>/competitions/<int:competition_id>/seasons/<int:season_id>/rules/<int:rule_id>/",
        SeasonRuleDetailView.as_view(),
    ),
    path("", ClubListCreateView.as_view()),
    path("join/", ClubJoinView.as_view()),
    path("<int:pk>/", ClubDetailView.as_view()),
    path("<int:pk>/members/", ClubMembersView.as_view()),
    path("<int:pk>/members/<int:membership_id>/", ClubMemberDetailView.as_view()),
    path("<int:pk>/codes/", ClubCodesView.as_view()),
    path("<int:pk>/codes/<int:code_id>/", ClubCodeDetailView.as_view()),
    path("<int:pk>/competitions/", ClubCompetitionsView.as_view()),
    path(
        "<int:pk>/competitions/<int:competition_id>/",
        ClubCompetitionDetailView.as_view(),
    ),
]
