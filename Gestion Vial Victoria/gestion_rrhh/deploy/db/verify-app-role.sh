#!/bin/sh
set -eu

: "${POSTGRES_HOST:?Falta POSTGRES_HOST}"
: "${POSTGRES_PORT:?Falta POSTGRES_PORT}"
: "${POSTGRES_DB:?Falta POSTGRES_DB}"
: "${POSTGRES_ADMIN_USER:?Falta POSTGRES_ADMIN_USER}"
: "${POSTGRES_APP_USER:?Falta POSTGRES_APP_USER}"

for identificador in \
    "$POSTGRES_DB" \
    "$POSTGRES_ADMIN_USER" \
    "$POSTGRES_APP_USER"
do
    if ! printf '%s' "$identificador" | grep -Eq '^[a-z_][a-z0-9_]{0,62}$'; then
        echo "ERROR: identificador PostgreSQL inválido." >&2
        exit 2
    fi
done

ADMIN_SECRET=/run/secrets/postgres_admin_password
APP_SECRET=/run/secrets/postgres_app_password
admin_password="$(cat "$ADMIN_SECRET")"
app_password="$(cat "$APP_SECRET")"

psql_admin() {
    PGPASSWORD="$admin_password" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
        --host="$POSTGRES_HOST" --port="$POSTGRES_PORT" \
        --username="$POSTGRES_ADMIN_USER" --dbname="$POSTGRES_DB" "$@"
}

psql_app() {
    PGPASSWORD="$app_password" psql --no-psqlrc --set=ON_ERROR_STOP=1 \
        --host="$POSTGRES_HOST" --port="$POSTGRES_PORT" \
        --username="$POSTGRES_APP_USER" --dbname="$POSTGRES_DB" "$@"
}

atributos="$(psql_admin --tuples-only --no-align \
    --command="SELECT (
        rolcanlogin
        AND NOT rolsuper
        AND NOT rolcreatedb
        AND NOT rolcreaterole
        AND NOT rolreplication
        AND NOT rolbypassrls
        AND NOT rolinherit
    )::int
    FROM pg_roles
    WHERE rolname = '$POSTGRES_APP_USER';")"
[ "$atributos" = "1" ] || {
    echo "ERROR: el rol runtime conserva atributos privilegiados." >&2
    exit 5
}

membresias="$(psql_admin --tuples-only --no-align \
    --command="SELECT count(*)
    FROM pg_auth_members AS membresia
    JOIN pg_roles AS miembro ON miembro.oid = membresia.member
    WHERE miembro.rolname = '$POSTGRES_APP_USER';")"
[ "$membresias" = "0" ] || {
    echo "ERROR: el rol runtime hereda o puede asumir otro rol." >&2
    exit 5
}

owner_objetos="$(psql_admin --tuples-only --no-align \
    --command="SELECT count(*)
    FROM pg_class AS objeto
    JOIN pg_roles AS owner ON owner.oid = objeto.relowner
    WHERE owner.rolname = '$POSTGRES_APP_USER'
      AND objeto.relpersistence <> 't';")"
[ "$owner_objetos" = "0" ] || {
    echo "ERROR: el rol runtime es owner de objetos persistentes." >&2
    exit 5
}

owner_funciones="$(psql_admin --tuples-only --no-align \
    --command="SELECT count(*)
    FROM pg_proc AS funcion
    JOIN pg_roles AS owner ON owner.oid = funcion.proowner
    WHERE owner.rolname = '$POSTGRES_APP_USER';")"
[ "$owner_funciones" = "0" ] || {
    echo "ERROR: el rol runtime es owner de funciones." >&2
    exit 5
}

privilegios_auditoria="$(psql_admin --tuples-only --no-align \
    --command="SELECT (
        has_table_privilege('$POSTGRES_APP_USER', 'public.auditoria_registroauditoria', 'SELECT')
        AND has_table_privilege('$POSTGRES_APP_USER', 'public.auditoria_registroauditoria', 'INSERT')
        AND NOT has_table_privilege('$POSTGRES_APP_USER', 'public.auditoria_registroauditoria', 'UPDATE')
        AND NOT has_table_privilege('$POSTGRES_APP_USER', 'public.auditoria_registroauditoria', 'DELETE')
        AND NOT has_table_privilege('$POSTGRES_APP_USER', 'public.auditoria_registroauditoria', 'TRUNCATE')
        AND NOT has_table_privilege('$POSTGRES_APP_USER', 'public.auditoria_registroauditoria', 'TRIGGER')
    )::int;")"
[ "$privilegios_auditoria" = "1" ] || {
    echo "ERROR: privilegios incorrectos sobre la bitácora." >&2
    exit 5
}

tablas_sin_crud="$(psql_admin --tuples-only --no-align \
    --command="SELECT count(*)
    FROM pg_class AS tabla
    JOIN pg_namespace AS esquema ON esquema.oid = tabla.relnamespace
    WHERE esquema.nspname = 'public'
      AND tabla.relkind IN ('r', 'p')
      AND tabla.relname <> 'auditoria_registroauditoria'
      AND NOT (
          has_table_privilege('$POSTGRES_APP_USER', tabla.oid, 'SELECT')
          AND has_table_privilege('$POSTGRES_APP_USER', tabla.oid, 'INSERT')
          AND has_table_privilege('$POSTGRES_APP_USER', tabla.oid, 'UPDATE')
          AND has_table_privilege('$POSTGRES_APP_USER', tabla.oid, 'DELETE')
      );")"
[ "$tablas_sin_crud" = "0" ] || {
    echo "ERROR: el rol runtime no tiene CRUD en todas las tablas operativas." >&2
    exit 5
}

limites_base_esquema="$(psql_admin --tuples-only --no-align \
    --command="SELECT (
        has_database_privilege(
            '$POSTGRES_APP_USER',
            '$POSTGRES_DB',
            'CONNECT'
        )
        AND NOT has_database_privilege(
            '$POSTGRES_APP_USER',
            '$POSTGRES_DB',
            'TEMP'
        )
        AND has_schema_privilege(
            '$POSTGRES_APP_USER',
            'public',
            'USAGE'
        )
        AND NOT has_schema_privilege(
            '$POSTGRES_APP_USER',
            'public',
            'CREATE'
        )
    )::int;")"
[ "$limites_base_esquema" = "1" ] || {
    echo "ERROR: límites incorrectos de conexión, temporales o esquema public." >&2
    exit 5
}

# CRUD real que el motor revierte: prueba login, tablas y permisos de sesiones sin dejar
# datos persistentes.
psql_app >/dev/null <<'SQL'
BEGIN;
INSERT INTO django_session (session_key, session_data, expire_date)
VALUES (
    'rrhh_permission_probe_' || pg_backend_pid(),
    'probe',
    CURRENT_TIMESTAMP + INTERVAL '5 minutes'
);
UPDATE django_session
SET session_data = 'probe_updated'
WHERE session_key = 'rrhh_permission_probe_' || pg_backend_pid();
SELECT session_key
FROM django_session
WHERE session_key = 'rrhh_permission_probe_' || pg_backend_pid();
DELETE FROM django_session
WHERE session_key = 'rrhh_permission_probe_' || pg_backend_pid();
ROLLBACK;
SQL

esperar_denegado() {
    descripcion="$1"
    sql="$2"
    if psql_app --command="$sql" >/dev/null 2>&1; then
        echo "ERROR: el rol runtime pudo $descripcion." >&2
        exit 6
    fi
}

esperar_denegado \
    "alterar la bitácora" \
    "BEGIN; ALTER TABLE auditoria_registroauditoria SET (autovacuum_enabled = true); ROLLBACK;"
esperar_denegado \
    "deshabilitar triggers de auditoría" \
    "BEGIN; ALTER TABLE auditoria_registroauditoria DISABLE TRIGGER ALL; ROLLBACK;"
esperar_denegado \
    "truncar la bitácora" \
    "BEGIN; TRUNCATE TABLE auditoria_registroauditoria; ROLLBACK;"
esperar_denegado \
    "borrar la bitácora" \
    "BEGIN; DELETE FROM auditoria_registroauditoria; ROLLBACK;"
esperar_denegado \
    "actualizar la bitácora" \
    "BEGIN; UPDATE auditoria_registroauditoria SET entidad = entidad; ROLLBACK;"
esperar_denegado \
    "asumir el rol owner" \
    "SET ROLE \"$POSTGRES_ADMIN_USER\";"

unset admin_password app_password
echo "Permisos runtime verificados: CRUD/sesiones OK; owner/ALTER/TRUNCATE bloqueados."
