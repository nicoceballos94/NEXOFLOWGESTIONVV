"""Catálogo semilla de tipos de documento (§5, CU-06). Idempotente.

Son los documentos de la PERSONA: los que vencen y hay que renovar (spec §1.2). Cada
empleado tiene uno vigente por tipo — renovar es mover su vencimiento, no apilar copias.

Los certificados de una licencia o de un accidente NO van acá: pertenecen a la novedad
que los originó, no a la persona, y su historia se conserva sola porque las novedades no
se borran. Ver el manual (Conocimiento/DOCUMENTACION/MANUAL_USUARIO_CAMPOS.md §3.6).
"""
from django.core.management.base import BaseCommand

from ...models import TipoDocumento

TIPOS = [
    ("Carnet de conducir", "Licencia de conducir habilitante. Vence y se renueva."),
    ("Apto médico", "Examen médico periódico que habilita a trabajar."),
    ("CNRT", "Habilitación de la Comisión Nacional de Regulación del Transporte."),
    ("Contrato", "Contrato de trabajo firmado."),
]


class Command(BaseCommand):
    help = "Crea/actualiza el catálogo de tipos de documento (idempotente)."

    def handle(self, *args, **options):
        for nombre, descripcion in TIPOS:
            # `activo` no se pisa: si RRHH desactivó un tipo, volver a correr el seed no
            # debe resucitarlo. La descripción sí se actualiza (es texto del catálogo).
            _, creado = TipoDocumento.objects.update_or_create(
                nombre=nombre, defaults={"descripcion": descripcion}
            )
            estado = "creado" if creado else "actualizado"
            self.stdout.write(f"Tipo de documento {nombre}: {estado}")
        self.stdout.write(self.style.SUCCESS("Catálogo de tipos de documento listo."))
