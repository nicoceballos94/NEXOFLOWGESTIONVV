"""Modelos abstractos compartidos. Acá NO va lógica de negocio (regla §10.4)."""
from django.conf import settings
from django.db import models


class ModeloBase(models.Model):
    """Campos de auditoría mínimos para todos los modelos de dominio."""

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        editable=False,
        help_text="Null cuando lo crea un proceso automático.",
    )

    class Meta:
        abstract = True
