"""Datos semilla del grupo empresarial. Idempotente."""
from django.core.management import call_command
from django.core.management.base import BaseCommand

from ...models import Empresa, Sector

EMPRESAS = ["VIAL VICTORIA", "PREMOCOR"]
SECTORES = ["RRHH", "Administración", "Obra", "Logística"]  # catálogo del front (§21)


class Command(BaseCommand):
    help = "Crea roles, empresas del grupo y sectores base."

    def handle(self, *args, **options):
        call_command("bootstrap_roles")
        for nombre in EMPRESAS:
            _, creada = Empresa.objects.get_or_create(nombre=nombre)
            self.stdout.write(f"Empresa {nombre}: {'creada' if creada else 'ya existía'}")
        for nombre in SECTORES:
            _, creado = Sector.objects.get_or_create(nombre=nombre)
            self.stdout.write(f"Sector {nombre}: {'creado' if creado else 'ya existía'}")
        call_command("seed_tipos_novedad")
        self.stdout.write(self.style.SUCCESS("Seed inicial listo."))
