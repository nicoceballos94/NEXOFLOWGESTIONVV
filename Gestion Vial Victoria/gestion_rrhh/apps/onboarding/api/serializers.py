"""Contrato I/O (§11): validación de forma. La lógica vive en services/selectors.

La tarjeta de la ficha no tiene serializer: el selector `armar_tarjeta` ya devuelve el dict
listo para el front (mismo criterio que la parametría de vencimientos). Acá van los del ABM
de plantillas y los de entrada de las acciones.
"""
from rest_framework import serializers

from apps.empleados.models import TipoDocumento
from apps.organizacion.models import Empresa

from ..models import ItemPlantilla, PlantillaChecklist, TipoItem, TipoProceso


class ItemPlantillaSerializer(serializers.ModelSerializer):
    """Salida de un ítem de plantilla, para el ABM de Configuración."""

    tipo_documento_nombre = serializers.CharField(
        source="tipo_documento.nombre", read_only=True, default=None
    )

    class Meta:
        model = ItemPlantilla
        fields = (
            "id",
            "orden",
            "etiqueta",
            "tipo_item",
            "tipo_documento",
            "tipo_documento_nombre",
            "activo",
        )


class PlantillaChecklistSerializer(serializers.ModelSerializer):
    """Salida de una plantilla con todos sus ítems (incluidos los inactivos, para el ABM)."""

    empresa_nombre = serializers.CharField(source="empresa.nombre", read_only=True)
    items = ItemPlantillaSerializer(many=True, read_only=True)

    class Meta:
        model = PlantillaChecklist
        fields = (
            "id",
            "empresa",
            "empresa_nombre",
            "tipo_proceso",
            "activa",
            "items",
        )


class CrearPlantillaSerializer(serializers.Serializer):
    empresa = serializers.PrimaryKeyRelatedField(queryset=Empresa.objects.all())
    tipo_proceso = serializers.ChoiceField(choices=TipoProceso.choices)


class ActualizarPlantillaSerializer(serializers.Serializer):
    """Solo se edita el estado activo (baja/alta lógica de la plantilla)."""

    activa = serializers.BooleanField()


class CrearItemSerializer(serializers.Serializer):
    etiqueta = serializers.CharField(max_length=120)
    tipo_item = serializers.ChoiceField(choices=TipoItem.choices, default=TipoItem.ACCION)
    tipo_documento = serializers.PrimaryKeyRelatedField(
        queryset=TipoDocumento.objects.all(), required=False, allow_null=True
    )
    orden = serializers.IntegerField(required=False, min_value=0)


class ActualizarItemSerializer(serializers.Serializer):
    etiqueta = serializers.CharField(max_length=120, required=False)
    tipo_item = serializers.ChoiceField(choices=TipoItem.choices, required=False)
    tipo_documento = serializers.PrimaryKeyRelatedField(
        queryset=TipoDocumento.objects.all(), required=False, allow_null=True
    )
    orden = serializers.IntegerField(required=False, min_value=0)
    activo = serializers.BooleanField(required=False)


class TildarItemSerializer(serializers.Serializer):
    hecho = serializers.BooleanField()
