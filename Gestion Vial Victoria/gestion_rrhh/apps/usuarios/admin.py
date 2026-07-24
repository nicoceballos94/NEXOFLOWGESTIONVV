"""Admin de usuarios, con auditoría enganchada acá y no en un service.

Es la excepción a la regla de "auditar desde los services" (§14), y por un motivo concreto:
en MVP1 **no existe ABM de usuarios por API** — `api/views.py` solo tiene login, refresh y
`/me`. La única forma de crear un usuario o cambiarle el rol es este admin, así que un
service que auditara esas operaciones no tendría quién lo llamara. Cuando exista el ABM
real, la llamada se muda al service y esto queda como red.

Quién es Admin y desde cuándo es de las preguntas más caras de responder sin registro: los
roles son Grupos (§7), y un cambio de grupo no deja ninguna huella en la fila del usuario.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.auditoria.services import Accion, registrar_evento, tomar_foto

from .models import Usuario


def _foto_con_roles(usuario: Usuario) -> dict:
    """Los roles son un M2M a Grupos: `tomar_foto` solo ve campos concretos y no los alcanza.

    Se agregan a mano porque son EL dato que interesa auditar de un usuario; sin esto, el
    ascenso de alguien a Admin quedaría como un evento con el diff vacío.
    """
    return tomar_foto(usuario) | {"roles": sorted(usuario.roles)}


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
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
