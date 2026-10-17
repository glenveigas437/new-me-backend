import secrets
import string
from datetime import timedelta
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import UserRateThrottle
from .models import Club, ClubMembership, ClubCode
from .serializers import (
    ClubSerializer,
    MemberSerializer,
    CodeSerializer,
    CompetitionSerializer,
    JoinSerializer,
    CodeCreateSerializer,
    RoleSerializer,
)
from apps.competitions.models import Competition


class JoinThrottle(UserRateThrottle):
    rate = "10/min"
    scope = "club_join"


def member(club, user, admin=False):
    membership = ClubMembership.objects.filter(club=club, user=user).first()
    if not membership:
        raise PermissionDenied("You are not a member of this club.")
    if admin and membership.role != "admin":
        raise PermissionDenied("Club admin access is required.")
    return membership


def data(serializer, obj, request, many=False):
    return serializer(obj, many=many, context={"request": request}).data


def require_profile(user):
    if not user.profile_complete:
        raise ValidationError(
            {
                "profile": "Complete your profile before creating or joining a club.",
                "missing_fields": user.missing_profile_fields,
            }
        )


class ClubListCreateView(APIView):
    def get(self, request):
        clubs = Club.objects.filter(memberships__user=request.user).order_by(
            "name", "id"
        )
        return Response(data(ClubSerializer, clubs, request, many=True))

    @transaction.atomic
    def post(self, request):
        require_profile(request.user)
        serializer = ClubSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        club = serializer.save()
        ClubMembership.objects.create(club=club, user=request.user, role="admin")
        return Response(data(ClubSerializer, club, request), status=201)


class ClubDetailView(APIView):
    def get(self, request, pk):
        club = get_object_or_404(Club, pk=pk)
        member(club, request.user)
        return Response(data(ClubSerializer, club, request))

    @transaction.atomic
    def patch(self, request, pk):
        club = get_object_or_404(Club.objects.select_for_update(), pk=pk)
        member(club, request.user, True)
        serializer = ClubSerializer(
            club, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ClubJoinView(APIView):
    throttle_classes = [JoinThrottle]

    @transaction.atomic
    def post(self, request):
        require_profile(request.user)
        serializer = JoinSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        code = ClubCode.objects.filter(code=serializer.validated_data["code"]).first()
        if not code:
            raise ValidationError({"code": "Invalid or expired club code."})
        # Lock the club before checking its code or changing membership; all club mutations share this lock.
        club = Club.objects.select_for_update().get(pk=code.club_id)
        code.refresh_from_db()
        if code.revoked_at or code.expires_at <= timezone.now():
            raise ValidationError({"code": "Invalid or expired club code."})
        membership, created = ClubMembership.objects.get_or_create(
            club=club, user=request.user, defaults={"role": "member"}
        )
        return Response(
            data(ClubSerializer, club, request), status=201 if created else 200
        )


class ClubMembersView(APIView):
    def get(self, request, pk):
        club = get_object_or_404(Club, pk=pk)
        member(club, request.user)
        return Response(
            data(
                MemberSerializer,
                club.memberships.select_related("user").order_by("joined_at", "id"),
                request,
                True,
            )
        )


class ClubMemberDetailView(APIView):
    def locked(self, request, pk, membership_id):
        club = get_object_or_404(Club.objects.select_for_update(), pk=pk)
        member(club, request.user, True)
        target = get_object_or_404(ClubMembership, pk=membership_id, club=club)
        return club, target

    def protect_last_admin(self, club, target):
        if (
            target.role == "admin"
            and club.memberships.filter(role="admin").count() <= 1
        ):
            raise ValidationError(
                "Promote another member before removing or demoting the last admin."
            )

    @transaction.atomic
    def patch(self, request, pk, membership_id):
        club, target = self.locked(request, pk, membership_id)
        serializer = RoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role = serializer.validated_data["role"]
        if role == "member":
            self.protect_last_admin(club, target)
        target.role = role
        target.save(update_fields=["role"])
        return Response(data(MemberSerializer, target, request))

    @transaction.atomic
    def delete(self, request, pk, membership_id):
        club, target = self.locked(request, pk, membership_id)
        self.protect_last_admin(club, target)
        # Preserve historical records, but all season/activity APIs now require a current membership.
        target.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ClubCodesView(APIView):
    def get(self, request, pk):
        club = get_object_or_404(Club, pk=pk)
        member(club, request.user, True)
        return Response(
            data(
                CodeSerializer,
                club.codes.filter(
                    revoked_at__isnull=True, expires_at__gt=timezone.now()
                ),
                request,
                True,
            )
        )

    @transaction.atomic
    def post(self, request, pk):
        club = get_object_or_404(Club.objects.select_for_update(), pk=pk)
        member(club, request.user, True)
        serializer = CodeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        now = timezone.now()
        club.codes.filter(revoked_at__isnull=True).update(revoked_at=now)
        alphabet = string.ascii_uppercase + string.digits
        code = "".join(secrets.choice(alphabet) for _ in range(12))
        while ClubCode.objects.filter(code=code).exists():
            code = "".join(secrets.choice(alphabet) for _ in range(12))
        record = ClubCode.objects.create(
            club=club,
            code=code,
            created_by=request.user,
            expires_at=now + timedelta(days=serializer.validated_data["valid_days"]),
        )
        return Response(data(CodeSerializer, record, request), status=201)


class ClubCodeDetailView(APIView):
    @transaction.atomic
    def delete(self, request, pk, code_id):
        club = get_object_or_404(Club.objects.select_for_update(), pk=pk)
        member(club, request.user, True)
        record = get_object_or_404(ClubCode, club=club, pk=code_id)
        record.revoked_at = timezone.now()
        record.save(update_fields=["revoked_at"])
        return Response(status=204)


class ClubCompetitionsView(APIView):
    def get(self, request, pk):
        club = get_object_or_404(Club, pk=pk)
        member(club, request.user)
        return Response(
            data(
                CompetitionSerializer,
                club.competitions.order_by("name", "id"),
                request,
                True,
            )
        )

    @transaction.atomic
    def post(self, request, pk):
        club = get_object_or_404(Club.objects.select_for_update(), pk=pk)
        member(club, request.user, True)
        serializer = CompetitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        competition = serializer.save(club=club)
        return Response(data(CompetitionSerializer, competition, request), status=201)


class ClubCompetitionDetailView(APIView):
    @transaction.atomic
    def patch(self, request, pk, competition_id):
        club = get_object_or_404(Club.objects.select_for_update(), pk=pk)
        member(club, request.user, True)
        competition = get_object_or_404(Competition, pk=competition_id, club=club)
        serializer = CompetitionSerializer(competition, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
