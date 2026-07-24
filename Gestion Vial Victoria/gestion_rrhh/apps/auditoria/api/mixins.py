"""Mixins de escritura auditada para catálogos sin reglas de orquestación."""

from django.db import IntegrityError, transaction
from rest_framework.exceptions import ValidationError

from apps.auditoria.services import Accion, registrar_evento, tomar_foto


class CatalogoAuditadoMixin:
    """Registra altas y cambios, y traduce carreras de unicidad a un 400 estable."""

    def perform_create(self, serializer):
        try:
            with transaction.atomic():
                objeto = serializer.save(creado_por=self.request.user)
                registrar_evento(
                    actor=self.request.user,
                    accion=Accion.CATALOGO_CREADO,
                    objeto=objeto,
                )
        except IntegrityError:
            raise ValidationError(
                {"detalle": "El elemento ya existe o contradice una restricción del catálogo."}
            )

    def perform_update(self, serializer):
        try:
            with transaction.atomic():
                modelo = type(serializer.instance)
                bloqueado = modelo._default_manager.select_for_update().get(
                    pk=serializer.instance.pk
                )
                # ``is_valid`` necesariamente ocurrió antes de entrar al mixin. Se cambia
                # la instancia por la fila fresca para que un PATCH concurrente no guarde
                # encima de datos obsoletos ni construya una foto “antes” falsa. Los
                # serializers con reglas relacionales vuelven a validarlas en update().
                serializer.instance = bloqueado
                antes = tomar_foto(bloqueado)
                objeto = serializer.save()
                registrar_evento(
                    actor=self.request.user,
                    accion=Accion.CATALOGO_ACTUALIZADO,
                    objeto=objeto,
                    antes=antes,
                    solo_si_cambia=True,
                )
        except IntegrityError:
            raise ValidationError(
                {"detalle": "El cambio duplica o contradice otro elemento del catálogo."}
            )
