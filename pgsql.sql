-- 1. Benutzer anlegen (in PostgreSQL heißt das "Rolle mit LOGIN")
CREATE ROLE vm_app WITH LOGIN PASSWORD 'root';

-- 2. Darf sich mit der Datenbank verbinden und das Schema public benutzen
GRANT CONNECT ON DATABASE vertragsverwaltung TO vm_app;
GRANT USAGE ON SCHEMA public TO vm_app;

-- 3. Gleiche Rechte wie vorher in MySQL: nur Daten lesen/ändern, keine Tabellen anlegen/löschen
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO vm_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO vm_app;

-- 4. Auch für Tabellen, die später neu angelegt werden
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO vm_app;