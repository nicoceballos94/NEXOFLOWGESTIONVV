"""Catálogo semilla de tipos de novedad (§5, P4). Idempotente.

Los flags gobiernan las reglas del dominio: `admite_prorroga` habilita la cadena §6 bis;
`justifica_ausencia` es lo que en la fase de asistencias cubrirá una jornada AUSENTE;
`requiere_cantidad_horas` es HORAS_EXTRA (carga manual, P4).
"""
from django.core.management.base import BaseCommand

from ...models import TipoNovedad

TIPOS = [
    # (codigo, nombre, justifica_ausencia, requiere_certificado, admite_prorroga, req_horas)
    ("FALTA", "Falta", False, False, False, False),
    ("LICENCIA_MEDICA", "Licencia médica", True, True, True, False),
    ("ACCIDENTE", "Accidente / ART", True, True, True, False),
    ("VACACIONES", "Vacaciones", True, False, False, False),
    ("PERMISO", "Permiso", True, False, False, False),
    ("HORAS_EXTRA", "Horas extra", False, False, False, True),
]


class Command(BaseCommand):
    help = "Crea/actualiza el catálogo de tipos de novedad (idempotente)."

    def handle(self, *args, **options):
        for codigo, nombre, justif, cert, prorroga, horas in TIPOS:
            _, creado = TipoNovedad.objects.update_or_create(
                codigo=codigo,
                defaults={
                    "nombre": nombre,
                    "justifica_ausencia": justif,
                    "requiere_certificado": cert,
                    "admite_prorroga": prorroga,
                    "requiere_cantidad_horas": horas,
                    "activo": True,
                },
            )
            self.stdout.write(f"Tipo {codigo}: {'creado' if creado else 'actualizado'}")
        self.stdout.write(self.style.SUCCESS("Catálogo de tipos de novedad listo."))
