from django.contrib import admin

from .models import DocumentoEmpleado, Empleado, RelacionLaboral, TipoDocumento


class RelacionLaboralInline(admin.TabularInline):
    model = RelacionLaboral
    extra = 0
    fields = ("empresa", "sector", "puesto", "fecha_ingreso", "estado", "fecha_egreso")


@admin.register(Empleado)
class EmpleadoAdmin(admin.ModelAdmin):
    list_display = ("legajo", "apellido", "nombre", "dni", "activo")
    search_fields = ("legajo", "dni", "nombre", "apellido")
    list_filter = ("exento_marcacion", "educacion")
    inlines = [RelacionLaboralInline]


@admin.register(RelacionLaboral)
class RelacionLaboralAdmin(admin.ModelAdmin):
    list_display = ("empleado", "empresa", "sector", "estado", "fecha_ingreso", "fecha_egreso")
    list_filter = ("estado", "empresa", "sector")
    search_fields = ("empleado__legajo", "empleado__apellido")


@admin.register(TipoDocumento)
class TipoDocumentoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "activo")
    search_fields = ("nombre",)


@admin.register(DocumentoEmpleado)
class DocumentoEmpleadoAdmin(admin.ModelAdmin):
    list_display = ("empleado", "tipo_documento", "numero", "fecha_vencimiento")
    list_filter = ("tipo_documento",)
    search_fields = ("empleado__legajo", "empleado__apellido", "numero")
