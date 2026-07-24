"""Escritura de la bitácora: un único punto de entrada, `registrar_evento()` (§14, RP8).

**Por qué desde los services y no con señales de Django.** Las señales disparan también
en migraciones de datos, `loaddata`, comandos de management e imports: la bitácora se
llenaría de eventos sin actor que nadie pidió, y encima no distinguen "aprobar" de
"rechazar" (ambas son un `post_save` de Novedad). El diseño ya lo decidió así: explícito
> mágico. El costo es una línea por operación en cada service; la ganancia es que cada
renglón de la bitácora tiene autor y significado.

**Por qué no atrapa excepciones.** `registrar_evento` corre dentro de la misma
transacción atómica del service que lo llama. Si falla, la operación de negocio se cae
con él. Es deliberado: en un dominio con disputas legales, una baja que se guarda "pero
sin constancia de quién la hizo" es peor que una baja que no se guarda. Para que ese
riesgo sea teórico y no real, `_valor_json` no puede fallar: cualquier tipo que no
reconozca cae a `str()`.

Uso típico:

    foto = tomar_foto(empleado)                 # antes de tocar nada
    ... se modifica el empleado ...
    registrar_evento(actor=actor, accion=Accion.EMPLEADO_ACTUALIZADO,
                     objeto=empleado, antes=foto, solo_si_cambia=True)
"""
import datetime
import decimal
import uuid

from django.core.exceptions import ObjectDoesNotExist
from django.db.models.fields.files import FieldFile

from .models import Accion, RegistroAuditoria

# Ruido de auditoría: son metadatos de la fila, no datos que alguien haya decidido.
# `creado_por`/`creado_en` no se pierden — quedan en el evento de alta, que tiene autor.
_CAMPOS_RUIDO = frozenset({"id", "creado_en", "actualizado_en", "creado_por"})

# Nunca, bajo ninguna acción, ni siquiera hasheados. La bitácora es lectura de Admin: un
# hash filtrado desde acá es un hash filtrado igual.
_CAMPOS_PROHIBIDOS = frozenset({"password"})


def _valor_json(objeto, campo):
    """Un campo del modelo → algo que entre en JSONB y se lea dentro de dos años.

    Las FK se guardan como **texto** (`str()` del relacionado), no como id: un
    `sector: 3 → 7` no le sirve a nadie, y el id además puede apuntar mañana a otra cosa.
    Se pierde poder linkear desde la bitácora al objeto relacionado; a cambio, el renglón
    se entiende solo para siempre, que es lo que se le pide a una constancia.
    """
    if campo.name in _CAMPOS_PROHIBIDOS:
        return "«oculto»"

    if campo.is_relation:
        try:
            relacionado = getattr(objeto, campo.name)
        except ObjectDoesNotExist:  # FK colgada: el relacionado ya no está
            return None
        return str(relacionado) if relacionado is not None else None

    valor = getattr(objeto, campo.name)

    # De los archivos se guarda el NOMBRE, jamás el contenido (PII, y no entra en JSONB).
    if isinstance(valor, FieldFile):
        return valor.name or None
    if valor is None or isinstance(valor, (bool, int, float, str)):
        return valor
    if isinstance(valor, (datetime.datetime, datetime.date, datetime.time)):
        return valor.isoformat()
    if isinstance(valor, (decimal.Decimal, uuid.UUID, datetime.timedelta)):
        return str(valor)
    return str(valor)  # red final: registrar_evento no puede caerse por un tipo raro


def _empleado_de(objeto):
    """De qué persona habla el evento, preguntándoselo al propio objeto.

    Cada modelo auditado declara una propiedad `empleado_auditado` con el camino hasta su
    persona (`ItemProceso` la busca por proceso→relación→empleado; `Empleado` se devuelve a
    sí mismo). Se resuelve por convención y no con un `if isinstance(...)` acá porque esta
    app no tiene por qué conocer el mapa de las otras: cada modelo sabe mejor que nadie
    dónde está su persona, y agregar una entidad auditable no obliga a tocar este archivo.

    El contrato lo sostiene `test_empleado_id.py`, que recorre las entidades auditadas y
    exige que cada una resuelva (o esté declarada como "no es de nadie"). Sin ese test, una
    entidad nueva sin la propiedad guardaría `empleado=None` sin que nada se queje, y el
    historial de la ficha quedaría incompleto en silencio.
    """
    try:
        return getattr(objeto, "empleado_auditado", None)
    except ObjectDoesNotExist:  # relación esperada que no está (usuario sin empleado)
        return None


def tomar_foto(objeto, *, campos: tuple[str, ...] | None = None) -> dict:
    """Estado serializable del objeto **en este instante**.

    Se saca ANTES de mutar para tener el "antes"; `registrar_evento` saca el "después"
    solo. `campos` acota a un subconjunto cuando al service le interesa una parte (la
    foto de perfil, por ejemplo) y el resto sería ruido en el diff.
    """
    return {
        campo.name: _valor_json(objeto, campo)
        for campo in objeto._meta.concrete_fields
        if campo.name not in _CAMPOS_RUIDO and (campos is None or campo.name in campos)
    }


def _diferencias(antes: dict, despues: dict) -> tuple[dict, dict]:
    """Se queda solo con los campos que cambiaron, en ambos lados.

    Guardar la fila entera dos veces engorda la tabla y obliga a quien lee a jugar a las
    diferencias. Los tres casos salen del mismo cálculo: en un alta `antes` está vacío
    (todo "cambió"), en una baja lo está `despues`, y en una edición quedan los dos o
    tres campos que alguien realmente tocó.
    """
    claves = set(antes) | set(despues)
    cambiadas = {clave for clave in claves if antes.get(clave) != despues.get(clave)}
    return (
        {clave: antes[clave] for clave in cambiadas if clave in antes},
        {clave: despues[clave] for clave in cambiadas if clave in despues},
    )


def registrar_evento(
    *,
    actor,
    accion: str,
    objeto,
    antes: dict | None = None,
    despues: dict | None = None,
    campos: tuple[str, ...] | None = None,
    solo_si_cambia: bool = False,
    ip: str | None = None,
) -> RegistroAuditoria | None:
    """Asienta un hecho en la bitácora. Devuelve el registro, o None si no hubo nada que asentar.

    - `antes`: la foto previa (`tomar_foto`). None en un alta.
    - `despues`: se calcula del objeto salvo que se pase explícito. En una **baja** se pasa
      `{}` y se llama **antes** del `.delete()`: después, Django deja el objeto sin pk y la
      constancia perdería a quién se refería.
    - `solo_si_cambia`: para acciones de tipo diff (`…_ACTUALIZADO`). Un PATCH que no cambió
      nada no es un hecho; sin esto, cada vez que alguien abre y guarda una ficha sin tocarla
      queda un renglón vacío que ensucia la historia. Las acciones semánticas
      (`NOVEDAD_RECHAZADA`) NO lo usan: ahí el hecho es la acción, no el diff.
    """
    antes = antes or {}
    if despues is None:
        despues = tomar_foto(objeto, campos=campos)

    valores_antes, valores_despues = _diferencias(antes, despues)
    if solo_si_cambia and not valores_antes and not valores_despues:
        return None

    # AnonymousUser tiene `username` pero no pk: se asienta como proceso sin autor.
    usuario = actor if getattr(actor, "is_authenticated", False) else None

    return RegistroAuditoria.objects.create(
        usuario=usuario,
        usuario_nombre=getattr(usuario, "username", "") or "",
        accion=accion,
        entidad=objeto._meta.object_name,
        empleado=_empleado_de(objeto),
        objeto_id=objeto.pk,
        objeto_repr=str(objeto)[:200],
        valores_antes=valores_antes,
        valores_despues=valores_despues,
        ip=ip,
    )


__all__ = ["Accion", "registrar_evento", "tomar_foto"]
