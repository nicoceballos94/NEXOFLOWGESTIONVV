from django.db import transaction
from rest_framework import serializers

from ..models import Empresa, Puesto, Sector


class EmpresaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Empresa
        fields = ("id", "nombre", "razon_social", "cuit", "referente_rrhh", "activa")

    def validate_activa(self, activa):
        if (
            self.instance is not None
            and self.instance.activa
            and not activa
            and self.instance.relaciones.filter(estado="ACTIVA").exists()
        ):
            raise serializers.ValidationError(
                "No se puede desactivar una empresa con relaciones laborales activas."
            )
        return activa

    @transaction.atomic
    def update(self, instance, validated_data):
        bloqueada = Empresa.objects.select_for_update().get(pk=instance.pk)
        activa = validated_data.get("activa", bloqueada.activa)
        self.instance = bloqueada
        self.validate_activa(activa)
        return super().update(bloqueada, validated_data)


class SectorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sector
        fields = ("id", "nombre", "activo")

    def validate_activo(self, activo):
        if self.instance is None or not self.instance.activo or activo:
            return activo
        if self.instance.relaciones.filter(estado="ACTIVA").exists():
            raise serializers.ValidationError(
                "No se puede desactivar un sector con relaciones laborales activas."
            )
        if self.instance.puestos.filter(activo=True).exists():
            raise serializers.ValidationError(
                "Desactivá primero los puestos activos de este sector."
            )
        return activo

    @transaction.atomic
    def update(self, instance, validated_data):
        bloqueado = Sector.objects.select_for_update().get(pk=instance.pk)
        activo = validated_data.get("activo", bloqueado.activo)
        self.instance = bloqueado
        self.validate_activo(activo)
        return super().update(bloqueado, validated_data)


class PuestoSerializer(serializers.ModelSerializer):
    sector = serializers.PrimaryKeyRelatedField(queryset=Sector.objects.filter(activo=True))

    class Meta:
        model = Puesto
        fields = ("id", "nombre", "sector", "activo")

    def validate(self, attrs):
        sector = attrs.get("sector", getattr(self.instance, "sector", None))
        nombre = str(attrs.get("nombre", getattr(self.instance, "nombre", ""))).strip()
        activo = attrs.get("activo", getattr(self.instance, "activo", True))

        if sector is None:
            raise serializers.ValidationError({"sector": "El puesto debe pertenecer a un sector."})
        if not sector.activo and activo:
            raise serializers.ValidationError(
                {"sector": "No se puede usar un sector inactivo para un puesto activo."}
            )
        if self.instance is not None:
            if (
                self.instance.sector_id != sector.id
                and self.instance.relaciones.exists()
            ):
                raise serializers.ValidationError(
                    {
                        "sector": (
                            "Un puesto ya utilizado no se mueve de sector; "
                            "creá otro puesto en el sector correcto."
                        )
                    }
                )
            if (
                self.instance.activo
                and not activo
                and self.instance.relaciones.filter(estado="ACTIVA").exists()
            ):
                raise serializers.ValidationError(
                    {
                        "activo": (
                            "No se puede desactivar un puesto usado por una "
                            "relación laboral activa."
                        )
                    }
                )

        repetido = Puesto.objects.filter(sector=sector, nombre__iexact=nombre)
        if self.instance is not None:
            repetido = repetido.exclude(pk=self.instance.pk)
        if repetido.exists():
            raise serializers.ValidationError(
                {"nombre": "Ya existe un puesto con ese nombre dentro del sector."}
            )

        attrs["nombre"] = nombre
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        sector = Sector.objects.select_for_update().get(
            pk=validated_data["sector"].pk
        )
        validated_data["sector"] = sector
        validated_data = self.validate(dict(validated_data))
        return super().create(validated_data)

    @transaction.atomic
    def update(self, instance, validated_data):
        sector_objetivo = validated_data.get("sector", instance.sector)
        sector_objetivo = Sector.objects.select_for_update().get(
            pk=sector_objetivo.pk
        )
        bloqueado = Puesto.objects.select_for_update().get(pk=instance.pk)
        validated_data["sector"] = sector_objetivo
        self.instance = bloqueado
        validated_data = self.validate(dict(validated_data))
        return super().update(bloqueado, validated_data)
