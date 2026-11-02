-- Local development roles. Runs once, when the data volume is created.
-- Passwords here are local-only values and are never used on a host.
-- ati_migrator owns the schema. The others receive grants from migrations.
CREATE ROLE ati_migrator LOGIN PASSWORD 'local_dev_only' CREATEROLE;
CREATE ROLE ati_ingest LOGIN PASSWORD 'local_dev_only';
CREATE ROLE ati_app LOGIN PASSWORD 'local_dev_only';
CREATE ROLE ati_readonly LOGIN PASSWORD 'local_dev_only';

ALTER DATABASE trading OWNER TO ati_migrator;
ALTER SCHEMA public OWNER TO ati_migrator;

CREATE DATABASE trading_test OWNER ati_migrator;
\connect trading_test
ALTER SCHEMA public OWNER TO ati_migrator;
