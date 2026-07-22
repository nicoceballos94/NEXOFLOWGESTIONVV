"""Datos semilla del grupo empresarial. Idempotente."""
from django.core.management import call_command
from django.core.management.base import BaseCommand

from ...models import Empresa, Parametro, Sector
from ...selectors import CLAVE_DIAS_AVISO, DIAS_AVISO_DEFAULT

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
        # Solo contratos: cada tipo de documento lleva su propio `dias_aviso` en el catálogo.
        # get_or_create y no update_or_create: si RRHH cambió el umbral desde Configuración,
        # volver a correr el seed no debe pisarle la decisión.
        _, creado = Parametro.objects.get_or_create(
            clave=CLAVE_DIAS_AVISO,
            defaults={
                "valor": {"dias": DIAS_AVISO_DEFAULT},
                "descripcion": "Días de anticipación con que se avisa el fin de un contrato.",
            },
        )
        self.stdout.write(
            f"Parámetro {CLAVE_DIAS_AVISO}: {'creado' if creado else 'ya existía'}"
        )
        call_command("seed_tipos_novedad")
        call_command("seed_tipos_documento")
        self.stdout.write(self.style.SUCCESS("Seed inicial listo."))
