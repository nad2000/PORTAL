PostgreSQL Upgrade From Version 16 to 17.x
==========================================

Please follow the steps below:

1. Dump user creation script: ``pg_dumpall --globals-only -U postgres --file=globals.sql``;
1. Dump DB using the current PostgreSQL version **pg_dump**, eg,
  ```bash
  for db in portal allfunds app fm funddb 'ie-contracts' jcf marsdenreports mwf pdp pmspp rdf rfda testdb ; do
    pg_dump -C -U postgres -d ${db} --column-inserts --rows-per-insert=10000 | xz - | pv >~/${db}_$(date -Idate).sql.xz ; done
  ```
2. Upgrade PostgreSQL package: ``apt update; apt full-upgrade``
1. Restored DB:
  ```bash
  psql -p 5433 -d postgres -U postgres -f globals.sql
  for db in portal allfunds app fm funddb 'ie-contracts' jcf marsdenreports mwf pdp pmspp rdf rfda testdb ; do
    xz -d -c ./${db}_*.sql.xz | psql -p 5433 -d postgres -U postgres -f - | tee ${db}_log.log ; done
  ```
4. If you have customized the configuration, copy your configuration files from the backup directory **pgdata_** (*pg_hba.conf* and *pg_ident.conf*)
1. And finally restart the solution.
