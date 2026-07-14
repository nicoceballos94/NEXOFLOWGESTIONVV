from django.db import migrations, models


def marcar_ocupa_periodo(apps, schema_editor):
    """Los tipos que ya justificaban ausencia ocupan el período, y FALTA también.

    FALTA quedó fuera del chequeo de solapamiento porque `justifica_ausencia=False` (una
    falta es una ausencia, pero injustificada), que era exactamente el bug.
    """
    TipoNovedad = apps.get_model("novedades", "TipoNovedad")
    TipoNovedad.objects.filter(justifica_ausencia=True).update(ocupa_periodo=True)
    TipoNovedad.objects.filter(codigo="FALTA").update(ocupa_periodo=True)


def revertir(apps, schema_editor):
    pass  # el campo se elimina; no hay nada que restaurar


class Migration(migrations.Migration):

    dependencies = [
        ("novedades", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="tiponovedad",
            name="ocupa_periodo",
            field=models.BooleanField(
                default=False,
                help_text="El tipo toma el día del empleado: dos novedades con este flag no "
                "pueden convivir en el mismo período (falta, licencia, accidente, vacaciones, "
                "permiso).",
            ),
        ),
        migrations.RunPython(marcar_ocupa_periodo, revertir),
    ]
