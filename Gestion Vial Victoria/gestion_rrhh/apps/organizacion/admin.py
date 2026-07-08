from django.contrib import admin

from .models import Empresa, Parametro, Puesto, Sector


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "cuit", "referente_rrhh", "activa")
    search_fields = ("nombre", "cuit")


@admin.register(Sector)
class SectorAdmin(admin.ModelAdmin):
    list_display = ("nombre", "activo")


@admin.register(Puesto)
class PuestoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "sector", "activo")
    list_filter = ("sector",)


@admin.register(Parametro)
class ParametroAdmin(admin.ModelAdmin):
    list_display = ("clave", "descripcion")
    search_fields = ("clave",)
