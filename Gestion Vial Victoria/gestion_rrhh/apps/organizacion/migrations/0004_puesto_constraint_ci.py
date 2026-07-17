"""Unicidad case-insensitive de Puesto (paso 2 de 2).

Va separada de 0003 a propósito: el índice único no se puede crear en la misma transacción
que la fusión de datos (Postgres: "cannot CREATE INDEX ... pending trigger events"). 0003
deja el catálogo sin duplicados; acá se sostiene esa garantía para cualquier cliente de la
API, no solo para el que pase por la vista.
"""
import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizacion', '0003_puesto_nombre_unico_ci'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='puesto',
            constraint=models.UniqueConstraint(
                django.db.models.functions.text.Lower('nombre'),
                name='puesto_nombre_unico_ci',
            ),
        ),
    ]
