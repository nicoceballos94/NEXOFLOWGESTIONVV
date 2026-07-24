import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q


MOTIVO_LEGADO = "Migrado: el sistema anterior no registró un motivo estructurado."


def completar_relacion_y_motivos(apps, _schema_editor):
    Novedad = apps.get_model("novedades", "Novedad")
    Relacion = apps.get_model("empleados", "RelacionLaboral")

    # En el contrato histórico, una FALTA sin fecha final significaba "ese día".
    # PostgreSQL, en cambio, interpreta daterange(desde, NULL) como abierto y esa fila
    # bloquearía todas las novedades futuras. Se materializa el único dato inequívoco.
    Novedad.objects.filter(
        tipo_novedad__codigo="FALTA",
        fecha_hasta__isnull=True,
    ).update(fecha_hasta=models.F("fecha_desde"))

    fechas_invalidas = list(
        Novedad.objects.filter(fecha_hasta__lt=models.F("fecha_desde"))
        .order_by("id")
        .values_list("id", flat=True)[:50]
    )
    if fechas_invalidas:
        raise RuntimeError(
            "No se puede exigir fecha_hasta >= fecha_desde. Corregí primero las "
            f"novedades con ids: {fechas_invalidas}."
        )

    sin_relacion = []
    for novedad in Novedad.objects.filter(relacion_laboral__isnull=True).iterator():
        posibles = list(
            Relacion.objects.filter(
                empleado_id=novedad.empleado_id,
                fecha_ingreso__lte=novedad.fecha_desde,
            )
            .order_by("-fecha_ingreso", "-id")
        )
        candidatas = [
            relacion
            for relacion in posibles
            if (
                relacion.fecha_egreso is None
                or (
                    novedad.fecha_hasta is not None
                    and relacion.fecha_egreso >= novedad.fecha_hasta
                )
            )
        ]
        if len(candidatas) != 1:
            sin_relacion.append(novedad.pk)
            continue
        relacion = candidatas[0]
        novedad.relacion_laboral_id = relacion.pk
        novedad.save(update_fields=["relacion_laboral_id"])

    if sin_relacion:
        ids = ", ".join(map(str, sin_relacion[:20]))
        raise RuntimeError(
            "No se pudo determinar la relación laboral de las novedades: "
            f"{ids}. Corregí esos datos antes de desplegar."
        )

    Novedad.objects.filter(estado="RECHAZADA", motivo_rechazo="").update(
        motivo_rechazo=MOTIVO_LEGADO
    )
    Novedad.objects.filter(estado="ANULADA", motivo_anulacion="").update(
        motivo_anulacion=MOTIVO_LEGADO
    )


class Migration(migrations.Migration):
    dependencies = [
        ("novedades", "0004_adjuntonovedad"),
        ("empleados", "0005_relacion_supervisor_y_vigencias"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="novedad",
            name="motivo_rechazo",
            field=models.CharField(
                blank=True,
                editable=False,
                help_text="Razón estructurada y obligatoria cuando el estado es RECHAZADA.",
                max_length=500,
            ),
        ),
        migrations.AddField(
            model_name="novedad",
            name="motivo_anulacion",
            field=models.CharField(
                blank=True,
                editable=False,
                help_text="Razón estructurada y obligatoria cuando el estado es ANULADA.",
                max_length=500,
            ),
        ),
        migrations.AddField(
            model_name="novedad",
            name="rechazada_en",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="novedad",
            name="rechazada_por",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="novedades_rechazadas",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="novedad",
            name="anulada_en",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="novedad",
            name="anulada_por",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="novedades_anuladas",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(completar_relacion_y_motivos, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="novedad",
            name="relacion_laboral",
            field=models.ForeignKey(
                help_text=(
                    "Contexto empresa/contrato obligatorio; se deriva de la relación activa."
                ),
                on_delete=django.db.models.deletion.PROTECT,
                related_name="novedades",
                to="empleados.relacionlaboral",
            ),
        ),
        migrations.AddConstraint(
            model_name="novedad",
            constraint=models.CheckConstraint(
                condition=models.Q(fecha_hasta__isnull=True)
                | models.Q(fecha_hasta__gte=models.F("fecha_desde")),
                name="novedad_fechas_validas",
            ),
        ),
        migrations.AddConstraint(
            model_name="novedad",
            constraint=models.CheckConstraint(
                condition=Q(cantidad_horas__isnull=True) | Q(cantidad_horas__gt=0),
                name="novedad_horas_positivas_o_null",
            ),
        ),
        migrations.AddConstraint(
            model_name="novedad",
            constraint=models.CheckConstraint(
                condition=~Q(estado="RECHAZADA") | ~Q(motivo_rechazo=""),
                name="novedad_rechazada_exige_motivo",
            ),
        ),
        migrations.AddConstraint(
            model_name="novedad",
            constraint=models.CheckConstraint(
                condition=~Q(estado="ANULADA") | ~Q(motivo_anulacion=""),
                name="novedad_anulada_exige_motivo",
            ),
        ),
    ]
