"""Catálogos organizativos: CRUD puro, sin reglas de negocio → ModelViewSet directo.

Las apps con reglas (empleados, novedades) usan services/selectors (§11-12);
acá no hay nada que orquestar.
"""
from rest_framework import viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common import roles
from common.permissions import LecturaAutenticadaEscrituraPorRol, RolRequerido

from .. import config_vencimientos
from ..models import Empresa, Puesto, Sector
from .serializers import EmpresaSerializer, PuestoSerializer, SectorSerializer


class EmpresaViewSet(viewsets.ModelViewSet):
    queryset = Empresa.objects.all()
    serializer_class = EmpresaSerializer
    permission_classes = [LecturaAutenticadaEscrituraPorRol(roles.ADMIN, roles.RRHH)]
    filterset_fields = ("activa",)
    search_fields = ("nombre", "cuit")
    # sin DELETE (baja lógica = activa=False)
    http_method_names = ["get", "post", "patch", "head", "options"]


class SectorViewSet(viewsets.ModelViewSet):
    queryset = Sector.objects.all()
    serializer_class = SectorSerializer
    permission_classes = [LecturaAutenticadaEscrituraPorRol(roles.ADMIN, roles.RRHH)]
    filterset_fields = ("activo",)
    http_method_names = ["get", "post", "patch", "head", "options"]


class PuestoViewSet(viewsets.ModelViewSet):
    queryset = Puesto.objects.select_related("sector")
    serializer_class = PuestoSerializer
    permission_classes = [LecturaAutenticadaEscrituraPorRol(roles.ADMIN, roles.RRHH)]
    filterset_fields = ("sector", "activo")
    http_method_names = ["get", "post", "patch", "head", "options"]


class ConfigVencimientosView(APIView):
    """Parametría de alertas (§21): con cuántos días de anticipación avisa cada cosa.

    Tiene reglas (qué filas existen, de dónde sale cada valor), así que delega en el módulo
    de dominio en vez de ser un ModelViewSet: no hay UN modelo detrás, hay dos orígenes.
    """

    # Cambiar el umbral cambia lo que ve toda la empresa: no es de un supervisor.
    permission_classes = [IsAuthenticated, RolRequerido(roles.ADMIN, roles.RRHH)]

    def get(self, request):
        return Response({"filas": config_vencimientos.filas_de_configuracion()})

    def patch(self, request):
        # Se levantan excepciones de DRF (y no se devuelve un Response a mano) para que
        # pasen por el manejador de §8 y lleguen como {codigo, detalle, campos}: el front
        # lee `detalle`, y un dict armado acá lo saltearía.
        try:
            fila = config_vencimientos.guardar_dias_aviso(
                clave=request.data.get("clave", ""), dias=request.data.get("dias")
            )
        except config_vencimientos.ClaveDesconocida:
            raise NotFound("Esa alerta ya no existe. Recargá la configuración.")
        except ValueError as e:
            raise ValidationError(str(e))
        return Response(fila)
