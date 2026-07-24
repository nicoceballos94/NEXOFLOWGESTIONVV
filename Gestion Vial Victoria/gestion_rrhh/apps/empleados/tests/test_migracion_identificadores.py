import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

DESDE = [("empleados", "0006_documento_por_relacion")]
HASTA = [("empleados", "0007_normalizar_identificadores")]


@pytest.fixture
def estado_0006():
    executor = MigrationExecutor(connection)
    executor.migrate(DESDE)
    apps_anteriores = executor.loader.project_state(DESDE).apps
    yield apps_anteriores

    # Si el preflight abortó, se quitan los datos deliberadamente inválidos antes de
    # devolver el esquema al estado actual para no contaminar el test siguiente.
    executor = MigrationExecutor(connection)
    if HASTA[0] not in executor.loader.applied_migrations:
        apps_anteriores.get_model("empleados", "Empleado").objects.all().delete()
        executor = MigrationExecutor(connection)
        executor.migrate(HASTA)


def _crear(Empleado, *, legajo, dni, cuil=None, id_huella=None):
    return Empleado.objects.create(
        legajo=legajo,
        dni=dni,
        cuil=cuil,
        id_huella=id_huella,
        nombre="Nombre",
        apellido="Apellido",
    )


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("dni", "ABC"),
        ("cuil", "2030111222"),
        ("id_huella", "ß" * 26),
    ],
)
def test_migracion_aborta_antes_de_escribir_si_hay_un_invalido(
    estado_0006, campo, valor
):
    Empleado = estado_0006.get_model("empleados", "Empleado")
    valida = _crear(
        Empleado,
        legajo="0100",
        dni="30.111.222",
        cuil="20-30111222-3",
        id_huella=" huella-01 ",
    )
    datos_invalidos = {"dni": "30999888", campo: valor}
    invalida = _crear(Empleado, legajo="0101", **datos_invalidos)

    with pytest.raises(RuntimeError) as error:
        MigrationExecutor(connection).migrate(HASTA)

    assert f"id={invalida.id}" in str(error.value)
    valida.refresh_from_db()
    assert valida.dni == "30.111.222"
    assert valida.cuil == "20-30111222-3"
    assert valida.id_huella == " huella-01 "


@pytest.mark.parametrize(
    "campo,valor_primero,valor_segundo",
    [
        ("dni", "30.111.222", "30111222"),
        ("cuil", "20-30111222-3", "20301112223"),
        ("id_huella", " huella-01 ", "HUELLA-01"),
    ],
)
def test_migracion_detecta_colisiones_normalizadas_sin_escribir(
    estado_0006, campo, valor_primero, valor_segundo
):
    Empleado = estado_0006.get_model("empleados", "Empleado")
    datos_primero = {"dni": "30111222", campo: valor_primero}
    datos_segundo = {"dni": "30999888", campo: valor_segundo}
    primera = _crear(Empleado, legajo="0100", **datos_primero)
    segunda = _crear(Empleado, legajo="0101", **datos_segundo)

    with pytest.raises(RuntimeError) as error:
        MigrationExecutor(connection).migrate(HASTA)

    mensaje = str(error.value)
    assert "colisiona" in mensaje
    assert f"campo={campo}" in mensaje
    assert str(primera.id) in mensaje and str(segunda.id) in mensaje
    assert valor_primero not in mensaje
    assert valor_segundo not in mensaje
    primera.refresh_from_db()
    segunda.refresh_from_db()
    assert getattr(primera, campo) == valor_primero
    assert getattr(segunda, campo) == valor_segundo


def test_migracion_normaliza_todo_el_conjunto_si_el_preflight_pasa(estado_0006):
    EmpleadoViejo = estado_0006.get_model("empleados", "Empleado")
    empleado = _crear(
        EmpleadoViejo,
        legajo="0100",
        dni="30.111.222",
        cuil="20-30111222-3",
        id_huella=" huella-01 ",
    )

    executor = MigrationExecutor(connection)
    executor.migrate(HASTA)
    apps_nuevas = executor.loader.project_state(HASTA).apps
    EmpleadoNuevo = apps_nuevas.get_model("empleados", "Empleado")
    normalizado = EmpleadoNuevo.objects.get(pk=empleado.id)

    assert normalizado.dni == "30111222"
    assert normalizado.cuil == "20301112223"
    assert normalizado.id_huella == "HUELLA-01"
