from rest_framework.generics import RetrieveAPIView
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .serializers import UsuarioActualSerializer


class LoginThrottledView(TokenObtainPairView):
    """Login JWT con throttle propio (5/min, §16)."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


class RefreshThrottledView(TokenRefreshView):
    """Renovación del access con throttle propio (30/min), separado del login."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "refresh"


class MeView(RetrieveAPIView):
    """Perfil del usuario autenticado — lo primero que consume el frontend tras el login."""

    serializer_class = UsuarioActualSerializer

    def get_object(self):
        return self.request.user
