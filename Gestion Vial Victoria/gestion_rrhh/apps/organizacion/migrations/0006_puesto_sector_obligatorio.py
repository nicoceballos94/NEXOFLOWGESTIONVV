"""Unicidad de puesto por sector y obligatoriedad segura para datos legados.

El CHECK se crea NOT VALID: PostgreSQL lo aplica a toda fila nueva o modificada, pero no
obliga a inventar sector para puestos huérfanos preexistentes. Cuando esos datos se
clasifiquen, se puede ejecutar ``VALIDATE CONSTRAINT`` sin otra migración de esquema.
"""

import django.db.models.deletion
from django.db import migrations, models
from django.db.models.functions import Lower


class Migration(migrations.Migration):
    dependencies = [
        ("organizacion", "0005_reubicar_puestos_por_sector"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="puesto",
            options={
                "ordering": ["sector__nombre", "nombre"],
                "verbose_name": "puesto",
                "verbose_name_plural": "puestos",
            },
        ),
        migrations.AlterField(
            model_name="puesto",
            name="sector",
            field=models.ForeignKey(
                help_text="Sector al que pertenece el puesto. Obligatorio para toda carga nueva.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="puestos",
                to="organizacion.sector",
            ),
        ),
        migrations.AddConstraint(
            model_name="puesto",
            constraint=models.UniqueConstraint(
                Lower("nombre"),
                "sector",
                name="puesto_nombre_sector_unico_ci",
            ),
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE organizacion_puesto "
                        "ADD CONSTRAINT puesto_sector_requerido "
                        "CHECK (sector_id IS NOT NULL) NOT VALID"
                    ),
                    reverse_sql=(
                        "ALTER TABLE organizacion_puesto "
                        "DROP CONSTRAINT IF EXISTS puesto_sector_requerido"
                    ),
                )
            ],
            state_operations=[
                migrations.AddConstraint(
                    model_name="puesto",
                    constraint=models.CheckConstraint(
                        condition=models.Q(sector__isnull=False),
                        name="puesto_sector_requerido",
                    ),
                )
            ],
        ),
    ]
