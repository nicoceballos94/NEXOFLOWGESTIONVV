from rest_framework import serializers

from ..models import Usuario


class UsuarioActualSerializer(serializers.ModelSerializer):
    roles = serializers.ListField(child=serializers.CharField(), read_only=True)

    class Meta:
        model = Usuario
        fields = ("id", "username", "first_name", "last_name", "email", "roles")
        read_only_fields = fields
