from rest_framework import serializers

from common.capacidades import capacidades_de

from ..models import Usuario


class UsuarioActualSerializer(serializers.ModelSerializer):
    roles = serializers.ListField(child=serializers.CharField(), read_only=True)
    # Qué acciones de escritura habilita el rol. El front las usa para esconder botones
    # (A5); la seguridad real sigue en permissions.py. Ver common/capacidades.py.
    capacidades = serializers.SerializerMethodField()

    class Meta:
        model = Usuario
        fields = ("id", "username", "first_name", "last_name", "email", "roles", "capacidades")
        read_only_fields = fields

    def get_capacidades(self, obj) -> dict:
        return capacidades_de(obj)
