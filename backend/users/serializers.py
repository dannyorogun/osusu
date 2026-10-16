from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers


User = get_user_model()

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        min_length=8
    )

    class Meta:
        model = User
        fields = [
            "email",
            "username",
            "first_name",
            "last_name",
            "password",
        ]

    def validate(self, attrs):
        # Run the configured AUTH_PASSWORD_VALIDATORS against an unsaved
        # user, so similarity to username/email/name is checked too. The
        # password itself is never echoed or logged.
        password = attrs.get("password")
        candidate = User(
            **{
                key: value
                for key, value in attrs.items()
                if key != "password"
            }
        )

        try:
            validate_password(password, user=candidate)
        except DjangoValidationError as error:
            raise serializers.ValidationError(
                {"password": list(error.messages)}
            )

        return attrs

    def create(self, validated_data):
        from services.users.user_service import UserService

        return UserService.create_user(
            **validated_data
        )


class UserSerializer(serializers.ModelSerializer):

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "username",
            "first_name",
            "last_name",
            "is_verified",
            "created_at",
            "updated_at",
        ]