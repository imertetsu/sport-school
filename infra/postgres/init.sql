-- init.sql — provisión MÍNIMA de la base de LatinoSport.
--
-- Se monta en /docker-entrypoint-initdb.d/ y SOLO corre la PRIMERA vez que el
-- volumen de datos de Postgres está vacío (comportamiento de la imagen oficial).
--
-- Alcance deliberadamente acotado (separación de responsabilidades con db-dev):
--   - La base `latinosport` la crea la imagen vía POSTGRES_DB (no aquí).
--   - El rol `latinosport_app` (LOGIN NOSUPERUSER NOBYPASSRLS), las tablas, la RLS,
--     los GRANTs y la función login_lookup SECURITY DEFINER los crea la
--     MIGRACIÓN de db-dev (`alembic upgrade head`, como owner/postgres).
--     NO se crean aquí.
--
-- Lo único que provisionamos: la extensión pgcrypto, necesaria para
-- gen_random_uuid() (PKs UUID, contrato C0). Se crea como superusuario en la
-- fase de init, antes de que corran las migraciones.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
