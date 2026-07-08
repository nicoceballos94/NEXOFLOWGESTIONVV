"""Errores JSON uniformes (§8): {codigo, detalle, campos}."""
from rest_framework.views import exception_handler


def manejador_excepciones(exc, context):
    respuesta = exception_handler(exc, context)
    if respuesta is None:
        return None

    datos = respuesta.data
    if isinstance(datos, dict) and "detail" in datos:
        # Errores simples (auth, permisos, not found, throttling)
        codigo = datos.get("code") or getattr(datos["detail"], "code", None) or "error"
        cuerpo = {"codigo": str(codigo), "detalle": str(datos["detail"]), "campos": {}}
    elif isinstance(datos, dict):
        # Errores de validación por campo
        cuerpo = {"codigo": "validacion", "detalle": "Datos inválidos.", "campos": datos}
    else:
        cuerpo = {"codigo": "error", "detalle": str(datos), "campos": {}}

    respuesta.data = cuerpo
    return respuesta
