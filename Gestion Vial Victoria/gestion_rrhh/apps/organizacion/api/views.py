"""Catálogos organizativos: CRUD puro, sin reglas de negocio → ModelViewSet directo.

Las apps con reglas (empleados, novedades) usan services/selectors (§11-12);
acá no hay nada que orquestar.
"""
from rest_framework import viewsets

from common import roles
from common.permissions import LecturaAutenticadaEscrituraPorRol

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
