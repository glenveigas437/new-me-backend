from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from apps.clubs.models import Club
from apps.clubs.views import member
from .models import Competition, Season, SeasonSettings, SeasonComponent
from .management_serializers import ManagedSeasonSerializer, SeasonRuleSerializer


def competition_for(request, club_id, competition_id, admin=False, lock=False):
    club = get_object_or_404(
        Club.objects.select_for_update() if lock else Club.objects, pk=club_id
    )
    member(club, request.user, admin)
    return get_object_or_404(Competition, pk=competition_id, club=club)


def season_for(request, club_id, competition_id, season_id, admin=False, lock=False):
    comp = competition_for(request, club_id, competition_id, admin, lock)
    return get_object_or_404(
        Season.objects.select_for_update() if lock else Season.objects,
        pk=season_id,
        competition=comp,
    )


def require_editable(season):
    if season.participants.filter(registration_locked_at__isnull=False).exists():
        raise ValidationError(
            "Registered participants have locked this season configuration."
        )
    if hasattr(season, "settings") and season.settings.locked_at:
        raise ValidationError(
            "Season rules are locked. Changes require an audited organizer correction."
        )
    if season.components.filter(useractivity__isnull=False).exists():
        raise ValidationError(
            "Scored activities already exist. Rules cannot be changed silently."
        )


def rule_data(rule):
    return SeasonRuleSerializer(rule).data


class CompetitionSeasonsView(APIView):
    def get(self, request, pk, competition_id):
        comp = competition_for(request, pk, competition_id)
        return Response(
            ManagedSeasonSerializer(
                comp.seasons.order_by("-start_date", "id"), many=True
            ).data
        )

    @transaction.atomic
    def post(self, request, pk, competition_id):
        comp = competition_for(request, pk, competition_id, True, True)
        serializer = ManagedSeasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        season = serializer.save(competition=comp)
        SeasonSettings.objects.create(season=season)
        return Response(ManagedSeasonSerializer(season).data, status=201)


class ManagedSeasonDetailView(APIView):
    def get(self, request, pk, competition_id, season_id):
        return Response(
            ManagedSeasonSerializer(
                season_for(request, pk, competition_id, season_id)
            ).data
        )

    @transaction.atomic
    def patch(self, request, pk, competition_id, season_id):
        season = season_for(request, pk, competition_id, season_id, True, True)
        require_editable(season)
        serializer = ManagedSeasonSerializer(season, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class SeasonRulesView(APIView):
    def get(self, request, pk, competition_id, season_id):
        season = season_for(request, pk, competition_id, season_id)
        return Response(
            SeasonRuleSerializer(
                season.components.prefetch_related("depends_on").order_by("id"),
                many=True,
            ).data
        )

    @transaction.atomic
    def post(self, request, pk, competition_id, season_id):
        season = season_for(request, pk, competition_id, season_id, True, True)
        require_editable(season)
        serializer = SeasonRuleSerializer(data=request.data, context={"season": season})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=201)


class SeasonRuleDetailView(APIView):
    @transaction.atomic
    def patch(self, request, pk, competition_id, season_id, rule_id):
        season = season_for(request, pk, competition_id, season_id, True, True)
        require_editable(season)
        rule = get_object_or_404(SeasonComponent, pk=rule_id, season=season)
        serializer = SeasonRuleSerializer(
            rule, data=request.data, partial=True, context={"season": season}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @transaction.atomic
    def delete(self, request, pk, competition_id, season_id, rule_id):
        season = season_for(request, pk, competition_id, season_id, True, True)
        require_editable(season)
        rule = get_object_or_404(SeasonComponent, pk=rule_id, season=season)
        if rule.dependent_rules.exists():
            raise ValidationError(
                "Other rules depend on this rule. Remove those dependencies first."
            )
        if rule.participantcomponenttarget_set.exists():
            raise ValidationError(
                "Participant targets use this rule. Remove or reassign them first."
            )
        rule.delete()
        return Response(status=204)
