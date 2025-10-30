#!/usr/bin/env bash

source "$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )/common.sh"

psql <<EOF
\echo *** UPDATE person AS d SET is_maori_decendent=s.maori_descent...
UPDATE person AS d SET is_maori_decendent=s.maori_descent
FROM stage.person AS s LEFT JOIN account_emailaddress AS ea
  ON ea.email=lower(s.email)
WHERE (d.user_id=ea.user_id OR d.code=s.code) AND d.is_maori_decendent IS NULL;
EOF


# POSTACTION:
psql <<EOF
\echo *** UPDATE organisation AS d SET coordinator_id=p.id ...
UPDATE organisation AS d SET coordinator_id=p.id
FROM stage.source AS s JOIN person AS p ON p.code=s.coordinator_code
WHERE d.code=s.code AND d.coordinator_id IS NULL AND s.coordinator_id IS NOT NULL;
EOF
