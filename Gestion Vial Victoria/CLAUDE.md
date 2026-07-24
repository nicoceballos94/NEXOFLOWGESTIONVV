# Gestión Vial Victoria — reglas del repo

## Estructura

- `gestion_rrhh/` — backend Django (API). Se verifica siempre contra **Postgres**
  vía `docker compose up` (nunca SQLite).
- `frontend/` — frontend Ceibo RRHH. Ver `frontend/README.md` para la arquitectura.
- `Conocimiento/` — specs y documentos de diseño funcional.

## Fuente de verdad

- **El repo Git es la única fuente de verdad del producto** (código, cableado,
  documentación).
- Para decisiones de dominio, seguridad y despliegue del MVP1, leer primero
  `Conocimiento/ARQUITECTURA_MVP1_PRODUCCION.md`. Es la referencia canónica actual.
  El estado de remediación, las pruebas ejecutadas, los riesgos residuales y los
  bloqueos previos a la VPS están en
  `Conocimiento/INFORME_CIERRE_MVP1_PRODUCCION.md`.
  Los documentos que todavía describan JWT, tokens en `sessionStorage`, puestos sin
  sector, documentos globales por empleado o importación Excel obligatoria son
  históricos y no autorizan reintroducir esas decisiones.
- Para la **UI**, el canvas de Claude Design ("Ceibo RRHH") es la fuente del
  *diseño visual*, y su export vive en `frontend/design/`. Pero el diseño **no es
  la app**: la app real es `dist/`, generada por `frontend/build.py`, que inyecta
  el cableado al backend definido en `frontend/integration/ceibo-api.js`.
- Si hay conflicto entre lo que dice Claude Design y lo que hay en el repo,
  **gana el repo**, salvo indicación explícita del usuario.

## Sincronización bidireccional con el canvas (regla)

El canvas y el repo se mantienen en sincronía en las **dos direcciones**, usando
la tool **DesignSync** (projectId y detalles en `frontend/docs/design-change-intake.md`):

- **Claude Code interviene en lo visual → actualiza el canvas.** Si Claude Code
  hace un cambio **visual** (markup/diseño), además de aplicarlo en el repo debe
  **subirlo al canvas** de Claude Design (`DesignSync write_files`), para que el
  canvas siga siendo la fuente del diseño visual. **Solo lo visual**: el cableado
  (`ceibo-api.js`, shims de `build.py`) **nunca** se sube al canvas.
- **El usuario avisa que cambió el canvas → Claude Code lo descarga.** Cuando el
  usuario dice que tocó algo en Claude Design, Claude Code **baja** el canvas
  actualizado (`DesignSync get_file`) y corre el intake (inbox → diff → promover →
  `build.py`).

## Reglas obligatorias para cambios visuales (Design Change Intake)

El proceso completo está en `frontend/docs/design-change-intake.md`. Resumen:

1. **Nunca editar a mano** los archivos de `frontend/design/` (`*.dc.html`,
   `support.js`). Son el export pristino de Claude Design.
2. **Nunca pisar con un export** los archivos vivos del repo: `frontend/build.py`,
   `frontend/integration/ceibo-api.js`, ni nada de `gestion_rrhh/`. Los ajustes
   hechos por Claude Code viven ahí y deben preservarse siempre.
3. Todo export nuevo de Claude Design entra **primero** por
   `frontend/design-inbox/AAAA-MM-DD-nombre-del-cambio/`. Los archivos del inbox
   son referencia visual, no código de producción.
4. Antes de promover un export a `frontend/design/`, comparar (diff) contra el
   diseño actual y **explicar qué se va a cambiar**.
5. Después de promover, correr `python frontend/build.py`. Si corta con
   "ancla no encontrada", ajustar el anclaje en `build.py` conscientemente,
   explicando el cambio; nunca silenciar el error.
6. Antes de commitear/publicar, mostrar diff o resumen de archivos modificados.
7. Si un cambio visual requiere eliminar código existente (anclas, shims,
   lógica de integración), pedir confirmación o explicarlo claramente antes.
8. **No hacer deploy sin confirmación explícita** (hoy no hay deploy; la regla
   aplica cuando exista).

## Backend

- Verificar siempre contra Postgres: `cd gestion_rrhh && docker compose up`.
- El front local se sirve desde `frontend/dist/` (ver `frontend/README.md`).

### Invariantes vigentes del MVP1

- Una persona tiene como máximo una relación laboral activa en todo el grupo y sus
  vigencias históricas no se superponen.
- Una relación activa exige empresa, sector y un puesto perteneciente a ese sector.
- El equipo de un Supervisor se asigna explícitamente en la relación; no se infiere por
  empresa o sector.
- El listado de empleados es deliberadamente resumido y no contiene PII. Para una ficha
  se usa el detalle auditado; para decidir alta/reingreso, Admin/RRHH usa la consulta
  exacta y auditada `/empleados/por-dni/`. No volver a exponer DNI/CUIL en el listado.
- Documentos y procesos de onboarding pertenecen a una relación laboral. Un reingreso
  vuelve a pedirlos.
- Plantillas de onboarding: empresa + sector + tipo, versionadas y publicadas
  explícitamente.
- Browser auth: sesión Django con cookie HttpOnly + CSRF. No JWT en JavaScript.
- Servicio es exclusivo y no admite login humano. La autenticación M2M y la importación
  Excel están diferidas.
- Los roles humanos combinados suman solo sus scopes seguros: Supervisor+Empleado ve lo
  propio y su equipo, pero los archivos documentales/médicos siguen siendo propios.
- La asignación vigente permite editar sector, puesto, jornada, contrato y vencimiento.
  Empresa, ingreso, baja y supervisor usan flujos propios. No cambiar de sector después
  de iniciar onboarding/offboarding; sí se puede promover dentro del mismo sector.
- Las fechas personales, contractuales y de seguimiento de novedades deben ser
  cronológicamente coherentes. Los reportes usan la vigencia efectiva de prórrogas
  aprobadas/cerradas.
- Los reportes históricos son solo Admin/RRHH. No atribuir historia a un Supervisor hasta
  que exista historial de asignaciones.
- La auditoría es append-only y las lecturas sensibles también se registran.
- Producción: Nginx Proxy Manager → gateway web; API y PostgreSQL privados.
- La API de producción usa un rol PostgreSQL runtime no propietario. Las migraciones
  usan el servicio operativo y una credencial distinta; nunca montar el secreto
  propietario dentro del contenedor API.
- No desplegar ni tocar la VPS sin confirmación explícita, backup verificado y gates en
  verde.

### Bloqueos de datos conocidos para la primera migración

- Relaciones activas sin puesto: IDs `1, 23, 24, 25, 27, 28`.
- Solapamientos del empleado `15`: relaciones `17/23`, `23/18`, `23/19`.
- Identificadores inválidos: empleados `11`, `15`, `16`, `17`, `18`; consultar
  `Conocimiento/ARQUITECTURA_MVP1_PRODUCCION.md` para saber qué campo falla.
- No inventar valores ni automatizar esas correcciones. RRHH debe resolverlas y luego se
  repite el preflight sobre una copia fresca del dump de la VPS.
