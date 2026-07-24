"""Bitácora consultable desde el admin, de solo lectura.

Es la superficie de consulta de la fase 1: `/admin/auditoria/registroauditoria/` ya deja
filtrar por acción, entidad, usuario y fecha antes de que exista la API o la pantalla en
Ceibo. Sirve para operar desde el día uno.

**Nada acá se puede crear, editar ni borrar**, ni siquiera siendo superusuario. Una
bitácora que el auditado puede retocar no es una bitácora — y el admin de Django, sin
esto, permite exactamente eso con dos clics.
"""
from django.contrib import admin
from django.utils.html import format_html_join

from .models import RegistroAuditoria


@admin.register(RegistroAuditoria)
class RegistroAuditoriaAdmin(admin.ModelAdmin):
    list_display = (
        "momento", "usuario_nombre", "accion", "empleado", "objeto_repr", "cambios"
    )
    list_filter = ("accion", "entidad", "momento")
    # Buscar por legajo o apellido responde "mostrame todo lo de esta persona" sin filtro
    # aparte: es la consulta que la columna `empleado` existe para hacer barata.
    search_fields = (
        "usuario_nombre",
        "objeto_repr",
        "empleado__legajo",
        "empleado__apellido",
    )
    date_hierarchy = "momento"
    list_select_related = ("usuario", "empleado")

    @admin.display(description="Cambios")
    def cambios(self, obj):
        """Resumen legible del diff: `estado: ACTIVA → FINALIZADA`, un renglón por campo."""
        claves = sorted(set(obj.valores_antes) | set(obj.valores_despues))
        if not claves:
            return "—"
        return format_html_join(
            "",
            "<div><b>{}</b>: {} → {}</div>",
            (
                (
                    clave,
                    obj.valores_antes.get(clave, "—"),
                    obj.valores_despues.get(clave, "—"),
                )
                for clave in claves
            ),
        )

    def get_readonly_fields(self, request, obj=None):
        return [campo.name for campo in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
