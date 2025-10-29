#!/usr/bin/env bash

source "$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )/common.sh"

psql <<EOF
\echo UPDATE person AS d SET is_maori_descent=s.maori_descent...
UPDATE person AS d SET is_maori_descent=s.maori_descent
FROM stage.person AS s LEFT JOIN account_emailaddress AS ea
  ON ea.email=lower(s.email)
WHERE (d.user_id=ea.user_id OR d.code=s.code) AND d.is_maori_descent IS NULL;
EOF
