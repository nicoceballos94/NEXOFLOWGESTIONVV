"""Vencimientos de toda la dotación: documentos y contratos (spec §1.2, CU-07).

El objetivo declarado del sistema es que nadie maneje con el carnet o el apto vencido.
Hasta acá eso dependía de que alguien abriera la ficha correcta el día correcto: el semáforo
existía por empleado, pero no había forma de cruzar la dotación. `fecha_vencimiento` está
indexada en la base **específicamente para esta consulta**, que nunca se había escrito.

Cada tipo de documento avisa con su propia anticipación (`TipoDocumento.dias_aviso`); los
contratos, con la del parámetro `vencimientos.dias_aviso`. Todo se edita en Configuración.

Dos decisiones de dominio que definen qué es una alerta:

- **Solo la dotación activa.** Un carnet vencido de alguien que se fue hace dos años no es
  un problema: es historia. Se filtra por relación ACTIVA, no por fechas.
- **El contrato que no vence no alerta.** Un INDETERMINADO no tiene fin; los demás sí. Un
  contrato a plazo fijo **sin fecha de fin cargada** cuenta como alerta: no es que esté al
  día, es que no se sabe cuándo vence, y eso es exactamente lo que hay que revisar.

Todo se calcula on-the-fly, como el resto del panel: nada se guarda.
"""
from __future__ import annotations

from datetime import date, timedelta

from apps.empleados.models import (
    DocumentoEmpleado,
    EstadoRelacion,
    RelacionLaboral,
    TipoContrato,
)
from apps.organizacion.selectors import dias_aviso_contratos

# El contrato indeterminado no termina: no hay nada que avisar.
CONTRATOS_QUE_VENCEN = [t for t in TipoContrato.values if t != TipoContrato.INDETERMINADO]

GRUPO_CONTRATOS = "Contratos"


def _estado(vence: date | None, hoy: date, dias_aviso: int) -> str:
    """ok / warn / bad, el mismo semáforo que ya usa la ficha del empleado.

    `None` = vencimiento sin cargar. Es `bad` a propósito: un plazo fijo sin fecha de fin no
    está "al día", está sin control. Mostrarlo en verde sería mentir por omisión.
    """
    if vence is None:
        return "bad"
    if vence < hoy:
        return "bad"
    if vence <= hoy + timedelta(days=dias_aviso):
        return "warn"
    return "ok"


def _empresa_por_empleado(ids) -> dict[int, str]:
    """Empresa de cada empleado: la de su relación ACTIVA.

    Con dos relaciones activas (la persona trabaja en las dos empresas del grupo) se toma la
    más reciente: la alerta necesita una etiqueta, no un informe. El documento es de la
    persona, no de la empresa — el carnet no se duplica por trabajar en dos lados.
    """
    empresas: dict[int, str] = {}
    for rel in (
        RelacionLaboral.objects.filter(
            empleado_id__in=ids, estado=EstadoRelacion.ACTIVA
        )
        .select_related("empresa")
        .order_by("empleado_id", "-fecha_ingreso")
    ):
        empresas.setdefault(rel.empleado_id, rel.empresa.nombre)
    return empresas


def _items_de_documentos(hoy: date) -> dict[str, list[dict]]:
    """Documentos con vencimiento de la gente activa, agrupados por tipo.

    Cada tipo avisa con su propia anticipación (`TipoDocumento.dias_aviso`): un apto médico
    puede querer más margen que un carnet, y RRHH lo decide desde Configuración.
    """
    documentos = list(
        DocumentoEmpleado.objects.filter(
            empleado__relaciones__estado=EstadoRelacion.ACTIVA,
            fecha_vencimiento__isnull=False,  # sin fecha no hay nada que vigilar
        )
        .select_related("empleado", "tipo_documento")
        # Quien tiene relación activa en las dos empresas del grupo matchea dos veces el
        # JOIN y traería el mismo documento repetido.
        .distinct()
    )
    empresas = _empresa_por_empleado({d.empleado_id for d in documentos})
    grupos: dict[str, list[dict]] = {}
    for doc in documentos:
        grupos.setdefault(doc.tipo_documento.nombre, []).append(
            {
                "empleado_id": doc.empleado_id,
                "empleado": doc.empleado.nombre_natural,
                "empresa": empresas.get(doc.empleado_id, "—"),
                "fecha": doc.fecha_vencimiento,
                "estado": _estado(doc.fecha_vencimiento, hoy, doc.tipo_documento.dias_aviso),
                "detalle": doc.tipo_documento.nombre,
            }
        )
    return grupos


def _items_de_contratos(hoy: date, dias_aviso: int) -> list[dict]:
    """Contratos con fin previsto (los que no son indeterminados) de la gente activa."""
    relaciones = (
        RelacionLaboral.objects.filter(
            estado=EstadoRelacion.ACTIVA, tipo_contrato__in=CONTRATOS_QUE_VENCEN
        )
        .select_related("empleado", "empresa")
    )
    return [
        {
            "empleado_id": rel.empleado_id,
            "empleado": rel.empleado.nombre_natural,
            "empresa": rel.empresa.nombre,
            "fecha": rel.fecha_vencimiento_contrato,
            "estado": _estado(rel.fecha_vencimiento_contrato, hoy, dias_aviso),
            "detalle": rel.get_tipo_contrato_display(),
        }
        for rel in relaciones
    ]


def _ordenar(items: list[dict]) -> list[dict]:
    """Lo más urgente arriba: primero lo que no tiene fecha, después por fecha ascendente."""
    return sorted(items, key=lambda i: (i["fecha"] is not None, i["fecha"] or date.min))


def vencimientos_de_la_dotacion(*, hoy: date | None = None) -> dict:
    """Todo lo que vence, agrupado por tipo, con el resumen del semáforo.

    No devuelve un `dias_aviso` global: cada tipo tiene el suyo y un único número acá sería
    mentira. La parametría se lee de /config/vencimientos/, que es su lugar.
    """
    hoy = hoy or date.today()

    grupos = _items_de_documentos(hoy)
    contratos = _items_de_contratos(hoy, dias_aviso_contratos())
    if contratos:
        grupos[GRUPO_CONTRATOS] = contratos

    # Los tipos de documento alfabéticos y los contratos al final: es lo que menos se mira
    # a diario y lo que el diseño ya muestra último.
    nombres = sorted(k for k in grupos if k != GRUPO_CONTRATOS)
    if GRUPO_CONTRATOS in grupos:
        nombres.append(GRUPO_CONTRATOS)

    salida = [{"tipo": n, "items": _ordenar(grupos[n])} for n in nombres]
    todos = [i for g in salida for i in g["items"]]
    return {
        "resumen": {
            "vencidos": sum(1 for i in todos if i["estado"] == "bad"),
            "por_vencer": sum(1 for i in todos if i["estado"] == "warn"),
            "al_dia": sum(1 for i in todos if i["estado"] == "ok"),
        },
        "grupos": salida,
    }
