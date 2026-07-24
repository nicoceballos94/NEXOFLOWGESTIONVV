"""Serializer de la bitácora. Solo lectura: la tabla no se escribe por API, jamás."""
from rest_framework import serializers

from ..models import RegistroAuditoria


class RegistroAuditoriaSerializer(serializers.ModelSerializer):
    accion_display = serializers.CharField(source="get_accion_display", read_only=True)
    empleado_nombre = serializers.CharField(
        source="empleado.nombre_natural", read_only=True, default=None
    )
    cambios = serializers.SerializerMethodField()

    class Meta:
        model = RegistroAuditoria
        fields = (
            "id",
            "momento",
            "usuario",
            "usuario_nombre",
            "accion",
            "accion_display",
            "entidad",
            "objeto_id",
            "objeto_repr",
            "empleado",
            "empleado_nombre",
            "cambios",
            "ip",
        )
        read_only_fields = fields

    def get_cambios(self, obj) -> list[dict]:
        """`valores_antes`/`valores_despues` fusionados en una lista lista para pintar.

        Se expone esto en vez de los dos diccionarios crudos porque es la forma en que se
        lee un cambio —"teléfono: vacío → 2664112233"— y porque no se pierde nada: las
        claves de la lista son la unión de ambos lados, y los valores son escalares (lo
        garantiza `services._valor_json`). Mandar además los dicts sería mandar lo mismo
        dos veces y obligar al front a decidir cuál usar.
        """
        claves = sorted(set(obj.valores_antes) | set(obj.valores_despues))
        return [
            {
                "campo": clave,
                "antes": obj.valores_antes.get(clave),
                "despues": obj.valores_despues.get(clave),
            }
            for clave in claves
        ]
