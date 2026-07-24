import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError, transaction

from apps.empleados.identificadores import normalizar_cuil, normalizar_dni
from apps.empleados.models import Empleado
from apps.organizacion.models import Empresa, Puesto, Sector

pytestmark = pytest.mark.django_db


@pytest.fixture
def empresa():
    sector = Sector.objects.create(nombre="Operaciones")
    puesto = Puesto.objects.create(nombre="Chofer", sector=sector)
    empresa = Empresa.objects.create(nombre="Vial Victoria")
    empresa._sector = sector
    empresa._puesto = puesto
    return empresa


def _payload_alta(empresa, **cambios):
    datos = {
        "dni": "30111222",
        "nombre": "Juan",
        "apellido": "Pérez",
        "relacion": {
            "empresa": empresa.id,
            "sector": empresa._sector.id,
            "puesto": empresa._puesto.id,
            "fecha_ingreso": "2025-01-01",
        },
    }
    datos.update(cambios)
    return datos


def _empleado(**cambios):
    datos = {
        "legajo": "0100",
        "dni": "30111222",
        "nombre": "Juan",
        "apellido": "Pérez",
    }
    datos.update(cambios)
    return Empleado(**datos)


def test_modelo_normaliza_identificadores_aunque_no_se_use_la_api():
    empleado = _empleado(
        dni="30.111.222",
        cuil="20-30111222-3",
        id_huella=" huella-77 ",
    )

    empleado.full_clean()
    empleado.save()

    empleado.refresh_from_db()
    assert empleado.dni == "30111222"
    assert empleado.cuil == "20301112223"
    assert empleado.id_huella == "HUELLA-77"


def test_modelo_convierte_identificadores_opcionales_vacios_a_null():
    empleado = _empleado(cuil=" -- ", id_huella=" \t ")

    empleado.save()

    empleado.refresh_from_db()
    assert empleado.cuil is None
    assert empleado.id_huella is None


@pytest.mark.parametrize(
    "cambios,campo",
    [
        ({"dni": "ABC123"}, "dni"),
        ({"dni": "12345"}, "dni"),
        ({"cuil": "2030111222"}, "cuil"),
        ({"id_huella": "x" * 51}, "id_huella"),
    ],
)
def test_modelo_rechaza_identificadores_invalidos_antes_de_guardar(cambios, campo):
    empleado = _empleado(**cambios)

    with pytest.raises(DjangoValidationError) as error:
        empleado.save()

    assert campo in error.value.message_dict
    assert not Empleado.objects.exists()


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("dni", "30.111.222"),
        ("cuil", "20-30111222-3"),
        ("id_huella", " huella-77 "),
        ("id_huella", "huella-77"),
    ],
)
def test_constraints_frenan_escrituras_que_saltean_save(campo, valor):
    empleado = _empleado()
    setattr(empleado, campo, valor)

    with pytest.raises(DatabaseError), transaction.atomic():
        Empleado.objects.bulk_create([empleado])


def test_normalizacion_y_constraints_usan_solo_digitos_ascii():
    with pytest.raises(DjangoValidationError):
        normalizar_dni("١٢٣٤٥٦")
    with pytest.raises(DjangoValidationError):
        normalizar_cuil("٢٠٣٠١١١٢٢٢٣")


def test_serializer_detecta_duplicados_despues_de_normalizar(
    cliente_rrhh, empresa
):
    primera = cliente_rrhh.post(
        "/api/v1/empleados/",
        _payload_alta(
            empresa,
            dni="30111222",
            cuil="20301112223",
            id_huella="HUELLA-77",
        ),
        format="json",
    )
    assert primera.status_code == 201, primera.data

    duplicada_dni = cliente_rrhh.post(
        "/api/v1/empleados/",
        _payload_alta(empresa, dni="30.111.222"),
        format="json",
    )
    duplicada_cuil = cliente_rrhh.post(
        "/api/v1/empleados/",
        _payload_alta(
            empresa,
            dni="30999888",
            cuil="20-30111222-3",
        ),
        format="json",
    )
    duplicada_huella = cliente_rrhh.post(
        "/api/v1/empleados/",
        _payload_alta(
            empresa,
            dni="30999887",
            id_huella=" huella-77 ",
        ),
        format="json",
    )

    assert duplicada_dni.status_code == 400
    assert "dni" in duplicada_dni.data["campos"]
    assert duplicada_cuil.status_code == 400
    assert "cuil" in duplicada_cuil.data["campos"]
    assert duplicada_huella.status_code == 400
    assert "id_huella" in duplicada_huella.data["campos"]
