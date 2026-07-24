from django.contrib import admin

from common.admin import AdminSoloLectura

from .models import DocumentoEmpleado, Empleado, RelacionLaboral, TipoDocumento


class RelacionLaboralInline(admin.TabularInline):
    model = RelacionLaboral
    extra = 0
    fields = (
        "empresa",
        "sector",
        "puesto",
        "supervisor",
        "fecha_ingreso",
        "estado",
        "fecha_egreso",
    )
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class DominioSoloLecturaAdmin(admin.ModelAdmin):
    """El dominio se muta por services; el admin queda como consola de consulta."""

    def get_readonly_fields(self, request, obj=None):
        return [campo.name for campo in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Empleado)
class EmpleadoAdmin(DominioSoloLecturaAdmin):
    list_display = ("legajo", "apellido", "nombre", "dni", "activo")
    search_fields = ("legajo", "dni", "nombre", "apellido")
    list_filter = ("exento_marcacion", "educacion")
    inlines = [RelacionLaboralInline]


@admin.register(RelacionLaboral)
class RelacionLaboralAdmin(DominioSoloLecturaAdmin):
    list_display = (
        "empleado",
        "empresa",
        "sector",
        "puesto",
        "supervisor",
        "estado",
        "fecha_ingreso",
        "fecha_egreso",
    )
    list_filter = ("estado", "empresa", "sector", "supervisor")
    search_fields = ("empleado__legajo", "empleado__apellido")


@admin.register(TipoDocumento)
class TipoDocumentoAdmin(AdminSoloLectura, admin.ModelAdmin):
    list_display = ("nombre", "activo")
    search_fields = ("nombre",)

@admin.register(DocumentoEmpleado)
class DocumentoEmpleadoAdmin(DominioSoloLecturaAdmin):
    list_display = (
        "empleado",
        "relacion_laboral",
        "tipo_documento",
        "numero",
        "fecha_vencimiento",
    )
    list_filter = ("tipo_documento",)
    search_fields = ("empleado__legajo", "empleado__apellido", "numero")
