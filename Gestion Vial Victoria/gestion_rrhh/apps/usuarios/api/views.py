from django.contrib.auth import authenticate, login, logout
from django.db import transaction
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.auditoria.services import Accion, registrar_evento
from common import roles
from common.permissions import RolRequerido

from .. import selectors
from .serializers import SupervisorAsignableSerializer, UsuarioActualSerializer


class CredencialesLoginSerializer(serializers.Serializer):
    """Entrada real del login, no solo una descripción para OpenAPI."""

    username = serializers.CharField(max_length=150, trim_whitespace=True)
    password = serializers.CharField(
        max_length=1024,
        trim_whitespace=False,
        write_only=True,
    )


MensajeSerializer = inline_serializer(
    name="Mensaje",
    fields={"detalle": serializers.CharField()},
)


@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    """Autenticación humana mediante sesión de servidor y cookie HttpOnly."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(
        request=CredencialesLoginSerializer,
        responses={
            200: UsuarioActualSerializer,
            401: OpenApiTypes.OBJECT,
            403: OpenApiTypes.OBJECT,
            429: OpenApiTypes.OBJECT,
        },
        description=(
            "Inicia una sesión humana. Antes debe obtenerse la cookie CSRF con "
            "GET /api/v1/auth/csrf/ y enviarse X-CSRFToken."
        ),
    )
    def post(self, request):
        entrada = CredencialesLoginSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        username = entrada.validated_data["username"]
        password = entrada.validated_data["password"]
        usuario = authenticate(request=request, username=username, password=password)
        # Una identidad de Servicio es de máquina, aunque por error también tenga otro
        # grupo. Consultamos la membresía real en vez de ``tiene_rol`` porque un
        # superusuario satisface cualquier rol sin pertenecer a sus grupos.
        es_servicio = usuario is not None and usuario.groups.filter(
            name=roles.SERVICIO
        ).exists()
        if usuario is None or not usuario.is_active or es_servicio:
            return Response(
                {
                    "codigo": "credenciales_invalidas",
                    "detalle": "Usuario o contraseña inválidos.",
                },
                status=status.HTTP_401_UNAUTHORIZED,
            )
        # La creación/rotación de la sesión de base y su evento deben confirmarse juntos.
        # Si la bitácora falla, tampoco queda una sesión humana abierta sin constancia.
        with transaction.atomic():
            login(request, usuario)
            registrar_evento(
                actor=usuario,
                accion=Accion.SESION_INICIADA,
                objeto=usuario,
                despues={},
            )
        return Response(UsuarioActualSerializer(usuario).data)


@method_decorator(csrf_protect, name="dispatch")
class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={204: None, 403: OpenApiTypes.OBJECT})
    def post(self, request):
        usuario = request.user
        with transaction.atomic():
            registrar_evento(
                actor=usuario,
                accion=Accion.SESION_CERRADA,
                objeto=usuario,
                despues={},
            )
            logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CsrfView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @method_decorator(ensure_csrf_cookie)
    @extend_schema(responses={200: MensajeSerializer})
    def get(self, request):
        return Response({"detalle": "Cookie CSRF inicializada."})


class MeView(RetrieveAPIView):
    """Perfil del usuario autenticado."""

    serializer_class = UsuarioActualSerializer

    def get_object(self):
        return self.request.user


class SupervisoresView(APIView):
    """Catálogo mínimo de responsables asignables, visible solo para RRHH/Admin."""

    permission_classes = [RolRequerido(roles.ADMIN, roles.RRHH)]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "activo",
                OpenApiTypes.BOOL,
                OpenApiParameter.QUERY,
                required=False,
                description="true (por defecto) lista activos; false lista inactivos.",
            )
        ],
        responses={200: SupervisorAsignableSerializer(many=True)},
    )
    def get(self, request):
        valor = request.query_params.get("activo")
        if valor is None or valor.lower() in {"1", "true", "si", "sí", "yes"}:
            activo = True
        elif valor.lower() in {"0", "false", "no"}:
            activo = False
        else:
            from rest_framework.exceptions import ValidationError

            raise ValidationError(
                {"activo": "Debe ser un booleano: true o false."}
            )
        supervisores = selectors.supervisores_asignables(activo=activo)
        return Response(SupervisorAsignableSerializer(supervisores, many=True).data)
