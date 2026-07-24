from django.contrib import admin

from common.admin import AdminSoloLectura

from .models import Novedad, TipoNovedad


@admin.register(TipoNovedad)
class TipoNovedadAdmin(AdminSoloLectura, admin.ModelAdmin):
    list_display = (
        "codigo", "nombre", "admite_prorroga", "justifica_ausencia", "ocupa_periodo", "activo"
    )
    list_filter = ("admite_prorroga", "justifica_ausencia", "ocupa_periodo", "activo")
    search_fields = ("codigo", "nombre")


@admin.register(Novedad)
class NovedadAdmin(AdminSoloLectura, admin.ModelAdmin):
    list_display = ("id", "empleado", "tipo_novedad", "estado", "fecha_desde", "fecha_hasta")
    list_filter = ("estado", "tipo_novedad", "clasificacion")
    search_fields = ("empleado__apellido", "empleado__legajo", "motivo")
    autocomplete_fields = ("empleado", "relacion_laboral", "novedad_origen")
    raw_id_fields = ("aprobada_por",)
