#!/bin/sh
set -eu

validar_identificador() {
    nombre="$1"
    valor="$2"
    if ! printf '%s' "$valor" | grep -Eq '^[a-z_][a-z0-9_]{0,62}$'; then
        echo "ERROR: $nombre debe ser un identificador PostgreSQL simple." >&2
        exit 2
    fi
}

: "${POSTGRES_HOST:?Falta POSTGRES_HOST}"
: "${POSTGRES_PORT:?Falta POSTGRES_PORT}"
: "${POSTGRES_DB:?Falta POSTGRES_DB}"
: "${POSTGRES_ADMIN_USER:?Falta POSTGRES_ADMIN_USER}"
: "${POSTGRES_APP_USER:?Falta POSTGRES_APP_USER}"

validar_identificador POSTGRES_DB "$POSTGRES_DB"
validar_identificador POSTGRES_ADMIN_USER "$POSTGRES_ADMIN_USER"
validar_identificador POSTGRES_APP_USER "$POSTGRES_APP_USER"

if [ "$POSTGRES_ADMIN_USER" = "$POSTGRES_APP_USER" ]; then
    echo "ERROR: el owner y el rol runtime deben ser distintos." >&2
    exit 2
fi

ADMIN_SECRET=/run/secrets/postgres_admin_password
APP_SECRET=/run/secrets/postgres_app_password
if [ ! -r "$ADMIN_SECRET" ] || [ ! -r "$APP_SECRET" ]; then
    echo "ERROR: faltan secretos de base montados." >&2
    exit 2
fi

admin_password="$(cat "$ADMIN_SECRET")"
app_password="$(cat "$APP_SECRET")"
if [ -z "$admin_password" ] || [ -z "$app_password" ]; then
    echo "ERROR: un secreto de base está vacío." >&2
    exit 2
fi

export PGPASSWORD="$admin_password"

psql \
    --no-psqlrc \
    --set=ON_ERROR_STOP=1 \
    --host="$POSTGRES_HOST" \
    --port="$POSTGRES_PORT" \
    --username="$POSTGRES_ADMIN_USER" \
    --dbname="$POSTGRES_DB" \
    --set=admin_role="$POSTGRES_ADMIN_USER" \
    --set=app_role="$POSTGRES_APP_USER" \
    --set=app_password="$app_password" \
    --set=db_name="$POSTGRES_DB" <<'SQL'
SELECT pg_get_userbyid(datdba) = :'admin_role' AS admin_es_owner
FROM pg_database
WHERE datname = current_database()
\gset
\if :admin_es_owner
\else
    \echo 'ERROR: POSTGRES_ADMIN_USER no es owner de la base.'
    \quit 3
\endif

SELECT format(
    'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE '
    'NOREPLICATION NOBYPASSRLS NOINHERIT',
    :'app_role',
    :'app_password'
)
WHERE NOT EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname = :'app_role'
)
\gexec

SELECT (
    EXISTS (
        SELECT 1
        FROM pg_class AS objeto
        JOIN pg_roles AS owner ON owner.oid = objeto.relowner
        WHERE owner.rolname = :'app_role'
          AND objeto.relpersistence <> 't'
    )
    OR EXISTS (
        SELECT 1
        FROM pg_proc AS funcion
        JOIN pg_roles AS owner ON owner.oid = funcion.proowner
        WHERE owner.rolname = :'app_role'
    )
    OR EXISTS (
        SELECT 1
        FROM pg_namespace AS esquema
        JOIN pg_roles AS owner ON owner.oid = esquema.nspowner
        WHERE owner.rolname = :'app_role'
    )
) AS app_es_owner
\gset
\if :app_es_owner
    \echo 'ERROR: el rol runtime ya posee objetos; corregir ownership antes de continuar.'
    \quit 4
\endif

ALTER ROLE :"app_role"
    WITH LOGIN PASSWORD :'app_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT;

SELECT format('REVOKE %I FROM %I', rol_padre.rolname, :'app_role')
FROM pg_auth_members AS membresia
JOIN pg_roles AS rol_padre ON rol_padre.oid = membresia.roleid
JOIN pg_roles AS miembro ON miembro.oid = membresia.member
WHERE miembro.rolname = :'app_role'
\gexec

REVOKE CONNECT, TEMPORARY ON DATABASE :"db_name" FROM PUBLIC;
REVOKE ALL PRIVILEGES ON DATABASE :"db_name" FROM :"app_role";
GRANT CONNECT ON DATABASE :"db_name" TO :"app_role";

REVOKE ALL PRIVILEGES ON SCHEMA public FROM PUBLIC;
REVOKE ALL PRIVILEGES ON SCHEMA public FROM :"app_role";
GRANT USAGE ON SCHEMA public TO :"app_role";

REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM :"app_role";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO :"app_role";

REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM :"app_role";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO :"app_role";

REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;
REVOKE ALL PRIVILEGES ON ALL FUNCTIONS IN SCHEMA public FROM :"app_role";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO :"app_role";

ALTER DEFAULT PRIVILEGES FOR ROLE :"admin_role" IN SCHEMA public
    REVOKE ALL PRIVILEGES ON TABLES FROM :"app_role";
ALTER DEFAULT PRIVILEGES FOR ROLE :"admin_role" IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_role";

ALTER DEFAULT PRIVILEGES FOR ROLE :"admin_role" IN SCHEMA public
    REVOKE ALL PRIVILEGES ON SEQUENCES FROM :"app_role";
ALTER DEFAULT PRIVILEGES FOR ROLE :"admin_role" IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO :"app_role";

ALTER DEFAULT PRIVILEGES FOR ROLE :"admin_role" IN SCHEMA public
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE :"admin_role" IN SCHEMA public
    REVOKE ALL PRIVILEGES ON FUNCTIONS FROM :"app_role";
ALTER DEFAULT PRIVILEGES FOR ROLE :"admin_role" IN SCHEMA public
    GRANT EXECUTE ON FUNCTIONS TO :"app_role";

SELECT format(
    'REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER '
    'ON TABLE public.auditoria_registroauditoria FROM %I',
    :'app_role'
)
WHERE to_regclass('public.auditoria_registroauditoria') IS NOT NULL
\gexec
SQL

unset PGPASSWORD admin_password app_password
echo "Rol runtime PostgreSQL provisionado con privilegios mínimos."
