# Runbook de producción — VPS + Docker + Nginx Proxy Manager

Este procedimiento supone una VPS Linux donde Nginx Proxy Manager (NPM) ya funciona en
Docker y su red compartida se llama `reverse-proxy`. Ningún paso debe ejecutarse sin un
backup verificable. Los ejemplos usan `/opt/nexoflow/rrhh` como directorio de despliegue.

## 1. Topología y prerequisitos

```text
Internet/TLS
    |
Nginx Proxy Manager
    |  red externa reverse-proxy
rrhh-web:8080
    |  red interna rrhh-app
api:8000
    |  red interna rrhh-db, rol rrhh_runtime
PostgreSQL:5432
    ^
jobs db-provision / migrate / db-permissions-check
    |  red interna rrhh-db, owner solo durante operación
```

- Docker Engine y `docker compose` actualizados.
- Un escáner de imágenes (los ejemplos usan Docker Scout).
- DNS del dominio apuntando a la VPS.
- NPM y `rrhh-web` conectados a la misma red Docker externa.
- Al menos espacio libre equivalente a dos veces el tamaño de la base y de `media`.
- Imágenes identificadas por digest para cada release. No reutilizar `latest`.

Hay dos identidades de base obligatoriamente distintas:

- `POSTGRES_ADMIN_USER`: owner existente de la base. Solo se monta en PostgreSQL y jobs
  operativos; nunca en Gunicorn.
- `POSTGRES_APP_USER`: login runtime de la API, sin ownership, `SUPERUSER`, `CREATEDB`,
  `CREATEROLE`, `REPLICATION`, `BYPASSRLS` ni membresías heredables.

La base se considera dedicada a este sistema. `db-provision` retira a `PUBLIC` conexión,
temporales, acceso al esquema y ejecución de funciones, y concede solo lo explícito. Si
existiera hoy otro consumidor, inventariarlo antes y otorgarle un rol propio; no volver a
abrir `PUBLIC`. El futuro rol servicio para n8n/API debe incorporarse con permisos
específicos en otra release.

Comprobar o crear la red una sola vez:

```bash
docker network inspect reverse-proxy >/dev/null 2>&1 \
  || docker network create reverse-proxy
```

## 2. Secretos y variables

Para una instalación nueva, crear los tres secretos fuera del repositorio:

```bash
sudo install -d -m 0700 /opt/nexoflow/secrets
openssl rand -base64 64 | tr -d '\n' \
  | sudo tee /opt/nexoflow/secrets/rrhh_django_secret_key >/dev/null
openssl rand -base64 48 | tr -d '\n' \
  | sudo tee /opt/nexoflow/secrets/rrhh_postgres_admin_password >/dev/null
openssl rand -base64 48 | tr -d '\n' \
  | sudo tee /opt/nexoflow/secrets/rrhh_postgres_app_password >/dev/null
sudo chmod 0444 /opt/nexoflow/secrets/rrhh_*
```

En una base existente **no ejecutar la generación de la contraseña admin del bloque
anterior**. Copiar por un canal seguro su valor actual a
`rrhh_postgres_admin_password` y generar únicamente los secretos Django/app. Cambiar el
archivo sin ejecutar también un cambio coordinado de contraseña en PostgreSQL bloquea el
acceso del owner.

El directorio padre `0700 root` es la barrera en el host. Los archivos son `0444` porque
Compose no-Swarm los monta como archivos y los contenedores API/migrate corren con UID
no-root; solo el servicio que declara cada secreto puede verlo dentro de su namespace.
No relajar el permiso del directorio ni montar el secreto admin en `api`.

Copiar `.env.prod.example` como `.env.prod`, dejarlo fuera de Git y completar:

- `RRHH_IMAGE`, `RRHH_WEB_IMAGE` y `RRHH_POSTGRES_IMAGE`: tag único o,
  preferentemente, referencia `registro/imagen@sha256:...`.
- `ALLOWED_HOSTS`: dominio público exacto, sin esquema.
- `CSRF_TRUSTED_ORIGINS`: el mismo dominio con `https://`.
- `PROXY_NETWORK=reverse-proxy`.
- `POSTGRES_ADMIN_USER`: en una base existente, el owner actual exacto.
- `POSTGRES_APP_USER`: un nombre nuevo que no sea owner de ningún objeto.
- `RRHH_POSTGRES_VOLUME` y `RRHH_MEDIA_VOLUME`: nombres Docker explícitos de los
  volúmenes persistentes.
- rutas absolutas de los tres secretos.

En una base existente no cambiar el nombre ni la contraseña del owner por suposición. El
archivo `RRHH_DB_ADMIN_PASSWORD_FILE` debe contener su contraseña actual. Si hoy el owner
se llama `rrhh_app`, conservar ese nombre como `POSTGRES_ADMIN_USER` y crear otro, por
ejemplo `rrhh_runtime`, como `POSTGRES_APP_USER`.

Los volúmenes son externos y Compose nunca los crea implícitamente ni los elimina con
`down -v`. Esto evita que un cambio de directorio o project name arranque por accidente
con una base vacía. En una instalación nueva, crear exactamente los nombres elegidos:

```bash
docker volume create rrhh-prod-postgres
docker volume create rrhh-prod-media
```

En una instalación existente, obtener primero los nombres reales de los contenedores
actuales y copiarlos sin reinterpretar a `.env.prod`:

```bash
CONTENEDOR_DB_ACTUAL=REEMPLAZAR
CONTENEDOR_API_ACTUAL=REEMPLAZAR
test "$CONTENEDOR_DB_ACTUAL" != REEMPLAZAR
test "$CONTENEDOR_API_ACTUAL" != REEMPLAZAR
docker inspect "$CONTENEDOR_DB_ACTUAL" \
  --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Type}} {{.Name}} {{.Source}}{{end}}{{end}}'
docker inspect "$CONTENEDOR_API_ACTUAL" \
  --format '{{range .Mounts}}{{if eq .Destination "/app/media"}}{{.Type}} {{.Name}} {{.Source}}{{end}}{{end}}'
```

Si el tipo informado es `bind`, no declararlo como volumen externo: restaurar el backup
en un volumen nombrado nuevo y ensayar el cutover. Antes de seguir, ambos nombres deben
existir y el volumen de media debe ser escribible por el UID/GID fijo `10001:10001` de la
API:

```bash
set -a
. ./.env.prod
set +a
test -n "$RRHH_POSTGRES_VOLUME"
test -n "$RRHH_MEDIA_VOLUME"
test -n "$RRHH_IMAGE"
docker volume inspect "$RRHH_POSTGRES_VOLUME" >/dev/null
docker volume inspect "$RRHH_MEDIA_VOLUME" >/dev/null
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges=true --user 10001:10001 \
  -v "$RRHH_MEDIA_VOLUME:/mnt/media" \
  --entrypoint sh "$RRHH_IMAGE" \
  -c 'test -r /mnt/media && test -w /mnt/media'
```

Si este último control falla en un volumen preexistente, conservar el backup y corregir
su ownership en una tarea de mantenimiento acotada al volumen ya inspeccionado antes de
iniciar la API. No hacer un `chown -R` sobre una ruta o variable sin resolver.

Validar permisos y que ningún secreto entró al environment:

```bash
stat -c '%a %U:%G %n' /opt/nexoflow/secrets
stat -c '%a %n' /opt/nexoflow/secrets/rrhh_*
if docker compose --env-file .env.prod -f docker-compose.prod.yml config \
  | grep -Eq '(^|[[:space:]])(SECRET_KEY|POSTGRES_PASSWORD):'; then
  echo "ERROR: un secreto quedó expandido en el environment" >&2
  exit 1
fi
```

El cache de throttling vive en el tmpfs del contenedor API y se comparte entre sus
workers. Esta configuración admite una sola réplica de `api`; antes de escalar
horizontalmente hay que mover `CACHES` a Redis compartido.

## 3. Configurar Nginx Proxy Manager

Crear un Proxy Host:

- Scheme: `http`
- Forward Hostname/IP: `rrhh-web`
- Forward Port: `8080`
- Websockets: desactivado (el MVP1 no los usa)
- Block Common Exploits: activado
- certificado válido, Force SSL y HTTP/2: activados
- Advanced:

  ```nginx
  client_max_body_size 12m;
  access_log off;
  ```

  El primer proxy respeta así el mismo límite que la aplicación y no guarda query strings
  con posibles DNI. El gateway conserva un access log operativo sin argumentos sensibles.

No publicar los puertos 8080, 8000 ni 5432 en la VPS. NPM debe reemplazar
`X-Real-IP` y `X-Forwarded-Proto`; es el comportamiento de su configuración estándar.
No agregar reglas que sirvan `/media/`.

El gateway ya emite HSTS por 30 días. No habilitar `preload` ni ampliar ese plazo sin
verificar antes todos los subdominios alcanzados y acordar un plan de reversión.

Comprobar que NPM aparece conectado a la red antes del primer deploy:

```bash
docker network inspect reverse-proxy \
  --format '{{range .Containers}}{{println .Name}}{{end}}'
```

## 4. Preflight de una release

Desde el commit exacto a desplegar, validar primero el Compose:

```bash
cd /opt/nexoflow/rrhh/gestion_rrhh
docker compose --env-file .env.prod --profile ops \
  -f docker-compose.prod.yml config --quiet
```

Si las imágenes se construyen en la VPS, usar tags únicos de release (no `latest`) y
construir:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml build --pull
```

Si se consumen imágenes de un registro, usar referencias por digest y descargarlas; no
ejecutar `build` en este caso:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml pull
```

Con las imágenes disponibles, ejecutar los controles:

```bash
set -a
. ./.env.prod
set +a
for imagen in "$RRHH_IMAGE" "$RRHH_WEB_IMAGE" "$RRHH_POSTGRES_IMAGE"; do
  # Críticas siempre bloquean; altas corregibles también. El último comando deja
  # visibles las altas todavía no corregidas para la evaluación documentada.
  docker scout cves --exit-code --only-severity critical "$imagen"
  docker scout cves --exit-code --only-severity high --only-fixed "$imagen"
  docker scout cves --only-severity high "$imagen"
done

docker compose --env-file .env.prod -f docker-compose.prod.yml \
  run --rm --no-deps api python manage.py check --deploy --fail-level WARNING
```

No liberar con vulnerabilidades críticas. Una vulnerabilidad alta solo puede quedar
temporalmente si no tiene versión corregida, el componente no es alcanzable en esta
arquitectura y queda registrada con fecha de revisión. En el escaneo del 24/07/2026,
`web` y la imagen PostgreSQL endurecida quedaron en `0C/0H`; la API quedó en `0C/2H`,
`CVE-2026-11822` y `CVE-2026-11824`, ambas en SQLite `3.51.2-r0` y sin fix del proveedor.
La aplicación es PostgreSQL-only y no abre bases SQLite, pero esta excepción vence en la
siguiente release: volver a escanear y actualizar la imagen base apenas exista un paquete
corregido.

`--no-deps` es intencional: este check no debe provisionar roles ni tocar la base antes
del backup. El plan y la ejecución de migraciones se prueban después sobre el clon, usando
el job `migrate`; nunca ejecutar `manage.py migrate` mediante el servicio `api`.

## 5. Backup previo

La ventana de mantenimiento empieza antes del backup: detener primero las entradas de
usuario para que PostgreSQL y `media` formen una pareja consistente. En el primer
cutover, detener los servicios equivalentes del Compose actual.

En el primer cutover desde otro Compose, detener su web/API y hacer este backup mediante
los servicios que están ejecutándose actualmente, dejando solo PostgreSQL activo. No
iniciar a la vez dos contenedores PostgreSQL sobre el mismo volumen. Los comandos
siguientes aplican cuando `docker-compose.prod.yml` ya controla el volumen elegido.

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml stop web api

umask 077
BACKUP_DIR="/opt/nexoflow/backups/rrhh/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP_DIR"

docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "$BACKUP_DIR/database.dump"

docker compose --env-file .env.prod -f docker-compose.prod.yml \
  run --rm --no-deps -T api \
  tar -C /app/media -czf - . > "$BACKUP_DIR/media.tar.gz"

sha256sum "$BACKUP_DIR/database.dump" "$BACKUP_DIR/media.tar.gz" \
  > "$BACKUP_DIR/SHA256SUMS"
test -s "$BACKUP_DIR/database.dump"
test -s "$BACKUP_DIR/media.tar.gz"
sha256sum -c "$BACKUP_DIR/SHA256SUMS"
docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T db \
  pg_restore --list < "$BACKUP_DIR/database.dump" >/dev/null
tar -tzf "$BACKUP_DIR/media.tar.gz" >/dev/null
git rev-parse HEAD > "$BACKUP_DIR/commit.txt"
docker compose --env-file .env.prod -f docker-compose.prod.yml config --images \
  > "$BACKUP_DIR/images.txt"
docker compose --env-file .env.prod -f docker-compose.prod.yml images --format json \
  > "$BACKUP_DIR/running-images.json"
```

Una copia en la misma VPS no protege ante pérdida del host. Replicarla cifrada a otro
destino y probar periódicamente la restauración en un entorno aislado.

## 6. Ensayo obligatorio sobre un clon

Nunca ejecutar una migración de release por primera vez contra producción. Restaurar el
dump recién creado en un PostgreSQL aislado, sin puertos publicados ni volúmenes
compartidos con producción, y ejecutar allí la imagen exacta que se quiere liberar.

Ejemplo con recursos Docker descartables y nombres acotados:

```bash
PREFLIGHT_ID="rrhh-preflight-$(date -u +%Y%m%dT%H%M%SZ)"
PREFLIGHT_DB="${PREFLIGHT_ID}-db"
PREFLIGHT_VOLUME="${PREFLIGHT_ID}-data"
PREFLIGHT_IMAGE="<copiar exactamente RRHH_IMAGE de .env.prod>"
PREFLIGHT_POSTGRES_IMAGE="<copiar exactamente RRHH_POSTGRES_IMAGE de .env.prod>"
PREFLIGHT_ADMIN_SECRET="$BACKUP_DIR/preflight-admin.secret"
PREFLIGHT_APP_SECRET="$BACKUP_DIR/preflight-app.secret"

test "$PREFLIGHT_IMAGE" != "<copiar exactamente RRHH_IMAGE de .env.prod>"
test "$PREFLIGHT_POSTGRES_IMAGE" != "<copiar exactamente RRHH_POSTGRES_IMAGE de .env.prod>"
docker image inspect "$PREFLIGHT_IMAGE" >/dev/null
docker image inspect "$PREFLIGHT_POSTGRES_IMAGE" >/dev/null
printf '%s' 'preflight-admin-disposable' > "$PREFLIGHT_ADMIN_SECRET"
printf '%s' 'preflight-app-disposable' > "$PREFLIGHT_APP_SECRET"
chmod 0444 "$PREFLIGHT_ADMIN_SECRET" "$PREFLIGHT_APP_SECRET"

docker network create "$PREFLIGHT_ID"
docker volume create "$PREFLIGHT_VOLUME"
docker run -d --name "$PREFLIGHT_DB" \
  --network "$PREFLIGHT_ID" \
  -e POSTGRES_DB=rrhh \
  -e POSTGRES_USER=preflight \
  -e POSTGRES_PASSWORD_FILE=/run/secrets/postgres_admin_password \
  -v "$PREFLIGHT_VOLUME:/var/lib/postgresql/data" \
  -v "$PREFLIGHT_ADMIN_SECRET:/run/secrets/postgres_admin_password:ro" \
  "$PREFLIGHT_POSTGRES_IMAGE"

for intento in $(seq 1 60); do
  docker exec "$PREFLIGHT_DB" pg_isready -U preflight -d rrhh && break
  sleep 1
done
docker exec "$PREFLIGHT_DB" pg_isready -U preflight -d rrhh
docker exec -i "$PREFLIGHT_DB" pg_restore \
  -U preflight -d rrhh --no-owner --no-privileges \
  --single-transaction --exit-on-error \
  < "$BACKUP_DIR/database.dump"

docker run --rm --user 70:70 --network "$PREFLIGHT_ID" \
  --read-only --tmpfs /tmp:size=16m,mode=1777 --cap-drop ALL \
  -e POSTGRES_HOST="$PREFLIGHT_DB" \
  -e POSTGRES_PORT=5432 \
  -e POSTGRES_DB=rrhh \
  -e POSTGRES_ADMIN_USER=preflight \
  -e POSTGRES_APP_USER=preflight_runtime \
  -v "$PREFLIGHT_ADMIN_SECRET:/run/secrets/postgres_admin_password:ro" \
  -v "$PREFLIGHT_APP_SECRET:/run/secrets/postgres_app_password:ro" \
  -v "$PWD/deploy/db/provision-app-role.sh:/opt/rrhh/provision-app-role.sh:ro" \
  "$PREFLIGHT_POSTGRES_IMAGE" \
  /bin/sh /opt/rrhh/provision-app-role.sh

docker run --rm --network "$PREFLIGHT_ID" \
  --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL \
  -e DJANGO_SETTINGS_MODULE=config.settings.prod \
  -e SECRET_KEY=preflight-only-not-production \
  -e ALLOWED_HOSTS=localhost \
  -e POSTGRES_HOST="$PREFLIGHT_DB" \
  -e POSTGRES_PORT=5432 \
  -e POSTGRES_DB=rrhh \
  -e POSTGRES_USER=preflight \
  -e POSTGRES_PASSWORD_FILE=/run/secrets/postgres_admin_password \
  -v "$PREFLIGHT_ADMIN_SECRET:/run/secrets/postgres_admin_password:ro" \
  "$PREFLIGHT_IMAGE" python manage.py migrate --plan

docker run --rm --network "$PREFLIGHT_ID" \
  --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL \
  -e DJANGO_SETTINGS_MODULE=config.settings.prod \
  -e SECRET_KEY=preflight-only-not-production \
  -e ALLOWED_HOSTS=localhost \
  -e POSTGRES_HOST="$PREFLIGHT_DB" \
  -e POSTGRES_PORT=5432 \
  -e POSTGRES_DB=rrhh \
  -e POSTGRES_USER=preflight \
  -e POSTGRES_PASSWORD_FILE=/run/secrets/postgres_admin_password \
  -v "$PREFLIGHT_ADMIN_SECRET:/run/secrets/postgres_admin_password:ro" \
  "$PREFLIGHT_IMAGE" python manage.py migrate --noinput

# Reaplicar grants para tablas recién creadas y verificar tanto permisos positivos como
# intentos negativos de ALTER/DISABLE/TRUNCATE.
docker run --rm --user 70:70 --network "$PREFLIGHT_ID" \
  --read-only --tmpfs /tmp:size=16m,mode=1777 --cap-drop ALL \
  -e POSTGRES_HOST="$PREFLIGHT_DB" \
  -e POSTGRES_PORT=5432 \
  -e POSTGRES_DB=rrhh \
  -e POSTGRES_ADMIN_USER=preflight \
  -e POSTGRES_APP_USER=preflight_runtime \
  -v "$PREFLIGHT_ADMIN_SECRET:/run/secrets/postgres_admin_password:ro" \
  -v "$PREFLIGHT_APP_SECRET:/run/secrets/postgres_app_password:ro" \
  -v "$PWD/deploy/db/provision-app-role.sh:/opt/rrhh/provision-app-role.sh:ro" \
  "$PREFLIGHT_POSTGRES_IMAGE" \
  /bin/sh /opt/rrhh/provision-app-role.sh

docker run --rm --user 70:70 --network "$PREFLIGHT_ID" \
  --read-only --tmpfs /tmp:size=16m,mode=1777 --cap-drop ALL \
  -e POSTGRES_HOST="$PREFLIGHT_DB" \
  -e POSTGRES_PORT=5432 \
  -e POSTGRES_DB=rrhh \
  -e POSTGRES_ADMIN_USER=preflight \
  -e POSTGRES_APP_USER=preflight_runtime \
  -v "$PREFLIGHT_ADMIN_SECRET:/run/secrets/postgres_admin_password:ro" \
  -v "$PREFLIGHT_APP_SECRET:/run/secrets/postgres_app_password:ro" \
  -v "$PWD/deploy/db/verify-app-role.sh:/opt/rrhh/verify-app-role.sh:ro" \
  "$PREFLIGHT_POSTGRES_IMAGE" \
  /bin/sh /opt/rrhh/verify-app-role.sh
```

El ensayo es válido solo si parte de un dump nuevo del destino real y termina sin
advertencias ni correcciones manuales dentro del clon. Después se validan conteos e
invariantes de negocio. Para limpiar, verificar que las tres variables conservan el
prefijo `rrhh-preflight-` y eliminar únicamente esos recursos descartables:

```bash
case "$PREFLIGHT_ID" in
  rrhh-preflight-*) ;;
  *) echo "Identificador de preflight inválido" >&2; exit 1 ;;
esac
docker rm -f "$PREFLIGHT_DB"
docker volume rm "$PREFLIGHT_VOLUME"
docker network rm "$PREFLIGHT_ID"
rm -f "$PREFLIGHT_ADMIN_SECRET" "$PREFLIGHT_APP_SECRET"
```

Si la migración informa relaciones sin puesto, vigencias solapadas u otra ambigüedad:

1. no desactivar restricciones ni editar la migración para forzar el paso;
2. presentar los registros a RRHH y obtener la decisión de negocio;
3. aplicar una corrección de datos aprobada, trazable y respaldada;
4. tomar un dump nuevo y repetir todo el ensayo hasta que quede verde.

### Bloqueo conocido del ensayo del 24/07/2026

El ensayo realizado sobre el clon exacto de la base local aplicó correctamente
Organización `0005/0006`, pero Empleados `0005` se detuvo por:

- relaciones activas sin puesto: IDs `1, 23, 24, 25, 27, 28`;
- vigencias solapadas del empleado `15`: pares de relaciones `17/23`, `23/18` y
  `23/19`.

Estos IDs pertenecen al clon local y deben reconfirmarse contra un dump fresco de la VPS.
No indican qué puesto ni qué vigencia elegir. Hasta que RRHH resuelva esos datos y un
nuevo ensayo termine verde, **no ejecutar `migrate` en producción**.

## 7. Migrar y levantar

Reservar una ventana de mantenimiento. El MVP1 corre una sola réplica y no se supone que
el binario anterior sea compatible con un esquema parcialmente migrado:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml stop web api

# Crea/rota el login runtime y retira atributos, memberships y grants excesivos.
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  run --rm db-provision

# El único servicio Django que recibe el secreto owner es el job operativo migrate.
docker compose --env-file .env.prod --profile ops -f docker-compose.prod.yml \
  run --rm migrate python manage.py migrate --plan
docker compose --env-file .env.prod --profile ops -f docker-compose.prod.yml \
  run --rm migrate

# Aplicar default grants a objetos nuevos, revocar mutación de bitácora y probar límites.
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  run --rm db-provision
docker compose --env-file .env.prod --profile ops -f docker-compose.prod.yml \
  run --rm --no-deps db-permissions-check

docker compose --env-file .env.prod -f docker-compose.prod.yml up -d

docker compose --env-file .env.prod -f docker-compose.prod.yml ps
docker compose --env-file .env.prod -f docker-compose.prod.yml logs \
  --tail=100 api web db db-provision
```

La prueba de permisos debe terminar con:

```text
Permisos runtime verificados: CRUD/sesiones OK; owner/ALTER/TRUNCATE bloqueados.
```

Si falla, no iniciar `api`. No usar temporalmente el owner como `POSTGRES_APP_USER`.

No correr `seed_datos_prueba`, `seed_usuarios_demo` ni `seed_inicial` como parte
automática del deploy. Los catálogos son datos de negocio. En una instalación nueva,
crear solo los roles del sistema con `bootstrap_roles`, crear un superusuario y cargar
catálogos validados por los responsables:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  run --rm api python manage.py bootstrap_roles
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  run --rm api python manage.py createsuperuser
```

## 8. Smoke tests

Desde la VPS y luego desde otra red:

```bash
curl --fail --silent --show-error https://rrhh.example.com/healthz
curl --fail --silent --show-error https://rrhh.example.com/ \
  | grep -q '<!DOCTYPE html>'
curl --fail --silent --show-error \
  https://rrhh.example.com/api/v1/auth/csrf/ >/dev/null
```

Además:

1. iniciar y cerrar sesión con un usuario no privilegiado de prueba;
2. confirmar que una URL de API sin sesión devuelve 401;
3. comprobar que `/api/docs/` y `/api/schema/` no se publican;
4. cargar y descargar un archivo de prueba autorizado;
5. revisar que `docker compose ps` muestre los tres servicios sanos;
6. revisar logs por errores, redirecciones TLS repetidas o `DisallowedHost`.

## 9. Rollback

La aplicación puede volver a las dos imágenes anteriores cambiando sus referencias por
los digests conocidos en `.env.prod` y ejecutando `up -d`. No revertir migraciones a
ciegas: un binario anterior puede ser incompatible con el esquema nuevo.

Si la release requiere volver también los datos:

1. poner la aplicación fuera de servicio;
2. conservar un segundo backup del estado fallido;
3. restaurar `database.dump` y `media.tar.gz` como una pareja;
4. volver a los digests anteriores;
5. levantar y repetir todos los smoke tests.

Ejemplo de restauración destructiva, solo tras validar las rutas y con la app detenida:

```bash
docker compose --env-file .env.prod -f docker-compose.prod.yml stop api web
docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T db \
  sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    --clean --if-exists --single-transaction --exit-on-error \
    --no-owner --no-privileges' \
  < /ruta/validada/database.dump
docker compose --env-file .env.prod -f docker-compose.prod.yml \
  run --rm db-provision
docker compose --env-file .env.prod --profile ops -f docker-compose.prod.yml \
  run --rm --no-deps db-permissions-check
```

La restauración de `media` debe hacerse sobre el volumen correcto y con un procedimiento
ensayado; no usar comandos recursivos contra rutas o volúmenes sin resolverlos primero.

## 10. Operación continua

- Monitorear externamente `/healthz`; comprueba Django y una consulta mínima a
  PostgreSQL, no solo el gateway.
- Alertar por contenedores `unhealthy`, reinicios, uso de disco y expiración TLS.
- Respaldar PostgreSQL y `media` juntos, cifrar y aplicar retención.
- Renovar dependencias e imágenes base mediante una release probada, nunca directamente
  sobre producción.
- Revisar el crecimiento de logs; Compose rota cada stream en cinco archivos de 10 MiB.
- El access log omite query strings para no copiar DNI u otros filtros sensibles; no
  reemplazar su formato por `$request_uri`.
- Ejecutar `db-permissions-check` después de cada migración y alertar cualquier drift de
  ownership, atributos o membresías del rol runtime.
- Para rotar la contraseña app: actualizar solo su archivo, ejecutar `db-provision`,
  verificar permisos y reiniciar `api`. La contraseña owner requiere un procedimiento
  coordinado con `ALTER ROLE`; reemplazar solo el archivo provoca un lockout.
- No usar `docker compose down -v`: elimina los volúmenes persistentes.
