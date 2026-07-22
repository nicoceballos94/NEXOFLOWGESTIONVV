"""Usuarios de prueba, uno por rol (§7). SOLO para dev: la base traía un único
`admin` superusuario, y `is_superuser` cortocircuita `tiene_rol()`, así que con él
nunca se ejerce el sistema de roles real (scope, PII, 403). Con estos usuarios se
puede ver la app con los ojos de cada rol.

Idempotente: se puede correr tras cada `seed_inicial`. Al rol Empleado se le vincula
una ficha existente (por `--empleado-legajo`) para que su scope muestre algo: sin el
vínculo, un Empleado no ve ninguna ficha ni novedad y la prueba queda vacía.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError

from apps.empleados.models import Empleado
from common import roles

# username → rol. El Servicio (n8n/bots) se incluye por completitud aunque su uso real
# sea vía token, no login interactivo.
USUARIOS_DEMO = {
    "demo_admin": roles.ADMIN,
    "demo_rrhh": roles.RRHH,
    "demo_supervisor": roles.SUPERVISOR,
    "demo_empleado": roles.EMPLEADO,
    "demo_servicio": roles.SERVICIO,
}


class Command(BaseCommand):
    help = "Crea usuarios de prueba, uno por rol (solo dev)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            default="demo1234",
            help="Contraseña para todos los usuarios demo (default: demo1234).",
        )
        parser.add_argument(
            "--empleado-legajo",
            default="0003",
            help="Legajo del empleado a vincular con demo_empleado (default: 0003).",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        password = options["password"]
        legajo = options["empleado_legajo"]

        for username, rol in USUARIOS_DEMO.items():
            usuario, creado = User.objects.get_or_create(
                username=username,
                defaults={"first_name": "Demo", "last_name": rol},
            )
            # set_password siempre: reejecutar el seed deja la clave conocida aunque
            # alguien la haya cambiado a mano probando.
            usuario.set_password(password)
            usuario.is_superuser = False  # el rol lo dan los grupos, no el flag
            usuario.is_staff = rol == roles.ADMIN  # solo Admin entra al /admin de Django
            usuario.save()
            # Un usuario, un rol: se limpian grupos previos para que reejecutar no
            # acumule roles si se editó el mapa.
            usuario.groups.clear()
            grupo, _ = Group.objects.get_or_create(name=rol)
            usuario.groups.add(grupo)
            self.stdout.write(
                f"{username} ({rol}): {'creado' if creado else 'actualizado'}"
            )

        # Vínculo del rol Empleado con una ficha real (scope de autoconsulta).
        empleado = Empleado.objects.filter(legajo=legajo).first()
        if empleado is None:
            raise CommandError(
                f"No existe empleado con legajo {legajo!r}. "
                "Corré primero un seed con datos o pasá --empleado-legajo."
            )
        demo_emp = User.objects.get(username="demo_empleado")
        # OneToOne: si la ficha ya está tomada por otro usuario, se libera para no chocar.
        if empleado.usuario_id and empleado.usuario_id != demo_emp.id:
            self.stdout.write(
                f"  (ficha {legajo} estaba vinculada a otro usuario: se reasigna)"
            )
        empleado.usuario = demo_emp
        empleado.save(update_fields=["usuario"])
        self.stdout.write(
            f"demo_empleado ↔ {empleado.nombre} {empleado.apellido} (legajo {legajo})"
        )

        self.stdout.write(
            self.style.SUCCESS(f"Usuarios demo listos. Contraseña: {password}")
        )
