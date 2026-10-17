from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from .serializers import RegisterSerializer, ProfileSerializer


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


class ProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = ProfileSerializer

    def get_object(self):
        return self.request.user


def token_response(response):
    refresh = response.data.pop("refresh", None)
    if refresh:
        response.set_cookie(
            "betterme_refresh",
            refresh,
            httponly=True,
            secure=not settings.DEBUG,
            samesite="Strict",
            path="/api/auth/",
            max_age=7 * 86400,
        )
    return response


@method_decorator(csrf_protect, name="dispatch")
class LoginView(TokenObtainPairView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"

    def post(self, request, *args, **kwargs):
        return token_response(super().post(request, *args, **kwargs))


@method_decorator(csrf_protect, name="dispatch")
class RefreshView(TokenRefreshView):
    def post(self, request, *args, **kwargs):
        refresh = request.COOKIES.get("betterme_refresh")
        if not refresh:
            raise InvalidToken("Refresh session is missing.")
        serializer = self.get_serializer(data={"refresh": refresh})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            raise InvalidToken(str(e))
        return token_response(Response(serializer.validated_data))


@method_decorator(csrf_protect, name="dispatch")
class LogoutView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def post(self, request):
        try:
            RefreshToken(request.COOKIES.get("betterme_refresh", "")).blacklist()
        except TokenError:
            pass
        response = Response(status=status.HTTP_204_NO_CONTENT)
        response.delete_cookie("betterme_refresh", path="/api/auth/", samesite="Strict")
        return response


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({"detail": "CSRF cookie set."})
