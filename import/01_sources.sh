#!/usr/bin/env bash

source "$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )/common.sh"

psql <<EOF
\echo *** UPDATE organisation AS d SET provider_type=s.provider_type ...
UPDATE organisation AS d SET provider_type=s.provider_type
FROM stage.source AS s
WHERE d.code=s.code AND d.provider_type IS NULL AND s.provider_type IS NOT NULL;
EOF

psql <<EOF
\echo *** UPDATE organisation AS d SET coordinator_id=p.id ...
UPDATE organisation AS d SET coordinator_id=p.id
FROM stage.source AS s JOIN person AS p ON p.code=s.coordinator_code
WHERE d.code=s.code AND d.coordinator_id IS NULL AND s.coordinator_id IS NOT NULL;
EOF

