"""Validación de parámetros para consultas puntuales de empleados."""

from rest_framework import serializers

from ..identificadores import normalizar_dni
from .campos import IdentificadorNormalizadoField


class BuscarEmpleadoPorDniSerializer(serializers.Serializer):
    """Exige un DNI completo; no admite prefijos ni búsquedas aproximadas."""

    dni = IdentificadorNormalizadoField(
        normalizador=normalizar_dni,
        max_length=9,
        trim_whitespace=True,
    )
