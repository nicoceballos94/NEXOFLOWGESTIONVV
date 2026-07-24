import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def completar_agregado(apps, _schema_editor):
    Registro = apps.get_model("auditoria", "RegistroAuditoria")
    for registro in Registro.objects.only("id", "entidad", "objeto_id").iterator():
        registro.agregado_entidad = registro.entidad
        registro.agregado_id = registro.objeto_id
        registro.save(update_fields=["agregado_entidad", "agregado_id"])


CREAR_PROTECCION = """
CREATE OR REPLACE FUNCTION auditoria_bloquear_mutacion()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'La bitácora es append-only: no se permite % sobre auditoria_registroauditoria',
        TG_OP
        USING ERRCODE = '55000';
END;
$$;

DROP TRIGGER IF EXISTS auditoria_append_only ON auditoria_registroauditoria;
CREATE TRIGGER auditoria_append_only
BEFORE UPDATE OR DELETE ON auditoria_registroauditoria
FOR EACH ROW EXECUTE FUNCTION auditoria_bloquear_mutacion();
"""

QUITAR_PROTECCION = """
DROP TRIGGER IF EXISTS auditoria_append_only ON auditoria_registroauditoria;
DROP FUNCTION IF EXISTS auditoria_bloquear_mutacion();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("auditoria", "0002_registroauditoria_empleado_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="registroauditoria",
            name="agregado_entidad",
            field=models.CharField(default="", max_length=50),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="registroauditoria",
            name="agregado_id",
            field=models.PositiveBigIntegerField(
                blank=True,
                help_text="PK de la raíz funcional. Permite reconstruir una cadena completa.",
                null=True,
            ),
        ),
        migrations.RunPython(completar_agregado, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="registroauditoria",
            name="agregado_entidad",
            field=models.CharField(
                db_index=True,
                help_text=(
                    "Raíz funcional a la que pertenece el hecho. En una prórroga es la "
                    "novedad madre; en los demás casos coincide con la entidad."
                ),
                max_length=50,
            ),
        ),
        migrations.AddIndex(
            model_name="registroauditoria",
            index=models.Index(
                fields=["agregado_entidad", "agregado_id", "-momento"],
                name="idx_audit_agregado",
            ),
        ),
        migrations.AlterField(
            model_name="registroauditoria",
            name="usuario",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Null si lo hizo un proceso automático. Los usuarios auditados no se "
                    "borran físicamente: se desactivan, para preservar la autoría."
                ),
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="registroauditoria",
            name="empleado",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "De qué PERSONA habla el evento, aunque `entidad` sea otra cosa. "
                    "Denormalizado a propósito para reconstruir el historial completo. "
                    "Null en eventos que no son de nadie en particular. La persona "
                    "referenciada no puede borrarse físicamente."
                ),
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="empleados.empleado",
            ),
        ),
        migrations.RunSQL(CREAR_PROTECCION, reverse_sql=QUITAR_PROTECCION),
    ]
