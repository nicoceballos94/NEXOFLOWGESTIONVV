"""Datos de prueba para dev: dotación con documentos y novedades realistas.

Complementa a `seed_inicial` (catálogos) y `seed_usuarios_demo` (usuarios). Crea una
dotación chica pero variada para que un backend recién migrado tenga con qué mostrarse:

- empleados en las dos empresas y varios sectores, con su relación laboral ACTIVA;
- documentos con vencimientos escalonados (vencido / por vencer / al día) para encender
  Alertas y el semáforo;
- novedades en distintos estados (registrada, aprobada, rechazada, anulada), una cadena
  madre + prórroga, un accidente con praxis y horas extra.

Todo pasa por los **services** (crear_empleado, crear_novedad, aprobar/rechazar/…), así
que respeta las reglas del dominio: legajo asignado por el backend, no-solapamiento,
transiciones válidas. Nada de escritura directa que saltee una invariante.

Idempotente por DNI: reejecutar no duplica (salta los empleados que ya existen). La
bitácora append-only impide borrar físicamente lo ya auditado; para regenerar el escenario
se usa una base de desarrollo descartable.

SOLO DEV. No correr en producción: inventa personas.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.empleados import services as emp_services
from apps.empleados.models import (
    Educacion,
    Empleado,
    JornadaLegal,
    TipoContrato,
    TipoDocumento,
)
from apps.novedades import services as nov_services
from apps.novedades.models import TipoNovedad
from apps.organizacion.models import Empresa, Puesto, Sector

# Dotación de prueba. `desde` en novedades es un offset firmado en días respecto de hoy
# (negativo = pasado). `dura` es la cantidad de días inclusive (None = sin fin). En
# documentos, `vence` es días desde hoy (negativo = vencido). DNIs en un rango propio
# (50-millones) para no chocar con datos reales ni entre corridas.
EMPLEADOS = [
    {
        "dni": "50000001", "nombre": "Ramón", "apellido": "Sosa",
        "email": "rsosa@vialvictoria.com.ar", "telefono": "+54 379 400-0001",
        "direccion": "Corrientes Capital", "educacion": Educacion.SECUNDARIO_COMPLETO,
        "empresa": "VIAL VICTORIA", "sector": "Obra", "puesto": "Oficial vial",
        "jornada": JornadaLegal.COMPLETA_8H, "contrato": TipoContrato.INDETERMINADO,
        "ingreso_hace_dias": 1300,
        "documentos": [
            {"tipo": "Apto médico", "numero": "AM-5001", "vence": -6},   # vencido → roja
            {"tipo": "Carnet de conducir", "numero": "CC-5001", "vence": 20},  # pronto → amarilla
        ],
        "novedades": [
            {"tipo": "FALTA", "desde": -3, "dura": 1, "clasif": "INJUSTIFICADA",
             "motivo": "No se presentó ni avisó", "estado": "REGISTRADA"},
        ],
    },
    {
        "dni": "50000002", "nombre": "Marta", "apellido": "Delgado",
        "email": "mdelgado@vialvictoria.com.ar", "telefono": "+54 379 400-0002",
        "direccion": "Corrientes Capital", "educacion": Educacion.TERCIARIO,
        "empresa": "VIAL VICTORIA", "sector": "Administración", "puesto": "Administrativa",
        "jornada": JornadaLegal.COMPLETA_8H, "contrato": TipoContrato.PLAZO_FIJO,
        "ingreso_hace_dias": 200, "contrato_vence_en_dias": 25,  # contrato por vencer
        "documentos": [
            {"tipo": "Contrato", "numero": "CT-5002", "vence": 25},
        ],
        "novedades": [
            # Cadena: licencia aprobada + una prórroga pendiente (madre APROBADA → prorrogable).
            {"tipo": "LICENCIA_MEDICA", "desde": -30, "dura": 10,
             "motivo": "Cirugía programada", "estado": "APROBADA",
             "prorroga": {"extiende_dias": 7, "motivo": "Reposo extendido por el médico"}},
        ],
    },
    {
        "dni": "50000003", "nombre": "Julio", "apellido": "Ferreyra",
        "email": "jferreyra@premocor.com.ar", "telefono": "+54 379 400-0003",
        "direccion": "Resistencia", "educacion": Educacion.SECUNDARIO_COMPLETO,
        "empresa": "PREMOCOR", "sector": "Logística", "puesto": "Chofer",
        "jornada": JornadaLegal.COMPLETA_8H, "contrato": TipoContrato.INDETERMINADO,
        "ingreso_hace_dias": 900,
        "documentos": [
            {"tipo": "CNRT", "numero": "CN-5003", "vence": 12},          # pronto → amarilla
            {"tipo": "Carnet de conducir", "numero": "CC-5003", "vence": 400},  # al día
        ],
        "novedades": [
            {"tipo": "ACCIDENTE", "desde": -12, "dura": 20,
             "motivo": "Accidente in itinere", "estado": "APROBADA",
             "praxis": {"turno_en_dias": -8, "fin_estimada_en_dias": 8}},
        ],
    },
    {
        "dni": "50000004", "nombre": "Sonia", "apellido": "Vera",
        "email": "svera@premocor.com.ar", "telefono": "+54 379 400-0004",
        "direccion": "Resistencia", "educacion": Educacion.PRIMARIO_COMPLETO,
        "empresa": "PREMOCOR", "sector": "Obra", "puesto": "Ayudante",
        "jornada": JornadaLegal.REDUCIDA_6H, "contrato": TipoContrato.EVENTUAL,
        "ingreso_hace_dias": 120,
        "documentos": [
            {"tipo": "Apto médico", "numero": "AM-5004", "vence": 300},  # al día
        ],
        "novedades": [
            {"tipo": "VACACIONES", "desde": 10, "dura": 5,
             "motivo": "Vacaciones acordadas", "estado": "APROBADA"},  # futuras
        ],
    },
    {
        "dni": "50000005", "nombre": "Hugo", "apellido": "Maldonado",
        "email": "hmaldonado@vialvictoria.com.ar", "telefono": "+54 379 400-0005",
        "direccion": "Corrientes Capital", "educacion": Educacion.SECUNDARIO_INCOMPLETO,
        "empresa": "VIAL VICTORIA", "sector": "Logística", "puesto": "Chofer",
        "jornada": JornadaLegal.COMPLETA_8H, "contrato": TipoContrato.INDETERMINADO,
        "ingreso_hace_dias": 2000,
        "documentos": [
            {"tipo": "Carnet de conducir", "numero": "CC-5005", "vence": -40},  # vencido → roja
        ],
        "novedades": [
            {"tipo": "HORAS_EXTRA", "desde": -5, "dura": 1, "horas": 6,
             "motivo": "Refuerzo por cierre de obra", "estado": "REGISTRADA"},
        ],
    },
    {
        "dni": "50000006", "nombre": "Elena", "apellido": "Ríos",
        "email": "erios@premocor.com.ar", "telefono": "+54 379 400-0006",
        "direccion": "Resistencia", "educacion": Educacion.UNIVERSITARIO,
        "empresa": "PREMOCOR", "sector": "RRHH", "puesto": "Analista de RRHH",
        "jornada": JornadaLegal.COMPLETA_8H, "contrato": TipoContrato.INDETERMINADO,
        "ingreso_hace_dias": 1500,
        "documentos": [],
        "novedades": [
            {"tipo": "PERMISO", "desde": -1, "dura": 1,
             "motivo": "Trámite personal", "estado": "REGISTRADA"},
        ],
    },
    {
        "dni": "50000007", "nombre": "Raúl", "apellido": "Ojanguren",
        "email": "rojanguren@vialvictoria.com.ar", "telefono": "+54 379 400-0007",
        "direccion": "Corrientes Capital", "educacion": Educacion.PRIMARIO_COMPLETO,
        "empresa": "VIAL VICTORIA", "sector": "Obra", "puesto": "Oficial vial",
        "jornada": JornadaLegal.COMPLETA_8H, "contrato": TipoContrato.INDETERMINADO,
        "ingreso_hace_dias": 700,
        "documentos": [],
        "novedades": [
            {"tipo": "FALTA", "desde": -20, "dura": 1, "clasif": "INJUSTIFICADA",
             "motivo": "Falta sin aviso; se rechaza el descargo", "estado": "RECHAZADA",
             "motivo_estado": "El descargo no justifica la ausencia"},
        ],
    },
    {
        "dni": "50000008", "nombre": "Beatriz", "apellido": "Cano",
        "email": "bcano@premocor.com.ar", "telefono": "+54 379 400-0008",
        "direccion": "Resistencia", "educacion": Educacion.SECUNDARIO_COMPLETO,
        "empresa": "PREMOCOR", "sector": "Administración", "puesto": "Administrativa",
        "jornada": JornadaLegal.MEDIA_4H, "contrato": TipoContrato.INDETERMINADO,
        "ingreso_hace_dias": 400,
        "documentos": [
            {"tipo": "Apto médico", "numero": "AM-5008", "vence": 45},  # al día
        ],
        "novedades": [
            {"tipo": "LICENCIA_MEDICA", "desde": -40, "dura": 5,
             "motivo": "Cargada por error en el empleado equivocado", "estado": "ANULADA",
             "motivo_estado": "Se cargó en la persona equivocada"},
        ],
    },
]


class Command(BaseCommand):
    help = "Crea datos de prueba (empleados, documentos, novedades). Solo dev. Idempotente."

    def add_arguments(self, parser):
        parser.add_argument(
            "--empleados", type=int, default=len(EMPLEADOS),
            help=f"Cuántos empleados del set crear (1..{len(EMPLEADOS)}; default: todos).",
        )
        parser.add_argument(
            "--reset", action="store_true",
            help=(
                "No disponible desde que la auditoría es append-only; use una base "
                "descartable para regenerar el escenario."
            ),
        )
        parser.add_argument(
            "--skip-catalogos", action="store_true",
            help="No correr seed_inicial primero (asume que los catálogos ya existen).",
        )

    def handle(self, *args, **options):
        if options["reset"]:
            raise CommandError(
                "No se permite borrar físicamente datos auditados. "
                "Regenerá el escenario en una base de desarrollo descartable."
            )
        cuantos = max(1, min(options["empleados"], len(EMPLEADOS)))
        datos = EMPLEADOS[:cuantos]

        if not options["skip_catalogos"]:
            # Idempotente: garantiza roles, empresas, sectores y catálogos de tipos.
            call_command("seed_inicial")

        actor = self._actor()
        hoy = timezone.localdate()

        creados = 0
        for d in datos:
            if Empleado.objects.filter(dni=d["dni"]).exists():
                self.stdout.write(
                    f"  {d['nombre']} {d['apellido']} (DNI {d['dni']}): "
                    "ya existe, se salta"
                )
                continue
            self._crear_empleado(actor, hoy, d)
            creados += 1

        self.stdout.write(self.style.SUCCESS(
            f"Datos de prueba listos: {creados} empleado(s) nuevo(s) de {len(datos)} pedidos."
        ))

    # ---- helpers ----

    def _actor(self):
        User = get_user_model()
        actor = (
            User.objects.filter(username="demo_admin").first()
            or User.objects.filter(is_superuser=True).first()
        )
        if actor is None:
            actor, creado = User.objects.get_or_create(
                username="__seed_datos_prueba__",
                defaults={
                    "first_name": "Carga",
                    "last_name": "de desarrollo",
                    "is_active": False,
                },
            )
            if creado:
                actor.set_unusable_password()
                actor.save(update_fields=["password"])
            self.stdout.write(
                self.style.WARNING(
                    "Se usa un actor técnico deshabilitado para atribuir la carga demo."
                )
            )
        return actor

    def _puesto(self, nombre, sector):
        """Reusa o crea el puesto dentro de su sector, respetando unicidad CI."""
        existente = Puesto.objects.filter(
            nombre__iexact=nombre,
            sector=sector,
        ).first()
        if existente:
            return existente
        return Puesto.objects.create(nombre=nombre, sector=sector)

    def _crear_empleado(self, actor, hoy, d):
        empresa = Empresa.objects.get(nombre=d["empresa"])
        sector = Sector.objects.get(nombre=d["sector"])
        puesto = self._puesto(d["puesto"], sector)

        datos_empleado = {
            "dni": d["dni"], "nombre": d["nombre"], "apellido": d["apellido"],
            "email": d.get("email", ""), "telefono": d.get("telefono", ""),
            "direccion": d.get("direccion", ""), "educacion": d.get("educacion", ""),
        }
        datos_relacion = {
            "empresa": empresa, "sector": sector, "puesto": puesto,
            "fecha_ingreso": hoy - timedelta(days=d["ingreso_hace_dias"]),
            "jornada_legal": d.get("jornada", ""),
            "tipo_contrato": d.get("contrato", TipoContrato.INDETERMINADO),
        }
        if d.get("contrato_vence_en_dias") is not None:
            datos_relacion["fecha_vencimiento_contrato"] = hoy + timedelta(
                days=d["contrato_vence_en_dias"]
            )

        empleado = emp_services.crear_empleado(
            actor=actor, datos_empleado=datos_empleado, datos_relacion=datos_relacion
        )
        self.stdout.write(f"  Empleado {empleado.nombre_natural} (leg. {empleado.legajo})")

        for doc in d.get("documentos", []):
            emp_services.crear_documento(
                actor=actor, empleado=empleado,
                tipo_documento=TipoDocumento.objects.get(nombre=doc["tipo"]),
                numero=doc.get("numero", ""),
                fecha_vencimiento=hoy + timedelta(days=doc["vence"]),
            )
            vence = hoy + timedelta(days=doc["vence"])
            self.stdout.write(f"    · doc {doc['tipo']} (vence {vence})")

        for sc in d.get("novedades", []):
            self._crear_novedad(actor, hoy, empleado, sc)

    def _crear_novedad(self, actor, hoy, empleado, sc):
        tipo = TipoNovedad.objects.get(codigo=sc["tipo"])
        desde = hoy + timedelta(days=sc["desde"])
        dura = sc.get("dura")
        hasta = desde + timedelta(days=dura - 1) if dura else None

        datos = {
            "empleado": empleado, "tipo_novedad": tipo,
            "fecha_desde": desde, "fecha_hasta": hasta,
            "motivo": sc.get("motivo", ""),
        }
        if sc.get("clasif"):
            datos["clasificacion"] = sc["clasif"]
        if sc.get("horas") is not None:
            datos["cantidad_horas"] = sc["horas"]
        if sc.get("praxis"):
            p = sc["praxis"]
            datos["requiere_praxis"] = True
            datos["fecha_turno_praxis"] = hoy + timedelta(days=p["turno_en_dias"])
            datos["fecha_fin_estimada"] = hoy + timedelta(days=p["fin_estimada_en_dias"])

        nov = nov_services.crear_novedad(actor=actor, datos=datos)

        estado = sc.get("estado", "REGISTRADA")
        if estado == "APROBADA":
            nov_services.aprobar_novedad(actor=actor, novedad=nov)
        elif estado == "RECHAZADA":
            nov_services.rechazar_novedad(
                actor=actor,
                novedad=nov,
                motivo=sc.get("motivo_estado", ""),
            )
        elif estado == "ANULADA":
            nov_services.anular_novedad(
                actor=actor,
                novedad=nov,
                motivo=sc.get("motivo_estado", ""),
            )
        self.stdout.write(f"    · novedad {tipo.nombre} [{estado}] {desde}")

        # La prórroga exige la madre APROBADA (la valida el service): nace REGISTRADA.
        if sc.get("prorroga"):
            pr = sc["prorroga"]
            nueva_fin = nov.fecha_hasta + timedelta(days=pr["extiende_dias"])
            nov_services.prorrogar_novedad(
                actor=actor, novedad=nov, fecha_hasta_nueva=nueva_fin, motivo=pr.get("motivo", ""),
            )
            self.stdout.write(f"      + prórroga hasta {nueva_fin} [REGISTRADA]")
