from rest_framework import serializers
from .models import Club, ClubMembership, ClubCode
from apps.competitions.models import Competition


class ClubSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()
    share_analytics = serializers.SerializerMethodField()

    class Meta:
        model = Club
        fields = [
            "id",
            "name",
            "type",
            "description",
            "settings_data",
            "created_at",
            "role",
            "member_count",
            "share_analytics",
        ]
        read_only_fields = ["id", "created_at", "role", "member_count"]

    def get_share_analytics(self, obj):
        return bool(
            obj.memberships.filter(
                user=self.context["request"].user, share_analytics=True
            ).exists()
        )

    def get_role(self, obj):
        return (
            obj.memberships.filter(user=self.context["request"].user)
            .values_list("role", flat=True)
            .first()
        )

    def get_member_count(self, obj):
        return obj.memberships.count()

    def validate_settings_data(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Settings must be a JSON object.")
        return value


class MemberSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()
    username = serializers.CharField(source="user.username", read_only=True)
    is_me = serializers.SerializerMethodField()

    class Meta:
        model = ClubMembership
        fields = [
            "id",
            "user_id",
            "username",
            "display_name",
            "role",
            "joined_at",
            "is_me",
            "share_analytics",
        ]

    def get_display_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    def get_is_me(self, obj):
        return obj.user_id == self.context["request"].user.id


class CodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClubCode
        fields = ["id", "club_id", "code", "created_at", "expires_at", "revoked_at"]


class CompetitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Competition
        fields = ["id", "club_id", "name"]
        read_only_fields = ["id", "club_id"]


class JoinSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=16, trim_whitespace=True)

    def validate_code(self, value):
        return value.upper()


class CodeCreateSerializer(serializers.Serializer):
    valid_days = serializers.IntegerField(min_value=1, max_value=30, default=7)


class RoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["admin", "member"])
