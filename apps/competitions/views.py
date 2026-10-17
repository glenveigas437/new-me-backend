from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from .models import Season
from .serializers import SeasonSerializer
from apps.tracking.services import score_participant


class SeasonListView(generics.ListAPIView):
    serializer_class = SeasonSerializer

    def get_queryset(self):
        return (
            Season.objects.filter(
                participants__user=self.request.user,
                competition__club__memberships__user=self.request.user,
            )
            .select_related("competition__club")
            .distinct()
        )


class LeaderboardView(APIView):
    def get(self, request, pk):
        season = get_object_or_404(
            Season,
            pk=pk,
            participants__user=request.user,
            competition__club__memberships__user=request.user,
        )
        rows = [
            {
                "display_name": p.user.get_full_name() or p.user.username,
                "is_me": p.user_id == request.user.id,
                **{
                    k: v
                    for k, v in score_participant(p).items()
                    if k != "weekly_breakdown"
                },
            }
            for p in season.participants.filter(
                user__clubmembership__club_id=season.competition.club_id
            ).select_related("user")
        ]
        rows.sort(
            key=lambda r: (
                float(r["total"]),
                float(r["consistency"]),
                float(r["improvement"]),
            ),
            reverse=True,
        )
        previous = None
        for index, row in enumerate(rows, 1):
            key = (row["total"], row["consistency"], row["improvement"])
            row["rank"] = previous[1] if previous and previous[0] == key else index
            previous = (key, row["rank"])
        return Response(rows)
