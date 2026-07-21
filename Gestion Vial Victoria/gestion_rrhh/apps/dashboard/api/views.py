"""Lecturas agregadas de los paneles (§11 view flaca → delega en selector).

Solo roles que ven la dotación (Admin/RRHH/Supervisor); el resto no tiene panel. Son
lecturas de TODA la dotación por definición: no hay scope por empleado que aplicar, se
tiene el permiso o no se tiene.
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common import roles
from common.permissions import RolRequerido

from .. import alertas_dia, reportes, selectors, vencimientos

_VeDotacion = RolRequerido(roles.ADMIN, roles.RRHH, roles.SUPERVISOR)


class DashboardMetricasView(APIView):
    permission_classes = [IsAuthenticated, _VeDotacion]

    def get(self, request):
        return Response(selectors.metricas_dashboard())


class ReportesMetricasView(APIView):
    """Dotación en el tiempo, ausentismo por tipo y motivos de egreso (pantalla Reportes)."""

    permission_classes = [IsAuthenticated, _VeDotacion]

    def get(self, request):
        return Response(reportes.metricas_reportes())


class VencimientosView(APIView):
    """CU-07: quién tiene documentación o contrato por vencer, en toda la dotación."""

    permission_classes = [IsAuthenticated, _VeDotacion]

    def get(self, request):
        return Response(vencimientos.vencimientos_de_la_dotacion())


class AlertasDelDiaView(APIView):
    """Resumen accionable del panel: lo que hay que mirar hoy."""

    permission_classes = [IsAuthenticated, _VeDotacion]

    def get(self, request):
        return Response(alertas_dia.alertas_del_dia())
