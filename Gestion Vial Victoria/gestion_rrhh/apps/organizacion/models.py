"""Núcleo organizativo: empresas del grupo, sectores, puestos y parámetros (§3.1).

Grupo empresarial que comparte recursos (P1): el Sector es transversal (D11);
la pertenencia a una empresa se da por la RelacionLaboral (app empleados, MVP1).
"""
from django.conf import settings
from django.db import models

from common.models import ModeloBase


class Empresa(ModeloBase):
    nombre = models.CharField(max_length=100, unique=True)
    razon_social = models.CharField(max_length=150, blank=True)
    cuit = models.CharField(max_length=15, blank=True)
    zona_horaria = models.CharField(
        max_length=50,
        default="America/Argentina/Buenos_Aires",
        help_text="P5: hoy todas operan en la misma zona; el campo evita bloquear el futuro.",
    )
    referente_rrhh = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="empresas_referenciadas",
        help_text="Destinatario de los avisos de la empresa (D9 del cross-check §21).",
    )
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "empresa"
        verbose_name_plural = "empresas"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Sector(ModeloBase):
    """Catálogo transversal al grupo (D11): RRHH, Administración, Obra, Logística…"""

    nombre = models.CharField(max_length=100, unique=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "sector"
        verbose_name_plural = "sectores"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Puesto(ModeloBase):
    nombre = models.CharField(max_length=100, unique=True)
    sector = models.ForeignKey(
        Sector, null=True, blank=True, on_delete=models.PROTECT, related_name="puestos"
    )
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "puesto"
        verbose_name_plural = "puestos"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Parametro(ModeloBase):
    """Parametría del sistema (§21: días de aviso de vencimientos, canales, etc.)."""

    clave = models.CharField(max_length=100, unique=True)
    valor = models.JSONField(default=dict)
    descripcion = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "parámetro"
        verbose_name_plural = "parámetros"
        ordering = ["clave"]

    def __str__(self):
        return self.clave
