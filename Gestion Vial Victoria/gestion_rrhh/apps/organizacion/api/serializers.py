from rest_framework import serializers

from ..models import Empresa, Puesto, Sector


class EmpresaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Empresa
        fields = ("id", "nombre", "razon_social", "cuit", "referente_rrhh", "activa")


class SectorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sector
        fields = ("id", "nombre", "activo")


class PuestoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Puesto
        fields = ("id", "nombre", "sector", "activo")
