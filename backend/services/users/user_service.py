from django.contrib.auth import get_user_model
from django.db import transaction


User = get_user_model()


class UserService:

    @staticmethod
    @transaction.atomic
    def create_user(
        *,
        email,
        username,
        first_name="",
        last_name="",
        password,
    ):
        user = User.objects.create_user(
            email=email,
            username=username,
            first_name=first_name,
            last_name=last_name,
            password=password,
        )

        return user