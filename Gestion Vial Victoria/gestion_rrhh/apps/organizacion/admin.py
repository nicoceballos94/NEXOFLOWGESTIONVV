from django.contrib import admin

from common.admin import AdminSoloLectura

from .models import Empresa, Parametro, Puesto, Sector


@admin.register(Empresa)
class EmpresaAdmin(AdminSoloLectura, admin.ModelAdmin):
    list_display = ("nombre", "cuit", "referente_rrhh", "activa")
    search_fields = ("nombre", "cuit")


@admin.register(Sector)
class SectorAdmin(AdminSoloLectura, admin.ModelAdmin):
    list_display = ("nombre", "activo")


@admin.register(Puesto)
class PuestoAdmin(AdminSoloLectura, admin.ModelAdmin):
    list_display = ("nombre", "sector", "activo")
    list_filter = ("sector",)


@admin.register(Parametro)
class ParametroAdmin(AdminSoloLectura, admin.ModelAdmin):
    list_display = ("clave", "descripcion")
    search_fields = ("clave",)
