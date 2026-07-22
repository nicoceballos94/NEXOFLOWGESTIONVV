"""Lectura de la parametría del sistema (§21)."""
from .models import Parametro

# Los documentos llevan su umbral en TipoDocumento.dias_aviso (es un atributo del tipo).
# Los contratos no tienen catálogo detrás, así que el suyo vive acá.
CLAVE_DIAS_AVISO = "vencimientos.dias_aviso"
DIAS_AVISO_DEFAULT = 30
DIAS_AVISO_MAX = 180


def dias_aviso_contratos() -> int:
    """Cuántos días antes se avisa que un contrato termina. Configurable sin tocar código.

    El valor vivía hardcodeado en el frontend (30 días), donde nadie podía cambiarlo sin un
    deploy — y la tabla de parámetros existía justo para esto. Ahora sale de acá.

    Tolera que el parámetro no exista (instalación nueva) y que tenga basura cargada a mano
    desde el admin: en cualquier caso cae al default. Un aviso de vencimientos que se cae
    por un parámetro mal tipeado es peor que uno con el umbral por defecto.
    """
    parametro = Parametro.objects.filter(clave=CLAVE_DIAS_AVISO).first()
    if not parametro:
        return DIAS_AVISO_DEFAULT
    try:
        dias = int(parametro.valor["dias"])
    except (TypeError, KeyError, ValueError):
        return DIAS_AVISO_DEFAULT
    if dias < 0 or dias > DIAS_AVISO_MAX:
        return DIAS_AVISO_DEFAULT
    return dias
