"""Lectura de la bitácora (§11-12). Sin reglas de negocio: acá solo se consulta.

Las tres preguntas que se le hacen, y el índice que responde cada una:
- "¿qué le pasó a esta persona?" → `empleado` (`idx_audit_empleado`)
- "¿quién tocó este objeto?"     → `entidad` + `objeto_id` (`idx_audit_objeto`)
- "¿qué hizo Fulano el martes?"  → `usuario` + rango de fechas (`idx_audit_usuario`)
"""
from .models import RegistroAuditoria


def registros():
    """Queryset base. El `select_related` evita un N+1 de 25 filas por página.

    Sin él, serializar una página cuesta 50 queries extra (autor y persona de cada
    renglón), que es justo lo que hace inusable una pantalla de bitácora.
    """
    return RegistroAuditoria.objects.select_related("usuario", "empleado")
