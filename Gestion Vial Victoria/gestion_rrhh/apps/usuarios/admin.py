"""Admin de usuarios, con auditoría enganchada acá y no en un service.

Es la excepción a la regla de "auditar desde los services" (§14), y por un motivo concreto:
en MVP1 **no existe ABM de usuarios por API** — `api/views.py` solo tiene sesión y
`/me`. La única forma de crear un usuario o cambiarle el rol es este admin, así que un
service que auditara esas operaciones no tendría quién lo llamara. Cuando exista el ABM
real, la llamada se muda al service y esto queda como red.

Quién es Admin y desde cuándo es de las preguntas más caras de responder sin registro: los
roles son Grupos (§7), y un cambio de grupo no deja ninguna huella en la fila del usuario.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.auditoria.services import Accion, registrar_evento, tomar_foto
from common import roles

from .models import Usuario


def _foto_con_roles(usuario: Usuario) -> dict:
    """Los roles son un M2M a Grupos: `tomar_foto` solo ve campos concretos y no los alcanza.

    Se agregan a mano porque son EL dato que interesa auditar de un usuario; sin esto, el
    ascenso de alguien a Admin quedaría como un evento con el diff vacío.
    """
    return tomar_foto(usuario) | {"roles": sorted(usuario.roles)}


class UsuarioAdminChangeForm(UserChangeForm):
    """Impide dejar equipos activos apuntando a una identidad que ya no supervisa."""

    def clean(self):
        datos = super().clean()
        usuario = self.instance
        if not usuario.pk:
            return datos

        grupos = datos.get("groups")
        nombres = (
            set(grupos.values_list("name", flat=True))
            if grupos is not None
            else set(usuario.groups.values_list("name", flat=True))
        )
        errores = {}
        if roles.SERVICIO in nombres and nombres != {roles.SERVICIO}:
            errores["groups"] = (
                "El rol Servicio es exclusivo y no se combina con roles de acceso humano."
            )
        if usuario.relaciones_supervisadas.filter(estado="ACTIVA").exists():
            if datos.get("is_active") is False:
                errores["is_active"] = (
                    "Reasigná o quitá primero todas las relaciones laborales activas "
                    "a cargo de este supervisor."
                )
            if roles.SUPERVISOR not in nombres or roles.SERVICIO in nombres:
                errores["groups"] = (
                    "Este usuario tiene empleados activos a cargo: debe conservar el rol "
                    "Supervisor y no puede convertirse en una identidad de Servicio."
                )
        if errores:
            raise ValidationError(errores)
        return datos


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    form = UsuarioAdminChangeForm
    list_display = ("username", "email", "first_name", "last_name", "is_active", "is_staff")

    def save_model(self, request, obj, form, change):
        # La foto previa se relee de la BASE, no de `obj`: para cuando el admin llama a
        # `save_model`, el form ya pisó la instancia con los valores nuevos, así que
        # `tomar_foto(obj)` acá devolvería el "después" disfrazado de "antes" y el diff
        # saldría siempre vacío (una desactivación no se registraría nunca).
        previo = Usuario.objects.filter(pk=obj.pk).first() if change else None
        # Va en `request` y no en `self`: el ModelAdmin es único para todo el proceso, y
        # guardar estado ahí haría que dos ediciones simultáneas se pisaran la foto.
        request._auditoria_antes = _foto_con_roles(previo) if previo else {}
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        # El evento se asienta acá y no en `save_model` a propósito: los grupos son M2M y
        # Django los escribe DESPUÉS del save. En `save_model`, el cambio de rol todavía no
        # ocurrió y el diff saldría siempre sin roles — justo lo que se quiere registrar.
        super().save_related(request, form, formsets, change)

        usuario = form.instance
        antes = getattr(request, "_auditoria_antes", {})
        despues = _foto_con_roles(usuario)

        if not change:
            accion = Accion.USUARIO_CREADO
        elif antes.get("is_active") and not despues.get("is_active"):
            accion = Accion.USUARIO_DESACTIVADO  # la baja de un usuario tiene nombre propio
        else:
            accion = Accion.USUARIO_ACTUALIZADO

        registrar_evento(
            actor=request.user,
            accion=accion,
            objeto=usuario,
            antes=antes,
            despues=despues,
            solo_si_cambia=change,  # abrir y guardar sin tocar nada no es un hecho
        )

    def has_delete_permission(self, request, obj=None):
        """Las cuentas se desactivan; borrar destruiría su identidad histórica."""
        return False

    def user_change_password(self, request, id, form_url=""):
        if request.method != "POST":
            return super().user_change_password(request, id, form_url)
        # La contraseña y su constancia son una sola operación. Sin este bloque, un
        # fallo de auditoría podía dejar la clave cambiada aunque la request terminara 500.
        with transaction.atomic():
            response = super().user_change_password(request, id, form_url)
            if response.status_code in (301, 302):
                usuario = Usuario.objects.get(pk=id)
                registrar_evento(
                    actor=request.user,
                    accion=Accion.USUARIO_PASSWORD_CAMBIADA,
                    objeto=usuario,
                    antes={},
                    despues={"password": "«oculto»"},
                )
            return response


admin.site.unregister(Group)


@admin.register(Group)
class GrupoSoloLecturaAdmin(admin.ModelAdmin):
    """Los roles canónicos se crean por bootstrap y no se renombran desde el admin.

    La membresía se sigue gestionando en cada usuario y queda auditada por
    ``UsuarioAdmin``. Renombrar o borrar un grupo cambiaría privilegios en masa sin pasar
    por ese registro.
    """

    list_display = ("name",)
    search_fields = ("name",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
