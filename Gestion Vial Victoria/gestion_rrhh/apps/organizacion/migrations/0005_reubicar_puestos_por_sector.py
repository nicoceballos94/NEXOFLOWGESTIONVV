"""Reubica puestos legados usando únicamente sectores demostrados por sus relaciones.

Un mismo nombre podía usarse en varios sectores porque el catálogo era global. La
migración conserva el puesto original en el sector donde más se usó, crea una copia para
cada otro sector y repunta las relaciones. Un puesto sin ninguna relación que permita
inferir sector queda null: inventarle uno sería falsear historia.
"""

from django.db import migrations, models
from django.db.models import Count


def _puesto_en_sector(Puesto, *, fuente, sector_id):
    nombre = (fuente.nombre or "").strip()
    existente = (
        Puesto.objects.filter(sector_id=sector_id, nombre__iexact=nombre)
        .order_by("id")
        .first()
    )
    if existente is not None:
        return existente
    return Puesto.objects.create(
        nombre=nombre,
        sector_id=sector_id,
        activo=fuente.activo,
        creado_por_id=fuente.creado_por_id,
    )


def reubicar_puestos(apps, schema_editor):
    Puesto = apps.get_model("organizacion", "Puesto")
    RelacionLaboral = apps.get_model("empleados", "RelacionLaboral")

    # Primero, los puestos sin sector que sí tienen usos inequívocos. Si aparecen en varios
    # sectores, el de mayor uso conserva el id histórico y los demás reciben una copia.
    for puesto in Puesto.objects.filter(sector__isnull=True).order_by("id"):
        usos = list(
            RelacionLaboral.objects.filter(
                puesto_id=puesto.id,
                sector_id__isnull=False,
            )
            .values("sector_id")
            .annotate(total=Count("id"))
            .order_by("-total", "sector_id")
        )
        if not usos:
            continue

        puesto.sector_id = usos[0]["sector_id"]
        puesto.save(update_fields=["sector"])
        for uso in usos[1:]:
            destino = _puesto_en_sector(
                Puesto,
                fuente=puesto,
                sector_id=uso["sector_id"],
            )
            RelacionLaboral.objects.filter(
                puesto_id=puesto.id,
                sector_id=uso["sector_id"],
            ).update(puesto_id=destino.id)

    # Después se corrige cada relación. Un sector vacío se infiere del puesto; una
    # discordancia explícita conserva el sector de la relación y clona/reusa el puesto allí.
    for relacion in RelacionLaboral.objects.exclude(puesto_id__isnull=True).iterator():
        puesto = Puesto.objects.get(pk=relacion.puesto_id)
        if relacion.sector_id is None:
            if puesto.sector_id is not None:
                RelacionLaboral.objects.filter(pk=relacion.pk).update(
                    sector_id=puesto.sector_id
                )
            continue
        if puesto.sector_id == relacion.sector_id:
            continue
        destino = _puesto_en_sector(
            Puesto,
            fuente=puesto,
            sector_id=relacion.sector_id,
        )
        RelacionLaboral.objects.filter(pk=relacion.pk).update(puesto_id=destino.id)


class Migration(migrations.Migration):
    dependencies = [
        ("empleados", "0004_empleado_foto"),
        ("organizacion", "0004_puesto_constraint_ci"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="puesto",
            name="puesto_nombre_unico_ci",
        ),
        migrations.RunPython(
            reubicar_puestos,
            migrations.RunPython.noop,
            elidable=False,
        ),
    ]
