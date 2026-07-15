"""Reglas comunes de los archivos de respaldo (documentos del empleado y de novedades).

Vive acá porque son la misma regla del sistema —qué archivo se acepta y dónde se guarda—
y hay dos usuarios reales: `empleados.DocumentoEmpleado` (el carnet, el apto médico) y
`novedades.AdjuntoNovedad` (el certificado de la licencia). Duplicarlo garantizaría que
un día el tope de tamaño cambie en un lado y no en el otro.

No hay lógica de negocio acá (§10.4): solo forma de archivo.
"""
import uuid

from django.conf import settings


def ruta_con_uuid(carpeta: str, identificador, filename: str) -> str:
    """<carpeta>/<identificador>/<uuid>.<ext> dentro de MEDIA_ROOT.

    El nombre original se descarta a propósito y se reemplaza por un UUID: el nombre que
    trae el archivo del escáner ("apto medico juan perez.pdf") filtraría PII en la ruta, y
    un nombre adivinable invita a probar URLs. La extensión se conserva (ya validada) porque
    de ella sale el Content-Type de la descarga.
    """
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"{carpeta}/{identificador}/{uuid.uuid4().hex}.{extension}"


def errores_de_archivo(archivo) -> str | None:
    """Devuelve el mensaje de error si el archivo no sirve, o None si está bien.

    Se mira la extensión, no el contenido: para saber de verdad si un PDF es un PDF hacen
    falta los magic bytes (python-magic/libmagic, dependencia binaria). Es una concesión
    consciente — el archivo nunca se ejecuta ni se sirve como HTML, se descarga como
    adjunto, así que el peor caso es un archivo inútil cargado por RRHH, no un XSS.

    Devuelve el error en vez de levantarlo para no atar `common` a DRF (§10.4): quien llama
    lo convierte en ValidationError.
    """
    if archivo in (None, ""):
        return None
    nombre = getattr(archivo, "name", "") or ""
    extension = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
    if extension not in settings.DOCUMENTO_EXTENSIONES:
        return (
            f"Formato no admitido ('{extension or 'sin extensión'}'). "
            f"Se aceptan: {', '.join(settings.DOCUMENTO_EXTENSIONES)}."
        )
    if archivo.size > settings.DOCUMENTO_MAX_BYTES:
        tope_mb = settings.DOCUMENTO_MAX_BYTES / (1024 * 1024)
        real_mb = archivo.size / (1024 * 1024)
        return (
            f"El archivo pesa {real_mb:.1f} MB y el máximo es {tope_mb:.0f} MB. "
            f"Si es una foto, sacala con menos resolución o escaneala como PDF."
        )
    return None
