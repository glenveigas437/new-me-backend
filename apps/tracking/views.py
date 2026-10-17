from django.db import IntegrityError, transaction
from rest_framework import generics, serializers
from .models import UserActivity, GoalMeasurement
from .serializers import ActivitySerializer, MeasurementSerializer


class ActivityListCreateView(generics.ListCreateAPIView):
    serializer_class = ActivitySerializer

    def get_queryset(self):
        qs = UserActivity.objects.filter(
            participant__user=self.request.user,
            participant__season__competition__club__memberships__user=self.request.user,
        ).select_related("season_component__component")
        season = self.request.query_params.get("season")
        return qs.filter(participant__season_id=season) if season else qs

    def perform_create(self, serializer):
        try:
            with transaction.atomic():
                serializer.save()
        except IntegrityError:
            raise serializers.ValidationError(
                "An activity already exists for this component and day."
            )


class MeasurementListCreateView(generics.ListCreateAPIView):
    serializer_class = MeasurementSerializer

    def get_queryset(self):
        return GoalMeasurement.objects.filter(
            goal__participant__user=self.request.user,
            goal__participant__season__competition__club__memberships__user=self.request.user,
        )
