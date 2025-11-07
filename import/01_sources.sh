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
    AND (city ~ '\s{2,}' OR trim(city) != city);
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

psql <<EOF
MERGE INTO organisation AS d
USING (
	SELECT DISTINCT ON (code, institution, gst, ror, grid, nzbn, legal_name, alt_name) *
	FROM stage.source
	WHERE code IS NOT NULL AND institution IS NOT NULL
	ORDER BY code, institution, gst, ror, grid, nzbn, legal_name, alt_name
) AS s
 ON s.code=d.code
 	/*OR (s.institution=d.name
	 AND s.gst IS NOT DISTINCT FROM s.gst
	 AND s.ror IS NOT DISTINCT FROM s.ror
	 AND s.grid IS NOT DISTINCT FROM s.grid
	 AND s.nzbn IS NOT DISTINCT FROM s.nzbn
	 AND s.legal_name = s.legal_name
	 AND s.alt_name IS NOT DISTINCT FROM d.alt_name)*/
WHEN NOT MATCHED AND s.institution IS NOT NULL THEN INSERT(
	"name",
	alt_name,
	code,
	grid,
	gst,
	is_active,
	legal_name,
	notes,
	nz_ris_type,
	nzbn,
	provider_type,
	ror,
	website,
	sector,
	address_id
) VALUES (
	s.institution,
	s.alt_name,
	s.code,
	s.grid,
	s.gst,
	s.is_active,
	s.legal_name,
	s.notes,
	s.nz_ris_type,
	s.nzbn,
	s.provider_type,
	s.ror,
	s.website,
	s.sector,
	s.address_id)
WHEN MATCHED  AND s.institution IS NOT NULL THEN UPDATE
SET
	address_id=coalesce(s.address_id, d.address_id),
	alt_name=coalesce(d.alt_name, s.alt_name),
	grid=coalesce(d.grid, s.grid),
	gst=coalesce(d.gst, s.gst),
	is_active=coalesce(d.is_active, s.is_active),
	legal_name=coalesce(d.legal_name, s.legal_name),
	notes=coalesce(d.notes, s.notes),
	nz_ris_type=coalesce(d.nz_ris_type, s.nz_ris_type),
	nzbn=coalesce(d.nzbn, s.nzbn),
	provider_type=coalesce(d.provider_type, s.provider_type),
	ror=coalesce(d.ror, s.ror),
	website=coalesce(d.website, s.website),
	sector=coalesce(d.sector, s.sector);
EOF

