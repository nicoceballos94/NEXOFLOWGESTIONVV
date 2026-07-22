"""Fusiona los puestos que solo difieren en mayúsculas/espacios (paso 1 de 2).

El catálogo se puebla escribiendo el puesto a mano en el alta, así que "Chofer", "chofer"
y "CHOFER " convivían como filas distintas (el unique de Postgres es case-sensitive).

La fusión va ANTES del constraint (que agrega 0004) y en su PROPIA migración: Postgres no
deja crear el índice único en la misma transacción en la que se tocaron filas con FKs
("cannot CREATE INDEX ... pending trigger events"). Juntas, esta migración se caía en toda
base que tuviera duplicados —justo las que hay que arreglar—.
"""
from django.conf import settings
from django.db import migrations, models


def fusionar_duplicados(apps, schema_editor):
    """Colapsa cada grupo de variantes en un solo puesto.

    Sobrevive el más antiguo (menor id): es el que la gente viene usando. Las relaciones
    laborales de los demás se repuntan al superviviente antes de borrarlos —la FK es
    PROTECT, así que sin repuntar el delete fallaría—.
    """
    Puesto = apps.get_model("organizacion", "Puesto")
    RelacionLaboral = apps.get_model("empleados", "RelacionLaboral")

    grupos: dict[str, list] = {}
    for puesto in Puesto.objects.order_by("id"):
        grupos.setdefault((puesto.nombre or "").strip().lower(), []).append(puesto)

    for _clave, puestos in grupos.items():
        superviviente = puestos[0]
        nombre_limpio = (superviviente.nombre or "").strip()
        if superviviente.nombre != nombre_limpio:
            superviviente.nombre = nombre_limpio
            superviviente.save(update_fields=["nombre"])
        for duplicado in puestos[1:]:
            RelacionLaboral.objects.filter(puesto=duplicado).update(puesto=superviviente)
            duplicado.delete()


def revertir(apps, schema_editor):
    """Los duplicados fusionados no se pueden desfusionar: no hay a dónde volver.

    Es no-op a propósito —y no un error— para que el rollback funcione; lo que se pierde
    es información que la fusión ya descartó.
    """


class Migration(migrations.Migration):

    dependencies = [
        ('organizacion', '0002_initial'),
        # La fusión repunta RelacionLaboral: la app empleados tiene que estar creada.
        ('empleados', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Se suelta el unique case-sensitive acá: con él puesto, la fusión no podría
        # normalizar "  CHOFER  " → "Chofer" mientras "Chofer" todavía existe.
        migrations.AlterField(
            model_name='puesto',
            name='nombre',
            field=models.CharField(max_length=100),
        ),
        migrations.RunPython(fusionar_duplicados, revertir),
    ]
