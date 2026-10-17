from django.db import transaction, IntegrityError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from .models import Club, ClubMembership, ClubPost
from .views import member
from apps.competitions.models import SeasonParticipant
from apps.tracking.models import UserActivity
from apps.tracking.analytics import participant_analytics


class PrivacySerializer(serializers.Serializer):
    share_analytics = serializers.BooleanField()


class ClubPrivacyView(APIView):
    @transaction.atomic
    def patch(self, request, pk):
        club = get_object_or_404(Club.objects.select_for_update(), pk=pk)
        membership = member(club, request.user)
        serializer = PrivacySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership.share_analytics = serializer.validated_data["share_analytics"]
        membership.save(update_fields=["share_analytics"])
        return Response({"share_analytics": membership.share_analytics})


def analytics_member(request, club, user_id):
    member(club, request.user)
    target = get_object_or_404(
        ClubMembership.objects.select_related("user"), club=club, user_id=user_id
    )
    if target.user_id != request.user.id and not target.share_analytics:
        raise PermissionDenied("This member keeps their analytics private.")
    return target


class MemberProfileView(APIView):
    def get(self, request, pk, membership_id):
        club = get_object_or_404(Club, pk=pk)
        member(club, request.user)
        target = get_object_or_404(
            ClubMembership.objects.select_related("user"), pk=membership_id, club=club
        )
        allowed = target.user_id == request.user.id or target.share_analytics
        seasons = []
        if allowed:
            seasons = [
                {"id": p.season_id, "name": p.season.name}
                for p in SeasonParticipant.objects.filter(
                    user=target.user, season__competition__club=club
                ).select_related("season")
            ]
        response = Response(
            {
                "user_id": target.user_id,
                "display_name": target.user.get_full_name() or target.user.username,
                "username": target.user.username,
                "role": target.role,
                "analytics_available": allowed,
                "is_me": target.user_id == request.user.id,
                "seasons": seasons,
            }
        )

        response["Cache-Control"] = "private, no-store"
        return response


class ClubAnalyticsView(APIView):
    def get(self, request, pk):
        club = get_object_or_404(Club, pk=pk)
        serializer = AnalyticsQuery(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        user_id = values.get("user_id", request.user.id)
        target = analytics_member(request, club, user_id)
        participation = get_object_or_404(
            SeasonParticipant,
            user_id=target.user_id,
            season_id=values["season_id"],
            season__competition__club=club,
        )
        response = Response(participant_analytics(participation))
        response["Cache-Control"] = "private, no-store"
        return response


class AnalyticsQuery(serializers.Serializer):
    user_id = serializers.IntegerField(min_value=1, required=False)
    season_id = serializers.IntegerField(min_value=1)


class OwnSeasonAnalyticsView(APIView):
    def get(self, request, season_id):
        participation = get_object_or_404(
            SeasonParticipant, user=request.user, season_id=season_id
        )
        member(participation.season.competition.club, request.user)
        response = Response(participant_analytics(participation))
        response["Cache-Control"] = "private, no-store"
        return response


class PostInput(serializers.Serializer):
    content = serializers.CharField(
        max_length=3000, allow_blank=True, required=False, default=""
    )
    activity_id = serializers.IntegerField(min_value=1, required=False)
    include_activity = serializers.BooleanField(default=False)
    include_analytics = serializers.BooleanField(default=False)
    season_id = serializers.IntegerField(min_value=1, required=False)


class PostSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    author_id = serializers.IntegerField(read_only=True)
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = ClubPost
        fields = [
            "id",
            "content",
            "author_id",
            "author_name",
            "activity_snapshot",
            "analytics_snapshot",
            "created_at",
            "can_delete",
        ]

    def get_author_name(self, obj):
        return obj.author.get_full_name() or obj.author.username

    def get_can_delete(self, obj):
        return obj.author_id == self.context["request"].user.id or self.context["admin"]


class FeedPagination(PageNumberPagination):
    page_size = 20


class ClubFeedView(APIView):
    def get(self, request, pk):
        club = get_object_or_404(Club, pk=pk)
        membership = member(club, request.user)
        pager = FeedPagination()
        posts = pager.paginate_queryset(
            club.posts.select_related("author").all(), request
        )
        response = pager.get_paginated_response(
            PostSerializer(
                posts,
                many=True,
                context={"request": request, "admin": membership.role == "admin"},
            ).data
        )
        response["Cache-Control"] = "private, no-store"
        return response

    @transaction.atomic
    def post(self, request, pk):
        club = get_object_or_404(Club.objects.select_for_update(), pk=pk)
        membership = member(club, request.user)
        serializer = PostInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        activity = None
        activity_snapshot = None
        analytics_snapshot = None
        if values["include_activity"]:
            if not values.get("activity_id"):
                raise ValidationError("Choose your activity to share.")
            activity = get_object_or_404(
                UserActivity.objects.select_related(
                    "season_component__component", "participant__season__competition"
                ),
                pk=values["activity_id"],
                participant__user=request.user,
                participant__season__competition__club=club,
            )
            activity_snapshot = {
                "component": activity.season_component.name
                or activity.season_component.component.name,
                "date": str(activity.activity_date),
                "quantity": str(activity.actual_value),
                "unit": activity.season_component.metric,
                "points": str(activity.awarded_points),
                "achieved": activity.achieved,
            }
        if values["include_analytics"]:
            if not values.get("season_id"):
                raise ValidationError("Choose a season to share.")
            p = get_object_or_404(
                SeasonParticipant,
                user=request.user,
                season_id=values["season_id"],
                season__competition__club=club,
            )
            analytics_snapshot = participant_analytics(p)
        if (
            not values["content"].strip()
            and not activity_snapshot
            and not analytics_snapshot
        ):
            raise ValidationError(
                "Write a post or explicitly select an activity or analytics to share."
            )
        try:
            with transaction.atomic():
                post = ClubPost.objects.create(
                    club=club,
                    author=request.user,
                    content=values["content"].strip(),
                    activity=activity,
                    activity_snapshot=activity_snapshot,
                    analytics_snapshot=analytics_snapshot,
                )
        except IntegrityError:
            raise ValidationError("This activity has already been posted to the club.")
        return Response(
            PostSerializer(
                post, context={"request": request, "admin": membership.role == "admin"}
            ).data,
            status=201,
        )


class ClubPostDetailView(APIView):
    @transaction.atomic
    def delete(self, request, pk, post_id):
        club = get_object_or_404(Club.objects.select_for_update(), pk=pk)
        membership = member(club, request.user)
        post = get_object_or_404(ClubPost, pk=post_id, club=club)
        if post.author_id != request.user.id and membership.role != "admin":
            raise PermissionDenied(
                "Only the author or club admin can remove this post."
            )
        post.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
