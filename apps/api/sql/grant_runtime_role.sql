\if :{?runtime_role}
GRANT chargegrid_api TO :"runtime_role";
\else
\echo 'Use: psql MIGRATION_DATABASE_URL -v runtime_role=nome_do_usuario -f sql/grant_runtime_role.sql'
\quit 1
\endif
