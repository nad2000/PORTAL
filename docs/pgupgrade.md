PostgreSQL Upgrade From Version 17 to 18
========================================

The PostgreSQL 18 installer provides DB cluster upgrade at the installation stage. The PostgreSQL database cluster 17/main can be upgraded to version 18,
this will be attempted at installation. If no automated cluster upgrades are desired, uninstall the "postgresql" meta package.

Alternatively, the cluster can later be upgraded by running the command:

  ```bash
  pg_upgradecluster 17 main -v 18
  ```

Once the upgraded cluster has been validated to work, drop the old cluster using the command:

  ```bash
  pg_dropcluster 17 main
  ```


PostgreSQL Upgrade From Version 16 to 17.x
==========================================

Please follow the steps below:

1. Dump user creation script: ``pg_dumpall --globals-only -U postgres --file=globals.sql``;
1. Dump DB using the current PostgreSQL version **pg_dump**, eg,
  ```bash
  for db in portal allfunds app fm funddb 'ie-contracts' jcf marsdenreports mwf pdp pmspp rdf rfda testdb ; do
    pg_dump -C -U postgres -d ${db} --column-inserts --rows-per-insert=10000 | xz - | pv >~/${db}_$(date -Idate).sql.xz ; done
  ```
1. Upgrade PostgreSQL package: ``apt update; apt full-upgrade``
1. Restored DB:
  ```bash
  psql -p 5433 -d postgres -U postgres -f globals.sql
  for db in portal allfunds app fm funddb 'ie-contracts' jcf marsdenreports mwf pdp pmspp rdf rfda testdb ; do
    xz -d -c ./${db}_*.sql.xz | psql -p 5433 -d postgres -U postgres -f - | tee ${db}_log.log ; done
  ```
1. If you have customized the configuration, copy your configuration files from the backup directory **pgdata_** (*pg_hba.conf* and *pg_ident.conf*)
1. And finally restart the solution.

Add AI CI collation
===================

```sql
CREATE COLLATION ignore_accent_case (provider = icu, deterministic = false, locale = 'und-u-ks-level1');
SELECT 'ALTER TABLE '||table_name||' ALTER COLUMN '||column_name||' TYPE '||data_type||' ('||character_maximum_length::text||') COLLATE ignore_accent_case;' FROM information_schema.columns WHERE table_schema='public' AND column_name LIKE 'email';
```

