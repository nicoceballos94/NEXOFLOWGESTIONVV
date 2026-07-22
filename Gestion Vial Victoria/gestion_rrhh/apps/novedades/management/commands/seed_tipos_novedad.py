"""Catálogo semilla de tipos de novedad (§5, P4). Idempotente.

Los flags gobiernan las reglas del dominio: `admite_prorroga` habilita la cadena §6 bis;
`justifica_ausencia` es lo que en la fase de asistencias cubrirá una jornada AUSENTE;
`ocupa_periodo` impide que dos novedades convivan en las mismas fechas; `requiere_cantidad_horas`
es HORAS_EXTRA (carga manual, P4).

Ojo con FALTA: ocupa el período (nadie falta y está de licencia el mismo día) pero no
justifica la ausencia. Y HORAS_EXTRA es el único que no ocupa período.
"""
from django.core.management.base import BaseCommand

from ...models import TipoNovedad

TIPOS = [
    # (codigo, nombre, justifica_ausencia, ocupa_periodo, requiere_certificado,
    #  admite_prorroga, req_horas)
    ("FALTA", "Falta", False, True, False, False, False),
    ("LICENCIA_MEDICA", "Licencia médica", True, True, True, True, False),
    ("ACCIDENTE", "Accidente / ART", True, True, True, True, False),
    ("VACACIONES", "Vacaciones", True, True, False, False, False),
    ("PERMISO", "Permiso", True, True, False, False, False),
    ("HORAS_EXTRA", "Horas extra", False, False, False, False, True),
]


class Command(BaseCommand):
    help = "Crea/actualiza el catálogo de tipos de novedad (idempotente)."

    def handle(self, *args, **options):
        for codigo, nombre, justif, ocupa, cert, prorroga, horas in TIPOS:
            _, creado = TipoNovedad.objects.update_or_create(
                codigo=codigo,
                defaults={
                    "nombre": nombre,
                    "justifica_ausencia": justif,
                    "ocupa_periodo": ocupa,
                    "requiere_certificado": cert,
                    "admite_prorroga": prorroga,
                    "requiere_cantidad_horas": horas,
                    "activo": True,
                },
            )
            self.stdout.write(f"Tipo {codigo}: {'creado' if creado else 'actualizado'}")
        self.stdout.write(self.style.SUCCESS("Catálogo de tipos de novedad listo."))
