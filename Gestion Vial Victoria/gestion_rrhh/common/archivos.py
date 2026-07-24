"""Validación y normalización de los archivos sensibles del sistema."""

import io
import uuid
import warnings

from django.conf import settings
from django.core.files.uploadedfile import InMemoryUploadedFile
from PIL import Image, ImageOps


def ruta_con_uuid(carpeta: str, identificador, filename: str) -> str:
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"{carpeta}/{identificador}/{uuid.uuid4().hex}.{extension}"


def _extension(archivo) -> str:
    nombre = getattr(archivo, "name", "") or ""
    return nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""


def _leer_cabecera(archivo, cantidad=1024) -> bytes:
    posicion = archivo.tell() if hasattr(archivo, "tell") else 0
    try:
        archivo.seek(0)
        return archivo.read(cantidad)
    finally:
        archivo.seek(posicion)


def _formato_por_firma(cabecera: bytes) -> str | None:
    if cabecera.lstrip(b"\xef\xbb\xbf\x00\t\r\n ").startswith(b"%PDF-"):
        return "pdf"
    if cabecera.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if cabecera.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if (
        len(cabecera) >= 12
        and cabecera.startswith(b"RIFF")
        and cabecera[8:12] == b"WEBP"
    ):
        return "webp"
    return None


def _verificar_imagen(archivo, extension: str) -> str | None:
    posicion = archivo.tell() if hasattr(archivo, "tell") else 0
    try:
        archivo.seek(0)
        Image.MAX_IMAGE_PIXELS = settings.IMAGEN_MAX_PIXELES
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(archivo) as imagen:
                formato = (imagen.format or "").lower()
                imagen.verify()
    except (Image.UnidentifiedImageError, Image.DecompressionBombError, Warning, OSError):
        return "La imagen está dañada, no es una imagen real o excede el máximo de píxeles."
    finally:
        archivo.seek(posicion)
    esperado = "jpeg" if extension in {"jpg", "jpeg"} else extension
    if formato != esperado:
        return f"El contenido es {formato or 'desconocido'}, pero la extensión es .{extension}."
    return None


def _validar(archivo, *, extensiones, max_bytes, solo_imagen: bool) -> str | None:
    if archivo in (None, ""):
        return None
    extension = _extension(archivo)
    if extension not in extensiones:
        return (
            f"Formato no admitido ('{extension or 'sin extensión'}'). "
            f"Se aceptan: {', '.join(extensiones)}."
        )
    if archivo.size > max_bytes:
        return (
            f"El archivo pesa {archivo.size / (1024 * 1024):.1f} MB y el máximo "
            f"es {max_bytes / (1024 * 1024):.0f} MB."
        )
    firma = _formato_por_firma(_leer_cabecera(archivo))
    esperado = "jpeg" if extension in {"jpg", "jpeg"} else extension
    if firma != esperado:
        return (
            f"El contenido del archivo no coincide con la extensión .{extension}; "
            "no se aceptan archivos renombrados."
        )
    if solo_imagen or extension != "pdf":
        return _verificar_imagen(archivo, extension)
    return None


def errores_de_archivo(archivo) -> str | None:
    return _validar(
        archivo,
        extensiones=settings.DOCUMENTO_EXTENSIONES,
        max_bytes=settings.DOCUMENTO_MAX_BYTES,
        solo_imagen=False,
    )


def errores_de_foto(archivo) -> str | None:
    return _validar(
        archivo,
        extensiones=settings.FOTO_EXTENSIONES,
        max_bytes=settings.FOTO_MAX_BYTES,
        solo_imagen=True,
    )


def normalizar_foto(archivo):
    """Re-encodea la foto: elimina EXIF/metadatos y cualquier payload extra."""

    archivo.seek(0)
    with Image.open(archivo) as original:
        imagen = ImageOps.exif_transpose(original)
        extension = _extension(archivo)
        formato = "JPEG" if extension in {"jpg", "jpeg"} else extension.upper()
        if formato == "JPEG" and imagen.mode not in ("RGB", "L"):
            imagen = imagen.convert("RGB")
        salida = io.BytesIO()
        opciones = {"quality": 88, "optimize": True} if formato == "JPEG" else {}
        imagen.save(salida, format=formato, **opciones)
    salida.seek(0)
    nombre = f"foto.{extension}"
    return InMemoryUploadedFile(
        salida,
        field_name="foto",
        name=nombre,
        content_type=f"image/{'jpeg' if formato == 'JPEG' else extension}",
        size=salida.getbuffer().nbytes,
        charset=None,
    )
