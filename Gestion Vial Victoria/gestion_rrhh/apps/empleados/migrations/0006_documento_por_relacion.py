"""Vincula cada documento con la relación laboral a la que pertenece.

El backfill solo atribuye cuando hay una respuesta inequívoca: una única relación total,
o una única vigencia que contiene la fecha de creación del documento. Si hay casos
ambiguos, la migración se detiene antes de instalar el nuevo contrato: RRHH debe resolverlos
sin que el despliegue oculte documentos históricos.
"""

import django.db.models.deletion
from django.db import migrations, models


def atribuir_documentos_legados(apps, schema_editor):
    DocumentoEmpleado = apps.get_model("empleados", "DocumentoEmpleado")
    RelacionLaboral = apps.get_model("empleados", "RelacionLaboral")

    relaciones_por_empleado = {}
    for relacion in RelacionLaboral.objects.order_by(
        "empleado_id", "fecha_ingreso", "id"
    ).iterator():
        relaciones_por_empleado.setdefault(relacion.empleado_id, []).append(relacion)

    ambiguos = []
    for documento in DocumentoEmpleado.objects.filter(
        relacion_laboral__isnull=True
    ).iterator():
        relaciones = relaciones_por_empleado.get(documento.empleado_id, [])
        elegida = relaciones[0] if len(relaciones) == 1 else None
        if len(relaciones) > 1:
            fecha_documento = documento.creado_en.date()
            candidatas = [
                relacion
                for relacion in relaciones
                if relacion.fecha_ingreso <= fecha_documento
                and (
                    relacion.fecha_egreso is None
                    or fecha_documento <= relacion.fecha_egreso
                )
            ]
            if len(candidatas) == 1:
                elegida = candidatas[0]
        if elegida is not None:
            DocumentoEmpleado.objects.filter(pk=documento.pk).update(
                relacion_laboral_id=elegida.pk
            )
        else:
            ambiguos.append(
                {
                    "documento": documento.pk,
                    "empleado": documento.empleado_id,
                    "relaciones": [relacion.pk for relacion in relaciones],
                }
            )

    if ambiguos:
        muestra = ", ".join(
            (
                f"documento {fila['documento']} / empleado {fila['empleado']} "
                f"/ relaciones {fila['relaciones']}"
            )
            for fila in ambiguos[:20]
        )
        extra = len(ambiguos) - min(len(ambiguos), 20)
        sufijo = f"; y {extra} caso(s) más" if extra else ""
        raise RuntimeError(
            "No se puede atribuir de forma inequívoca cada documento legado. "
            f"Revisá: {muestra}{sufijo}."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("empleados", "0005_relacion_supervisor_y_vigencias"),
    ]

    operations = [
        migrations.AddField(
            model_name="documentoempleado",
            name="relacion_laboral",
            field=models.ForeignKey(
                blank=True,
                help_text="Puede ser nula solo en documentos históricos no atribuibles.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="documentos",
                to="empleados.relacionlaboral",
            ),
        ),
        migrations.RunPython(
            atribuir_documentos_legados,
            migrations.RunPython.noop,
            elidable=False,
        ),
        migrations.AlterField(
            model_name="documentoempleado",
            name="relacion_laboral",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="documentos",
                to="empleados.relacionlaboral",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="documentoempleado",
            name="uniq_documento_vigente_por_tipo",
        ),
        migrations.AddConstraint(
            model_name="documentoempleado",
            constraint=models.UniqueConstraint(
                fields=("relacion_laboral", "tipo_documento"),
                name="uniq_documento_por_relacion_tipo",
            ),
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE empleados_documentoempleado "
                        "ADD CONSTRAINT documento_relacion_requerida "
                        "CHECK (relacion_laboral_id IS NOT NULL)"
                    ),
                    reverse_sql=(
                        "ALTER TABLE empleados_documentoempleado "
                        "DROP CONSTRAINT IF EXISTS documento_relacion_requerida"
                    ),
                )
            ],
            state_operations=[
                migrations.AddConstraint(
                    model_name="documentoempleado",
                    constraint=models.CheckConstraint(
                        condition=models.Q(relacion_laboral__isnull=False),
                        name="documento_relacion_requerida",
                    ),
                )
            ],
        ),
    ]
