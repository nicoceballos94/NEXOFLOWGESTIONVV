"""Predicados compartidos para consultar la vigencia efectiva de una cadena."""

from django.db.models import Q

from .models import EstadoNovedad


def cadena_intersecta_desde(desde) -> Q:
    """Madre o prórroga confirmada cuyo fin efectivo alcanza ``desde``.

    Las prórrogas rechazadas, anuladas o todavía pendientes no extienden el período.
    ``FALTA`` histórica sin fecha_hasta conserva su semántica de un solo día.
    """

    madre_abierta = Q(fecha_hasta__isnull=True) & ~Q(
        tipo_novedad__codigo="FALTA"
    )
    falta_un_dia = Q(
        fecha_hasta__isnull=True,
        tipo_novedad__codigo="FALTA",
        fecha_desde__gte=desde,
    )
    extension_confirmada = Q(
        prorrogas__estado__in=(
            EstadoNovedad.APROBADA,
            EstadoNovedad.CERRADA,
        ),
        prorrogas__fecha_hasta__gte=desde,
    )
    extension_abierta = Q(
        prorrogas__estado__in=(
            EstadoNovedad.APROBADA,
            EstadoNovedad.CERRADA,
        ),
        prorrogas__fecha_hasta__isnull=True,
    )
    return (
        Q(fecha_hasta__gte=desde)
        | madre_abierta
        | falta_un_dia
        | extension_confirmada
        | extension_abierta
    )


__all__ = ["cadena_intersecta_desde"]
