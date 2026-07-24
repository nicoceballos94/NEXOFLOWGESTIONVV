# Informe de cierre técnico del MVP1

**Sistema:** Gestión RRHH · Grupo Vial Victoria

**Fecha de corte:** 2026-07-24

**Alcance:** remediación de seguridad, consistencia, dominio, frontend, auditoría,
infraestructura y documentación del MVP1.

## 1. Conclusión ejecutiva

La remediación del código quedó implementada y validada localmente. El repositorio ya
contiene la arquitectura objetivo para una VPS con Docker y Nginx Proxy Manager, junto
con migraciones, controles de datos, pruebas y documentación.

El estado de salida es:

| Área | Estado |
|---|---|
| Código y migraciones del MVP1 | Completo y con gates verdes |
| Auditoría append-only | Completa y probada |
| Frontend por roles | Completo y probado contra API real |
| Imágenes y topología Docker | Construidas y validadas localmente |
| Datos existentes | Bloqueados hasta corrección de RRHH |
| Despliegue en VPS | No ejecutado |
| Punto 10 en desarrollo separado | No modificado |

Por lo tanto, el resultado es **GO técnico condicionado / NO-GO de despliegue hoy**.
No debe ejecutarse `migrate` sobre la VPS hasta resolver los bloqueos de datos del
apartado 5 y repetir el ensayo con un dump fresco.

## 2. Cambios implementados

### Seguridad y privacidad

- Autenticación humana mediante sesión Django y cookie `HttpOnly`, `Secure` y
  `SameSite=Strict` en producción.
- CSRF obligatorio y API same-origin; se eliminaron JWT y credenciales persistidas en
  JavaScript.
- Throttle de login compartido entre workers de una única réplica.
- Contraseñas nuevas con mínimo de 12 caracteres y Argon2 como hasher preferido.
- Rol Servicio exclusivo, reservado para M2M futuro; su login humano se rechaza.
- Scopes cerrados para Admin, RRHH, Supervisor y Empleado.
- Listado de empleados sin DNI, CUIL, domicilio, contacto, huella ni historia completa.
- Consulta exacta por DNI separada, restringida y auditada para alta/reingreso.
- Novedades y archivos médicos reducen campos según rol y relación con la persona.
- Documentos y fotos se descargan por endpoints autenticados; `media/` no es público.
- Subidas limitadas por tamaño, extensión, firma real, integridad y dimensiones; las
  fotos se recodifican sin metadatos.

### Reglas de dominio e integridad

- Una persona puede tener historia laboral, pero solo una relación activa en todo el
  grupo y ninguna vigencia superpuesta.
- Cada relación exige empresa, sector y un puesto perteneciente a ese sector.
- Los puestos se parametrizan por sector.
- El Supervisor tiene N empleados mediante una asignación explícita en la relación
  activa.
- El reingreso crea una relación nueva y vuelve a pedir empresa, sector, puesto, fecha,
  supervisor, documentación y onboarding.
- Los documentos pertenecen a la relación laboral y no se reutilizan para completar un
  reingreso.
- Onboarding/offboarding se resuelve por empresa, sector y tipo; las plantillas se
  versionan y las publicadas son inmutables.
- Novedades tienen workflow explícito para tomar, aprobar, rechazar, cerrar y anular.
- Rechazar o anular exige motivo; cerrar un rango abierto exige su fecha final.
- Se validan cronología, pertenencia a la relación, horas, prórrogas y solapamientos.
- Constraints de PostgreSQL y locks transaccionales cierran carreras concurrentes.

### Auditoría

- Bitácora con acción semántica, actor congelado, fecha, IP validada, agregado,
  empleado afectado y diff.
- Los eventos se confirman en la misma transacción que la operación de negocio.
- Se auditan también lecturas sensibles, fotos y descargas protegidas.
- Triggers de PostgreSQL impiden `UPDATE`, `DELETE` y `TRUNCATE`.
- Las referencias protegidas evitan borrar actores o empleados que romperían la
  trazabilidad.
- Solo Admin consulta la bitácora transversal.

### Frontend

- Capacidades entregadas por el backend controlan navegación y acciones visibles.
- RRHH conserva Dashboard, Alertas, Reportes y Configuración; no accede a Bitácora.
- Supervisor ve únicamente su equipo actual y módulos operativos permitidos.
- Empleado entra directamente a su ficha, ve solo su legajo/novedades y no recibe un
  Dashboard que terminaría en 403.
- Servicio no puede iniciar una sesión humana.
- Se corrigió el render cuando Supervisor no tiene empleados ni novedades asignadas.
- Las guardas de build cortan si reaparecen API `localhost`, JWT, DOM inseguro,
  asociaciones por nombre, acciones incompatibles o menús fuera de capacidad.
- El artefacto productivo usa React local, assets con hash y CSP sin JavaScript inline,
  CDN, `eval` ni `new Function`.
- `frontend/design/` quedó sin modificaciones; el cableado se resolvió en `build.py` e
  integración, respetando el desarrollo separado del punto 10.

### Producción e infraestructura

- Flujo público: Nginx Proxy Manager → gateway web → API privada → PostgreSQL privado.
- API y base no publican puertos.
- Contenedores no root, capacidades reducidas, límites de procesos y filesystems de
  solo lectura donde corresponde.
- Secretos montados como archivos; no quedan incluidos en imágenes ni variables con
  credenciales completas.
- Rol PostgreSQL owner/migraciones separado del rol runtime de la API.
- El runtime no puede crear objetos, truncar la bitácora ni deshabilitar sus triggers.
- Volúmenes de PostgreSQL y archivos son externos y deben preexistir.
- Healthchecks distinguen gateway y readiness de API+base.
- Dependencias directas y transitivas quedan fijadas en locks con hashes.
- CI valida lint, migraciones, pruebas, OpenAPI, producción, permisos de base, frontend,
  imágenes y aislamiento de redes.

## 3. Validación realizada

| Gate | Resultado |
|---|---|
| Ruff | Verde |
| `makemigrations --check --dry-run` | Sin cambios |
| Suite backend con PostgreSQL | **388 passed** |
| OpenAPI `--validate --fail-on-warn` | Verde |
| `manage.py check --deploy --fail-level WARNING` | Verde |
| `pip check` | Sin dependencias rotas |
| Lock completo de desarrollo + producción con `pip-audit --strict` | Sin vulnerabilidades conocidas |
| Invariantes y guardas frontend | Verdes |
| Build frontend productivo | Verde |
| Migraciones desde base vacía | Verdes hasta la última migración |
| Rol PostgreSQL runtime vs. owner | Separación comprobada |
| Contratos de imágenes | `IMAGE_CONTRACTS=PASS` |
| Topología Compose | `PRODUCTION_STACK_PROOF=PASS` |
| Configuración Nginx interna | Sintaxis válida |

Las imágenes locales finales verificadas fueron:

- API: `sha256:42132b7d54de...`, usuario `app` (`10001:10001`);
- web: `sha256:1a13d459b75e...`, usuario `101`;
- PostgreSQL: `sha256:5e3793cf555f...`.

No son referencias de despliegue todavía: antes de la VPS deben publicarse o etiquetarse
de forma inmutable y registrarse sus digests definitivos.

### E2E real por rol

Se levantó un stack descartable con una copia local, gateway web y API real:

- Admin: login, Dashboard, empleados y Bitácora cargaron correctamente.
- RRHH: Dashboard, Alertas, Reportes y Configuración visibles; Bitácora ausente.
- Supervisor sin empleados: estados vacíos válidos, cero errores de render; Reportes,
  Configuración y Bitácora ausentes.
- Empleado: ingreso directo a su ficha, un único legajo y sus novedades; sin módulos
  agregados ni acciones de escritura.
- Servicio: login humano rechazado.
- Logout y nueva sesión por otro rol no conservaron datos del usuario anterior.

## 4. Vulnerabilidades y riesgos residuales

La auditoría de dependencias Python, incluido el entorno de pruebas, no reporta
vulnerabilidades conocidas. Durante el cierre se actualizó `pytest` de 8.4.2 a 9.1.1
para eliminar `PYSEC-2026-1845`.

Docker Scout informó:

| Imagen | Critical | High | Observación |
|---|---:|---:|---|
| web | 0 | 0 | Sin paquetes vulnerables detectados |
| PostgreSQL | 0 | 0 | Sin paquetes vulnerables detectados |
| API | 0 | 2 | `sqlite 3.51.2-r0`: CVE-2026-11824 y CVE-2026-11822 |

Los dos CVE de la API no tienen versión corregida disponible en Alpine al cierre. La
aplicación usa exclusivamente PostgreSQL, no importa `sqlite3` ni procesa bases SQLite,
por lo que no existe un flujo funcional conocido que alcance esas fallas. Aun así, no se
declaran “resueltas”: son un riesgo residual pendiente de aceptación y seguimiento.
Antes de desplegar se debe volver a consultar una actualización de la imagen base.

Otros límites conscientes:

- no hay antivirus de contenido; sí validación estructural y de firma;
- filesystem es adecuado para una única VPS; S3/R2 queda para otra escala;
- el cache de throttle soporta una réplica de API; para varias se requiere Redis;
- no existe todavía historia temporal de asignaciones de Supervisor, por eso sus
  reportes históricos están bloqueados;
- backup no está validado hasta completar un restore real.

## 5. Bloqueos de los datos existentes

El ensayo sobre una copia de la base se detuvo correctamente y no alteró la base
principal. RRHH debe resolver, por ID:

- relaciones activas sin puesto: `1`, `23`, `24`, `25`, `27`, `28`;
- empleado `15` con solapamientos entre relaciones `17/23`, `23/18`, `23/19`;
- identificadores inválidos:
  - empleado `11`: CUIL;
  - empleado `15`: CUIL;
  - empleado `16`: CUIL;
  - empleado `17`: DNI y CUIL;
  - empleado `18`: DNI.

No se encontraron colisiones posteriores a la normalización. No corresponde inventar
puestos, fechas ni identificadores: la corrección requiere fuente documental y decisión
de RRHH.

## 6. Checklist obligatorio antes de la VPS

1. RRHH corrige los IDs anteriores con respaldo documental.
2. Se obtiene un dump nuevo de PostgreSQL y una copia consistente del volumen de
   archivos.
3. Se restaura ambos en un entorno aislado.
4. Se repiten preflight, migraciones, 388 pruebas y smoke test por roles.
5. Se define el host de Nginx Proxy Manager y se crea/conecta la red externa.
6. Se crean volúmenes externos con sus nombres definitivos.
7. Se generan secretos distintos para Django, owner de base y runtime.
8. Se verifican UID/GID del volumen de archivos y límites CPU/RAM de la VPS.
9. Se publican imágenes inmutables y se registran sus digests.
10. Se prueba backup y restore, no solo creación de backup.
11. Se autoriza explícitamente la ventana de despliegue.
12. Después de migrar: `/gateway-healthz`, `/healthz`, login, CSRF, scopes, auditoría y
    descarga protegida deben pasar antes de habilitar tráfico.

## 7. Diferido deliberadamente

- autenticación M2M y scopes del rol Servicio para n8n u otros consumidores;
- importación Excel, hasta confirmar si existe una fuente real;
- n8n/WhatsApp y otras integraciones;
- biometría, asistencias y horas automáticas;
- antivirus y almacenamiento de objetos;
- historial temporal de supervisores;
- paginación server-side del frontend al superar el volumen esperado;
- punto 10, que continúa en su desarrollo separado.

La referencia normativa completa sigue siendo
[`ARQUITECTURA_MVP1_PRODUCCION.md`](ARQUITECTURA_MVP1_PRODUCCION.md).
