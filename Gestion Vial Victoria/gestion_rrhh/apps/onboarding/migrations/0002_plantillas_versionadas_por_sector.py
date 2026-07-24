import django.db.models.deletion
from django.db import migrations, models
from django.db.models.functions import Coalesce


def migrar_estado(apps, _schema_editor):
    Plantilla = apps.get_model("onboarding", "PlantillaChecklist")
    # El esquema anterior permitía varias plantillas inactivas por empresa/tipo.
    # Asignarles a todas version=1 haría fallar la nueva unicidad. Se numeran por
    # cronología dentro de cada alcance; la única activa conserva el estado publicada.
    alcance_actual = None
    version = 0
    for plantilla in Plantilla.objects.order_by(
        "empresa_id",
        "tipo_proceso",
        "creado_en",
        "id",
    ).iterator():
        alcance = (plantilla.empresa_id, plantilla.tipo_proceso)
        if alcance != alcance_actual:
            alcance_actual = alcance
            version = 0
        version += 1
        plantilla.version = version
        plantilla.estado = "PUBLICADA" if plantilla.activa else "ARCHIVADA"
        plantilla.save(update_fields=["version", "estado"])


class Migration(migrations.Migration):
    dependencies = [
        ("onboarding", "0001_initial"),
        ("organizacion", "0004_puesto_constraint_ci"),
    ]

    operations = [
        migrations.AddField(
            model_name="plantillachecklist",
            name="sector",
            field=models.ForeignKey(
                blank=True,
                help_text="Sector al que aplica. Null es una plantilla general de respaldo.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="plantillas_checklist",
                to="organizacion.sector",
            ),
        ),
        migrations.AddField(
            model_name="plantillachecklist",
            name="version",
            field=models.PositiveSmallIntegerField(default=1, editable=False),
        ),
        migrations.AddField(
            model_name="plantillachecklist",
            name="estado",
            field=models.CharField(
                choices=[
                    ("BORRADOR", "Borrador"),
                    ("PUBLICADA", "Publicada"),
                    ("ARCHIVADA", "Archivada"),
                ],
                default="BORRADOR",
                max_length=10,
            ),
        ),
        migrations.RunPython(migrar_estado, migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name="plantillachecklist",
            name="uniq_plantilla_activa_por_empresa_tipo",
        ),
        migrations.RemoveField(
            model_name="plantillachecklist",
            name="activa",
        ),
        migrations.AlterField(
            model_name="procesoempleado",
            name="plantilla",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Plantilla fotografiada al crear el proceso "
                    "(referencia; puede quedar null)."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="procesos",
                to="onboarding.plantillachecklist",
            ),
        ),
        migrations.AddConstraint(
            model_name="plantillachecklist",
            constraint=models.UniqueConstraint(
                models.F("empresa"),
                Coalesce("sector", models.Value(0)),
                models.F("tipo_proceso"),
                models.F("version"),
                name="uniq_version_plantilla_por_alcance",
            ),
        ),
        migrations.AddConstraint(
            model_name="plantillachecklist",
            constraint=models.UniqueConstraint(
                models.F("empresa"),
                Coalesce("sector", models.Value(0)),
                models.F("tipo_proceso"),
                condition=models.Q(estado="PUBLICADA"),
                name="uniq_plantilla_publicada_por_alcance",
            ),
        ),
        migrations.AddConstraint(
            model_name="plantillachecklist",
            constraint=models.UniqueConstraint(
                models.F("empresa"),
                Coalesce("sector", models.Value(0)),
                models.F("tipo_proceso"),
                condition=models.Q(estado="BORRADOR"),
                name="uniq_plantilla_borrador_por_alcance",
            ),
        ),
    ]
