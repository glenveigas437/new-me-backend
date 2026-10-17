from datetime import date
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from .models import User


class ProfileSerializer(serializers.ModelSerializer):
    bmi = serializers.DecimalField(max_digits=5, decimal_places=1, read_only=True)
    date_of_birth = serializers.DateField(
        format="%d-%m-%Y", input_formats=["%d-%m-%Y"], allow_null=True, required=False
    )

    profile_complete = serializers.BooleanField(read_only=True)
    missing_profile_fields = serializers.ListField(
        child=serializers.CharField(), read_only=True
    )

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "height_cm",
            "weight_kg",
            "date_of_birth",
            "bmi",
            "muscle_percentage",
            "body_fat_percentage",
            "profile_complete",
            "missing_profile_fields",
        ]
        read_only_fields = ["id", "username", "email", "bmi"]

    def validate_date_of_birth(self, value):
        if value and value >= date.today():
            raise serializers.ValidationError("Date of birth must be in the past.")
        return value


class RegisterSerializer(ProfileSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta(ProfileSerializer.Meta):
        fields = ProfileSerializer.Meta.fields + ["password"]
        read_only_fields = ["id", "bmi"]

    def validate(self, attrs):
        try:
            validate_password(
                attrs["password"],
                user=User(**{k: v for k, v in attrs.items() if k != "password"}),
            )
        except DjangoValidationError as e:
            raise serializers.ValidationError({"password": e.messages})
        return attrs

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)
