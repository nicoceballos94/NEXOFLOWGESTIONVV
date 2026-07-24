"""Normalización canónica de identificadores del legajo."""

import re

from django.core.exceptions import ValidationError

_SEPARADORES_DOCUMENTO = re.compile(r"[\s.-]+")
_DNI_CANONICO = re.compile(r"^[0-9]{6,9}$")
_CUIL_CANONICO = re.compile(r"^[0-9]{11}$")


def normalizar_dni(valor) -> str:
    normalizado = _SEPARADORES_DOCUMENTO.sub("", str(valor or ""))
    if not _DNI_CANONICO.fullmatch(normalizado):
        raise ValidationError("El DNI debe contener entre 6 y 9 dígitos.")
    return normalizado


def normalizar_cuil(valor) -> str | None:
    normalizado = _SEPARADORES_DOCUMENTO.sub("", str(valor or ""))
    if not normalizado:
        return None
    if not _CUIL_CANONICO.fullmatch(normalizado):
        raise ValidationError("El CUIL debe contener 11 dígitos.")
    return normalizado


def normalizar_id_huella(valor) -> str | None:
    normalizado = str(valor or "").strip().upper()
    if not normalizado:
        return None
    if len(normalizado) > 50:
        raise ValidationError("El identificador de huella no puede superar 50 caracteres.")
    return normalizado
