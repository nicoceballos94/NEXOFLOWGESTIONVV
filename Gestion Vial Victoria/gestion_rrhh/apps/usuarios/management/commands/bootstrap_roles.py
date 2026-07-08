"""Crea los grupos/roles del sistema (§7). Idempotente: correr tras cada migrate."""
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from common import roles


class Command(BaseCommand):
    help = "Crea los grupos de roles (Admin, RRHH, Supervisor, Empleado, Servicio)."

    def handle(self, *args, **options):
        for nombre in roles.TODOS:
            _, creado = Group.objects.get_or_create(name=nombre)
            estado = "creado" if creado else "ya existía"
            self.stdout.write(f"Grupo {nombre}: {estado}")
        self.stdout.write(self.style.SUCCESS("Roles listos."))
