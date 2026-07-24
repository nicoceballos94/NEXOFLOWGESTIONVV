"""Consulta de la bitácora (§8). Solo lectura y solo Admin.

**Por qué solo Admin y no RRHH.** RRHH es el rol que más aparece *auditado* — es quien da
altas, bajas y aprueba licencias. Darle la bitácora sería dejar que el auditado lea su
propio expediente. Además la tabla concentra el PII más sensible del sistema (DNI y CUIL en
los diffs de empleado, motivos médicos en los de novedad) sin los serializers por rol que
protegen esos datos en sus endpoints de origen: acá el diff es texto plano.

No hay POST, PATCH ni DELETE, y no es un olvido: la bitácora se escribe únicamente desde
los services, dentro de la transacción del hecho que registra.
"""
import django_filters
from rest_framework import mixins, viewsets

from common import roles
from common.permissions import RolRequerido

from .. import selectors
from ..models import RegistroAuditoria
from .serializers import RegistroAuditoriaSerializer

_SoloAdmin = RolRequerido(roles.ADMIN)


class RegistroAuditoriaFilter(django_filters.FilterSet):
    """`desde`/`hasta` filtran por DÍA, no por instante.

    `momento` es un datetime; un `momento__gte=2026-07-24` a secas dejaría afuera todo lo
    del propio 24 salvo la medianoche exacta. Quien busca "lo del martes" espera el día
    completo, así que se compara contra `momento__date`.
    """

    desde = django_filters.DateFilter(field_name="momento", lookup_expr="date__gte")
    hasta = django_filters.DateFilter(field_name="momento", lookup_expr="date__lte")

    class Meta:
        model = RegistroAuditoria
        fields = (
            "empleado",
            "entidad",
            "objeto_id",
            "agregado_entidad",
            "agregado_id",
            "usuario",
            "accion",
            "desde",
            "hasta",
        )


class RegistroAuditoriaViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """GET /auditoria/registros/ — la bitácora, filtrable.

    - `?empleado=42` → la pestaña "Historial" de una ficha (todo lo que le pasó a alguien).
    - `?entidad=Novedad&objeto_id=7` → la historia de un objeto puntual.
    - `?usuario=3&desde=2026-07-01&hasta=2026-07-31` → qué hizo alguien en un período.
    """

    serializer_class = RegistroAuditoriaSerializer
    permission_classes = [_SoloAdmin]
    filterset_class = RegistroAuditoriaFilter
    search_fields = ("objeto_repr", "usuario_nombre")
    ordering_fields = ("momento",)
    ordering = ("-momento", "-id")

    def get_queryset(self):
        return selectors.registros()
