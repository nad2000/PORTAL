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

psql <<EOF
\echo *** UPDATE organisation AS d SET source=s.provider_type ...
UPDATE organisation AS d SET sector=s.sector
FROM stage.source AS s
WHERE d.code=s.code AND d.sector IS NULL AND s.sector IS NOT NULL;
EOF

psql <<EOF
UPDATE "address" SET city=regexp_replace(trim(city), '\s+', ' ')
WHERE
    city IS NOT NULL
    AND trim(city) != ''
    AND city!=regexp_replace(trim(city), '\s+' , ' ');
EOF

psql <<EOF
-- ALTER TABLE stage.source ADD COLUMN IF NOT EXISTS country_code varchar(10);
-- set up the city:
WITH c AS (
	SELECT DISTINCT
		upper(a.city) AS city,
		upper(a.country) AS country_code,
		upper(cc.name) AS country_name
	FROM "address" AS a LEFT JOIN "country" AS c ON c.name ~* a.city
	  LEFT JOIN "country" AS cc ON cc.code=a.country
	WHERE c.code IS NULL AND a.city IS NOT NULL AND TRIM(a.city)!= ''
)
UPDATE stage.source AS s
SET
    city=c.city,
    country=coalesce(s.country, c.country_code)
FROM c
WHERE s.city IS NULL
	AND s.address IS NOT NULL
	AND TRIM(s.address)!= ''
	AND s.address ~* c.city;
-- set up the country form the address field:
WITH c AS (
	SELECT DISTINCT
		upper(coalesce(a.country, c.code)) AS country_code,
		upper(c.name) AS country_name
	FROM "address" AS a
	  LEFT JOIN "country" AS c ON c.code=a.country
)
-- SELECT s.address, c.country_name
UPDATE stage.source AS s
SET country=coalesce(s.country, c.country_code)
FROM c
WHERE s.country IS NULL AND c.country_name IS NOT NULL
	AND s.address IS NOT NULL
	AND TRIM(s.address)!= ''
	AND s.address ~* c.country_name;
-- set the country code:
WITH c AS (
	SELECT DISTINCT
		c.code AS country_code,
		upper(c.name) AS country_name
	FROM "country" AS c
)
UPDATE stage.source AS s
SET country=c.country_code
FROM c
WHERE s.country IS NULL AND c.country_code IS NOT NULL
	AND s.address IS NOT NULL
	AND TRIM(s.address)!= ''
	AND s.address ~* c.country_name;
-- populate with address entries:
\echo populate with address entries:
MERGE INTO "address" AS a
USING (SELECT DISTINCT country, city, address FROM stage.source) AS s
  ON s.country IS NOT DISTINCT FROM a.country
	  AND s.city IS NOT DISTINCT FROM a.city
	  AND s.address IS NOT DISTINCT FROM a.address
WHEN NOT MATCHED AND NOT (s.country IS NOT NULL AND city IS NOT NULL AND address IS NOT NULL) THEN
INSERT (country, city, address)
VALUES (s.country, s.city, CASE WHEN s.address IS NULL THEN FORMAT('%s/%s', s.city, s.country) ELSE s.address END);
-- link address entries to the sources:
ALTER TABLE stage.source ADD COLUMN IF NOT EXISTS address_id int;
WITH a AS (
	SELECT max(a.id) AS "id", a.country, a.city, a.address
	FROM "address" AS a JOIN stage.source AS s
	  ON s.country IS NOT DISTINCT FROM a.country
		  AND s.city IS NOT DISTINCT FROM a.city
		  AND (s.address IS NOT DISTINCT FROM a.address
			OR FORMAT('%s/%s', s.city, s.country) = a.address)
	GROUP BY a.country, a.city, a.address
)
UPDATE stage.source AS s
SET address_id = a.id
FROM a
WHERE s.address_id IS NULL
  AND s.country IS NOT DISTINCT FROM a.country
  AND s.city IS NOT DISTINCT FROM a.city
  AND (s.address IS NOT DISTINCT FROM a.address
	OR FORMAT('%s/%s', s.city, s.country) = a.address);

EOF
