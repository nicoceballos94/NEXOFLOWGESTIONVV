"""Parametría de alertas de vencimiento (§21): lectura y escritura desde Configuración.

La pantalla mostraba 4 filas hardcodeadas con valores inventados (apto 15, contrato 45) que
no salían de ningún lado ni se guardaban en ninguno: mover el `+` no cambiaba nada. Acá se
arma la lista real y se persiste.

Las filas de documento salen del **catálogo**, no de una lista fija: si RRHH da de alta un
tipo nuevo, aparece configurable solo. La de contratos es fija porque no hay catálogo
detrás — el fin de contrato vive en la relación laboral.
"""
from __future__ import annotations

from django.db import transaction

from apps.auditoria.services import Accion, registrar_evento, tomar_foto
from apps.empleados.models import TipoDocumento

from .models import Parametro
from .selectors import CLAVE_DIAS_AVISO, DIAS_AVISO_MAX, dias_aviso_contratos

# Clave de la fila de contratos. El prefijo `tipo:` de los documentos no puede colisionar.
CLAVE_CONTRATOS = "contratos"
HINT_CONTRATOS = "Aviso antes del fin de contrato (plazo fijo, eventual, temporada)."


class ClaveDesconocida(Exception):
    """La fila que se quiere guardar no existe (tipo borrado, o clave inventada)."""


def filas_de_configuracion() -> list[dict]:
    """Una fila por cada cosa que puede vencer, con su anticipación actual."""
    filas = [
        {
            "clave": f"tipo:{t.id}",
            "label": t.nombre,
            "hint": t.descripcion,
            "dias": t.dias_aviso,
        }
        # Solo los tipos activos: configurar el aviso de un tipo dado de baja no tiene
        # sentido, no puede generar alertas.
        for t in TipoDocumento.objects.filter(activo=True)
    ]
    filas.append(
        {
            "clave": CLAVE_CONTRATOS,
            "label": "Contratos a plazo",
            "hint": HINT_CONTRATOS,
            "dias": dias_aviso_contratos(),
        }
    )
    return filas


def _validar_dias(dias) -> int:
    try:
        dias = int(dias)
    except (TypeError, ValueError):
        raise ValueError("Los días de aviso tienen que ser un número entero.")
    if dias < 0 or dias > DIAS_AVISO_MAX:
        raise ValueError(f"Los días de aviso van de 0 a {DIAS_AVISO_MAX}.")
    return dias


@transaction.atomic
def guardar_dias_aviso(*, clave: str, dias: int, actor=None) -> dict:
    """Guarda la anticipación de una fila. Devuelve la fila actualizada."""
    dias = _validar_dias(dias)

    if clave == CLAVE_CONTRATOS:
        parametro_previo = (
            Parametro.objects.select_for_update().filter(clave=CLAVE_DIAS_AVISO).first()
        )
        antes = tomar_foto(parametro_previo) if parametro_previo else {}
        parametro, _ = Parametro.objects.update_or_create(
            clave=CLAVE_DIAS_AVISO,
            defaults={
                "valor": {"dias": dias},
                "descripcion": "Días de anticipación con que se avisa el fin de un contrato.",
            },
        )
        if actor is not None:
            registrar_evento(
                actor=actor,
                accion=Accion.CONFIG_ACTUALIZADA,
                objeto=parametro,
                antes=antes,
                solo_si_cambia=True,
            )
        return {"clave": clave, "label": "Contratos a plazo", "hint": HINT_CONTRATOS, "dias": dias}

    if not clave.startswith("tipo:"):
        raise ClaveDesconocida(clave)
    try:
        tipo_id = int(clave.split(":", 1)[1])
    except ValueError:
        raise ClaveDesconocida(clave)

    tipo = TipoDocumento.objects.select_for_update().filter(pk=tipo_id, activo=True).first()
    if not tipo:
        raise ClaveDesconocida(clave)
    antes = tomar_foto(tipo, campos=("dias_aviso",))
    tipo.dias_aviso = dias
    tipo.save(update_fields=["dias_aviso", "actualizado_en"])
    if actor is not None:
        registrar_evento(
            actor=actor,
            accion=Accion.CONFIG_ACTUALIZADA,
            objeto=tipo,
            antes=antes,
            campos=("dias_aviso",),
            solo_si_cambia=True,
        )
    return {"clave": clave, "label": tipo.nombre, "hint": tipo.descripcion, "dias": dias}
