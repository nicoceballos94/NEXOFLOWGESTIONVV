from rest_framework import serializers

from common.capacidades import capacidades_de

from ..models import Usuario


class SupervisorAsignableSerializer(serializers.ModelSerializer):
    """Identidad mínima para asignar dotación; no expone email ni permisos."""

    nombre_completo = serializers.SerializerMethodField()

    class Meta:
        model = Usuario
        fields = ("id", "username", "nombre_completo")
        read_only_fields = fields

    def get_nombre_completo(self, obj) -> str:
        return obj.get_full_name().strip() or obj.username


class UsuarioActualSerializer(serializers.ModelSerializer):
    roles = serializers.ListField(child=serializers.CharField(), read_only=True)
    # Qué acciones de escritura habilita el rol. El front las usa para esconder botones
    # (A5); la seguridad real sigue en permissions.py. Ver common/capacidades.py.
    capacidades = serializers.SerializerMethodField()

    class Meta:
        model = Usuario
        # is_superuser: el superusuario no está en ningún grupo, así que `roles` viene vacío;
        # el front lo usa para mostrar "Administrador" en vez de "Sin rol asignado" (MENOR-01).
        fields = (
            "id", "username", "first_name", "last_name", "email",
            "is_superuser", "roles", "capacidades",
        )
        read_only_fields = fields

    def get_capacidades(self, obj) -> dict:
        return capacidades_de(obj)
