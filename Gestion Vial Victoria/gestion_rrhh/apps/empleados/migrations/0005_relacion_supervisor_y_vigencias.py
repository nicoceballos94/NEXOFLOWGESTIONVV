"""Supervisor, relación activa única global y vigencias no solapadas.

No se corrigen fechas ni se elige qué relación activa conservar: ambas decisiones tienen
efecto laboral. Si el legado contradice las nuevas invariantes, la migración falla antes
de quitar la constraint anterior e informa los ids que RRHH debe revisar.
"""

import django.contrib.postgres.constraints
import django.contrib.postgres.fields.ranges
import django.db.models.deletion
from django.conf import settings
from django.contrib.postgres.operations import BtreeGistExtension
from django.db import migrations, models


def validar_vigencias_legadas(apps, schema_editor):
    RelacionLaboral = apps.get_model("empleados", "RelacionLaboral")
    errores = []

    for relacion in RelacionLaboral.objects.filter(estado="ACTIVA").select_related(
        "empresa", "sector", "puesto"
    ):
        faltantes = []
        if relacion.sector_id is None:
            faltantes.append("sector")
        if relacion.puesto_id is None:
            faltantes.append("puesto")
        if faltantes:
            errores.append(
                f"relación activa {relacion.id} sin {', '.join(faltantes)}"
            )
            continue
        if not relacion.empresa.activa:
            errores.append(
                f"relación activa {relacion.id} usa empresa inactiva "
                f"{relacion.empresa_id}"
            )
        if not relacion.sector.activo:
            errores.append(
                f"relación activa {relacion.id} usa sector inactivo "
                f"{relacion.sector_id}"
            )
        if not relacion.puesto.activo:
            errores.append(
                f"relación activa {relacion.id} usa puesto inactivo "
                f"{relacion.puesto_id}"
            )
        if relacion.puesto.sector_id != relacion.sector_id:
            errores.append(
                f"relación activa {relacion.id}: puesto {relacion.puesto_id} "
                f"no pertenece al sector {relacion.sector_id}"
            )

    for relacion in RelacionLaboral.objects.only(
        "id", "estado", "fecha_egreso", "motivo_egreso"
    ):
        if relacion.estado == "ACTIVA" and (
            relacion.fecha_egreso is not None or relacion.motivo_egreso
        ):
            errores.append(
                f"relación activa {relacion.id} tiene datos de baja cargados"
            )
        if relacion.estado == "FINALIZADA" and (
            relacion.fecha_egreso is None or not relacion.motivo_egreso
        ):
            errores.append(
                f"relación finalizada {relacion.id} no tiene fecha y motivo de egreso"
            )

    activos = (
        RelacionLaboral.objects.filter(estado="ACTIVA")
        .values("empleado_id")
        .annotate(total=models.Count("id"))
        .filter(total__gt=1)
        .order_by("empleado_id")
    )
    for fila in activos[:20]:
        ids = list(
            RelacionLaboral.objects.filter(
                empleado_id=fila["empleado_id"],
                estado="ACTIVA",
            )
            .order_by("id")
            .values_list("id", flat=True)
        )
        errores.append(
            f"empleado {fila['empleado_id']} tiene relaciones activas {ids}"
        )

    empleados = RelacionLaboral.objects.order_by().values_list(
        "empleado_id", flat=True
    ).distinct()
    for empleado_id in empleados.iterator():
        filas = list(
            RelacionLaboral.objects.filter(empleado_id=empleado_id)
            .order_by("fecha_ingreso", "id")
            .values("id", "fecha_ingreso", "fecha_egreso")
        )
        limite_hasta = None
        limite_id = None
        hay_previa = False
        for fila in filas:
            desde = fila["fecha_ingreso"]
            hasta = fila["fecha_egreso"]
            if hasta is not None and hasta < desde:
                errores.append(
                    f"relación {fila['id']} tiene egreso {hasta} anterior al ingreso {desde}"
                )
            if hay_previa and (limite_hasta is None or desde <= limite_hasta):
                errores.append(
                    f"empleado {empleado_id}: relaciones {limite_id} y {fila['id']} "
                    "se solapan"
                )
            if not hay_previa or limite_hasta is not None:
                if hasta is None or limite_hasta is None or hasta > limite_hasta:
                    limite_hasta = hasta
                    limite_id = fila["id"]
            hay_previa = True

    if errores:
        muestra = "\n- ".join(errores[:30])
        extra = len(errores) - min(len(errores), 30)
        sufijo = f"\n... y {extra} conflicto(s) más." if extra else ""
        raise RuntimeError(
            "No se pueden instalar las constraints de relaciones laborales. "
            "Corregí estos datos sin inventar fechas ni responsables:\n- "
            f"{muestra}{sufijo}"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("empleados", "0004_empleado_foto"),
        ("organizacion", "0006_puesto_sector_obligatorio"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="relacionlaboral",
            name="supervisor",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Supervisor actual de esta relación. Null si todavía no fue asignado."
                ),
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="relaciones_supervisadas",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(
            validar_vigencias_legadas,
            migrations.RunPython.noop,
            elidable=False,
        ),
        migrations.RemoveConstraint(
            model_name="relacionlaboral",
            name="uniq_relacion_activa_por_empresa",
        ),
        BtreeGistExtension(),
        migrations.AddConstraint(
            model_name="relacionlaboral",
            constraint=models.UniqueConstraint(
                condition=models.Q(estado="ACTIVA"),
                fields=("empleado",),
                name="uniq_relacion_activa_por_empleado",
            ),
        ),
        migrations.AddConstraint(
            model_name="relacionlaboral",
            constraint=django.contrib.postgres.constraints.ExclusionConstraint(
                expressions=[
                    ("empleado", "="),
                    (
                        models.Func(
                            "fecha_ingreso",
                            "fecha_egreso",
                            django.contrib.postgres.fields.ranges.RangeBoundary(
                                inclusive_lower=True,
                                inclusive_upper=True,
                            ),
                            function="DATERANGE",
                            output_field=django.contrib.postgres.fields.ranges.DateRangeField(),
                        ),
                        "&&",
                    ),
                ],
                name="excl_relaciones_solapadas_por_empleado",
            ),
        ),
        migrations.AddConstraint(
            model_name="relacionlaboral",
            constraint=models.CheckConstraint(
                condition=models.Q(fecha_egreso__isnull=True)
                | models.Q(fecha_egreso__gte=models.F("fecha_ingreso")),
                name="relacion_fechas_validas",
            ),
        ),
        migrations.AddConstraint(
            model_name="relacionlaboral",
            constraint=models.CheckConstraint(
                condition=models.Q(estado="FINALIZADA")
                | (
                    models.Q(sector__isnull=False)
                    & models.Q(puesto__isnull=False)
                ),
                name="relacion_activa_con_catalogos",
            ),
        ),
        migrations.AddConstraint(
            model_name="relacionlaboral",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        estado="ACTIVA",
                        fecha_egreso__isnull=True,
                        motivo_egreso="",
                    )
                    | (
                        models.Q(
                            estado="FINALIZADA",
                            fecha_egreso__isnull=False,
                        )
                        & ~models.Q(motivo_egreso="")
                    )
                ),
                name="relacion_estado_baja_coherente",
            ),
        ),
        migrations.AddIndex(
            model_name="relacionlaboral",
            index=models.Index(
                condition=models.Q(estado="ACTIVA"),
                fields=["supervisor", "empleado"],
                name="idx_rel_activa_supervisor",
            ),
        ),
    ]
