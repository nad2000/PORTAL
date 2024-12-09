PostgreSQL Upgrade From Version 16 to 17.x
==========================================

Please follow the steps bellow:

#. Dump DB using the current PostgreSQL version **pg_dump**, eg, ``for db in allfunds app fm funddb 'ie-contracts' jcf marsdenreports mwf pdp pmspp rdf rfda testdb ; do pg_dump -c -U postgres -d ${db} --column-inserts --rows-per-insert=10000 >~/${db}_$(date -Idate).sql ; done
``
#. Upgrade PostgreSQL package: ``apt update; apt full-upgrade``
#. Restored DB: ``xz -d -c ./full.sql.xz | psql -d orcidhub -U postgres -f - &>log.log``
#. If you had customized the configuration, copy your configuration files form the backup directory **pgdata_** (*pg_hba.conf* and *pg_ident.conf*)
#. And finally restart the solution.
