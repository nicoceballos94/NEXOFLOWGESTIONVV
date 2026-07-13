"""Panel general: una sola lectura agregada (§11 view flaca → delega en selector).

Solo roles que ven la dotación (Admin/RRHH/Supervisor); el resto no tiene panel.
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common import roles
from common.permissions import RolRequerido

from .. import selectors


class DashboardMetricasView(APIView):
    permission_classes = [IsAuthenticated, RolRequerido(roles.ADMIN, roles.RRHH, roles.SUPERVISOR)]

    def get(self, request):
        return Response(selectors.metricas_dashboard())
