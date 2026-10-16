from rest_framework import generics
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView

from .serializers import RegisterSerializer, UserSerializer
from .throttles import LoginIPThrottle, LoginUsernameThrottle, RegisterIPThrottle


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    throttle_classes = [RegisterIPThrottle]


class LoginView(TokenObtainPairView):
    """SimpleJWT login, throttled per username and per client IP (429)."""

    throttle_classes = [LoginUsernameThrottle, LoginIPThrottle]


class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user