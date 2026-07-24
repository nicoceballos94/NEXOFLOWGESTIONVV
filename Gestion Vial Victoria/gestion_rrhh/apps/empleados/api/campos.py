"""Campos DRF que normalizan antes de ejecutar validadores como UniqueValidator."""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.fields import empty


class IdentificadorNormalizadoField(serializers.CharField):
    def __init__(self, *args, normalizador, **kwargs):
        self.normalizador = normalizador
        super().__init__(*args, **kwargs)

    def run_validation(self, data=empty):
        if data is empty:
            return super().run_validation(data)
        try:
            normalizado = self.normalizador(data)
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.messages) from error
        # El CharField y sus validators reciben ya la representación persistible.
        return super().run_validation(normalizado)
