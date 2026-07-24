"""Validadores pequeños y compartidos para parámetros de consulta."""

from rest_framework.exceptions import ValidationError


def entero_positivo(valor, campo: str) -> int:
    """Convierte un identificador externo sin permitir que un ValueError llegue como 500."""
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        raise ValidationError({campo: "Debe ser un identificador numérico."})
    if numero <= 0:
        raise ValidationError({campo: "Debe ser un identificador positivo."})
    return numero
