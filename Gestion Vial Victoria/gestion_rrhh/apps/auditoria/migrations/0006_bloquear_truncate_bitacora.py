"""Completa la garantía append-only bloqueando también TRUNCATE.

El trigger por fila de 0003 impide UPDATE y DELETE, pero PostgreSQL no ejecuta
triggers por fila ante TRUNCATE. Sin este trigger por sentencia, la credencial de
la aplicación podría vaciar toda la bitácora sin violar la protección existente.
"""

from django.db import migrations


CREAR_TRIGGER = """
DROP TRIGGER IF EXISTS auditoria_append_only_truncate
ON auditoria_registroauditoria;

CREATE TRIGGER auditoria_append_only_truncate
BEFORE TRUNCATE ON auditoria_registroauditoria
FOR EACH STATEMENT EXECUTE FUNCTION auditoria_bloquear_mutacion();
"""

QUITAR_TRIGGER = """
DROP TRIGGER IF EXISTS auditoria_append_only_truncate
ON auditoria_registroauditoria;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("auditoria", "0005_alter_registroauditoria_accion_and_more"),
    ]

    operations = [
        migrations.RunSQL(CREAR_TRIGGER, reverse_sql=QUITAR_TRIGGER),
    ]
