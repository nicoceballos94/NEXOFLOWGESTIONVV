"""Lecturas agregadas de los paneles (§11 view flaca → delega en selector).

Admin/RRHH ven el alcance transversal. Supervisor ve únicamente el estado operativo del
equipo que tiene asignado hoy; no recibe series históricas hasta que exista vigencia de
asignaciones. Los selectors aplican el scope aunque la view ya haya validado el rol.
"""
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common import roles
from common.permissions import RolRequerido

from .. import alertas_dia, reportes, selectors, vencimientos

_VeDotacion = RolRequerido(roles.ADMIN, roles.RRHH, roles.SUPERVISOR)
_VeHistorico = RolRequerido(roles.ADMIN, roles.RRHH)


class DashboardMetricasView(APIView):
    permission_classes = [IsAuthenticated, _VeDotacion]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        return Response(selectors.metricas_dashboard(usuario=request.user))


class ReportesMetricasView(APIView):
    """Dotación en el tiempo, ausentismo por tipo y motivos de egreso (pantalla Reportes)."""

    # El supervisor se almacena como asignación actual. Hasta modelar su historial, darle
    # series pasadas proyectaría el equipo de hoy hacia meses en que pudo ser otro.
    permission_classes = [IsAuthenticated, _VeHistorico]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        return Response(reportes.metricas_reportes(usuario=request.user))


class VencimientosView(APIView):
    """CU-07: documentación o contrato por vencer dentro del scope del actor."""

    permission_classes = [IsAuthenticated, _VeDotacion]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        return Response(vencimientos.vencimientos_de_la_dotacion(usuario=request.user))


class AlertasDelDiaView(APIView):
    """Resumen accionable del panel: lo que hay que mirar hoy."""

    permission_classes = [IsAuthenticated, _VeDotacion]

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request):
        return Response(alertas_dia.alertas_del_dia(usuario=request.user))
