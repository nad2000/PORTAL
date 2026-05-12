#!/usr/bin/env bash

source "$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )/common.sh"

psql <<EOF
\echo *** UPDATE person AS d SET is_maori_decendent=s.maori_descent...
UPDATE person AS d SET is_maori_decendent=s.maori_descent
FROM stage.person AS s LEFT JOIN account_emailaddress AS ea
  ON ea.email=lower(s.email)
WHERE (d.user_id=ea.user_id OR d.code=s.code) AND d.is_maori_decendent IS NULL;
EOF

psql <<EOF
\echo INSERT INTO "title" (code, "name") ...
INSERT INTO "title" (code, "name")
SELECT DISTINCT
  CASE
    WHEN length(title) > 10 THEN
	  left(replace(replace(upper(
	  	  trim(replace(title, ' ', ''))
	   ), 'ESSOR', ''), 'IATE', ''), 10)
	ELSE   upper(trim(title))
  END AS code,
  trim(title) AS title
FROM stage.person
WHERE title IS NOT NULL AND trim(title)!=''
AND upper(trim(title)) NOT IN (SELECT upper(trim(name)) FROM "title")
ON CONFLICT (code) DO NOTHING;

ALTER TABLE stage.person ADD COLUMN IF NOT EXISTS title_code varchar(100) NULL;

UPDATE stage.person AS s
SET title_code=t.code
FROM (
	SELECT DISTINCT ON (s.title) s.title, t.code
	FROM stage.person AS s JOIN "title" AS t ON upper(trim(t.name))=upper(trim(s.title))
) AS t
WHERE upper(trim(t.title))=upper(trim(s.title));
EOF

# ADDRESSES:
# psql --echo-all  <<EOF
psql <<EOF
UPDATE stage.person
SET city=upper(regexp_replace(trim(country_name), '\s+', ' '))
WHERE
    country_name IS NOT NULL
    AND (country_name ~ '\s{2,}' OR trim(country_name) != country_name);

UPDATE stage.person
SET city=trim(city), address=trim(address)
WHERE city!=trim(city) OR address!=trim(address);

-- Fix country codes:
UPDATE stage.person SET country='AE', city=coalesce(city, 'ABU DHABI') WHERE country_name='ABU DHABI' AND country IS DISTINCT FROM 'AE';
UPDATE stage.person SET country='AU' WHERE country_name='AUSRALIA' AND country IS DISTINCT FROM 'AU';
UPDATE stage.person SET country='AU' WHERE country_name='AUSTRLIA' AND country IS DISTINCT FROM 'AU';
UPDATE stage.person SET country='AU' WHERE country_name='SOUTH AUSTRALIA' AND country IS DISTINCT FROM 'AU';
UPDATE stage.person SET country='BE' WHERE country_name='BELGUIM' AND country IS DISTINCT FROM 'BE';
UPDATE stage.person SET country='BE' WHERE country_name='BELIGUM' AND country IS DISTINCT FROM 'BE';
UPDATE stage.person SET country='BR' WHERE country_name='BRASIL' AND country IS DISTINCT FROM 'BR';
UPDATE stage.person SET country='CA' WHERE country_name='CANANDA'; UPDATE stage.person SET country='DE', city=coalesce(city, 'COLOGNE') WHERE country_name='COLOGNE' AND country IS DISTINCT FROM 'DE';
UPDATE stage.person SET country='CA', city=coalesce(city, 'VANCOUVER') WHERE country_name='VANCOUVER' AND country IS DISTINCT FROM 'CA';
UPDATE stage.person SET country='CD' WHERE country_name='DRC' AND country IS DISTINCT FROM 'CD';
UPDATE stage.person SET country='CH', city=coalesce(city, 'LAUSANNE') WHERE country_name='LAUSANNE' AND country IS DISTINCT FROM 'CH';
UPDATE stage.person SET country='CN' WHERE country_name LIKE '%PEOPL%CHINA%' AND country IS DISTINCT FROM 'CN';
UPDATE stage.person SET country='CN' WHERE country_name='REPUBLIC OF CHINA' AND country IS DISTINCT FROM 'CN';
UPDATE stage.person SET country='CO' WHERE country_name='COLUMBIA' AND country IS DISTINCT FROM 'CO';
UPDATE stage.person SET country='CZ' WHERE country_name='CZECHIA' AND country IS DISTINCT FROM 'CZ';
UPDATE stage.person SET country='DK' WHERE country_name='DENAMRK' AND country IS DISTINCT FROM 'DK';
UPDATE stage.person SET country='FI' WHERE country_name='FINALND' AND country IS DISTINCT FROM 'FI';
UPDATE stage.person SET country='FM' WHERE country_name='FEDERATED STATES OF MICRONESIA' AND country IS DISTINCT FROM 'FM';
UPDATE stage.person SET country='FR', city=coalesce(city, 'PARIS') WHERE country_name='PARIS' AND country IS DISTINCT FROM 'FR';
UPDATE stage.person SET country='GB' WHERE country_name='ENGLAND' AND country IS DISTINCT FROM 'GB';
UPDATE stage.person SET country='GB' WHERE country_name='UK' AND country IS DISTINCT FROM 'GB';
UPDATE stage.person SET country='GB' WHERE country_name='UNIETD KINGDOM' AND country IS DISTINCT FROM 'GB';
UPDATE stage.person SET country='GB' WHERE country_name='UNITD KINGDOM' AND country IS DISTINCT FROM 'GB';
UPDATE stage.person SET country='GB' WHERE country_name='UNITED KINDDOM' AND country IS DISTINCT FROM 'GB';
UPDATE stage.person SET country='GB' WHERE country_name='UNITED KINDGOM' AND country IS DISTINCT FROM 'GB';
UPDATE stage.person SET country='GB' WHERE country_name='UNITED KINDOM' AND country IS DISTINCT FROM 'GB';
UPDATE stage.person SET country='GB' WHERE country_name='UNITED KINGDON' AND country IS DISTINCT FROM 'GB';
UPDATE stage.person SET country='GB' WHERE country_name='UNITED KINGOM' AND country IS DISTINCT FROM 'GB';
UPDATE stage.person SET country='GB', address=CASE WHEN address ~* 'NORTHERN IRELAND' THEN address ELSE address||',\rNORTHERN IRELAND' END WHERE country_name='NORTHERN IRELAND' AND country IS DISTINCT FROM 'GB';
UPDATE stage.person SET country='GB', address=CASE WHEN address ~* 'SCOTLAND' THEN address ELSE address||',\rSCOTLAND' END WHERE country_name='SCOTLAND' AND country IS DISTINCT FROM 'GB';
UPDATE stage.person SET country='GB', address=CASE WHEN address ~* 'WALES' THEN address ELSE address||',\rWALES' END WHERE country_name='WALES' AND country IS DISTINCT FROM 'GB';
UPDATE stage.person SET country='IE' WHERE country_name='PEOPLE''S REPUBLIC OF IRELAND' AND country IS DISTINCT FROM 'IE';
UPDATE stage.person SET country='IE' WHERE country_name='REPUBLIC OF IRELAND' AND country IS DISTINCT FROM 'IE';
UPDATE stage.person SET country='IN' WHERE country_name='INDIANA' AND country IS DISTINCT FROM 'IN';
UPDATE stage.person SET country='IR' WHERE country_name='ISLAMIC REPUBLIC OF IRAN' AND country IS DISTINCT FROM 'IR';
UPDATE stage.person SET country='IT' WHERE country_name='ITLAY' AND country IS DISTINCT FROM 'IT';
UPDATE stage.person SET country='KR' WHERE country_name='KOREA' AND country IS DISTINCT FROM 'KR';
UPDATE stage.person SET country='KR' WHERE country_name='REPBULIC OF KOREA' AND country IS DISTINCT FROM 'KR';
UPDATE stage.person SET country='KR' WHERE country_name='REPLUBLIC OF KOREA' AND country IS DISTINCT FROM 'KR';
UPDATE stage.person SET country='KR' WHERE country_name='REPUBLIC OF KOREA' AND country IS DISTINCT FROM 'KR';
UPDATE stage.person SET country='KR' WHERE country_name='SOUTH KOREA' AND country IS DISTINCT FROM 'KR';
UPDATE stage.person SET country='LU' WHERE country_name='LUXEMOURG' AND country IS DISTINCT FROM 'LU';
UPDATE stage.person SET country='MX' WHERE country_name LIKE 'M%XICO' AND country IS DISTINCT FROM 'MX';
UPDATE stage.person SET country='NL' WHERE country_name='THE NETHERLAND' AND country IS DISTINCT FROM 'NL';
UPDATE stage.person SET country='NL' WHERE country_name='THE NETHERLANDS' AND country IS DISTINCT FROM 'NL';
UPDATE stage.person SET country='RU' WHERE country_name='RUSSIA' AND country IS DISTINCT FROM 'RU';
UPDATE stage.person SET country='SG' WHERE country_name='REPUBLIC OF SINGAPORE' AND country IS DISTINCT FROM 'SG';
UPDATE stage.person SET country='SI' WHERE country_name='SLOVENIJA' AND country IS DISTINCT FROM 'SI';
UPDATE stage.person SET country='SK' WHERE country_name='SLOVAK REPUBLIC' AND country IS DISTINCT FROM 'SK';
UPDATE stage.person SET country='US' WHERE country_name IN ('USA', 'USA ', 'UNITED STATES', 'UNITED STASTES OF AMERICA', 'UNITED DATES OF AMERICA', 'UNITED STATES') AND country IS DISTINCT FROM 'US';
UPDATE stage.person SET country='US', address=CASE WHEN address ~* 'ARIZONA' THEN address ELSE address||',\rARIZONA' END WHERE country_name='ARIZONA' AND country IS DISTINCT FROM 'US';
UPDATE stage.person SET country='US', address=CASE WHEN address ~* 'CALIFORNIA' THEN address ELSE address||',\rCALIFORNIA' END WHERE country_name='CALIFORNIA' AND country IS DISTINCT FROM 'US';
UPDATE stage.person SET country='US', address=CASE WHEN address ~* 'FLORIDA' THEN address ELSE address||',\rFLORIDA' END WHERE country_name='FLORIDA' AND country IS DISTINCT FROM 'US';
UPDATE stage.person SET country='US', address=CASE WHEN address ~* 'HAWAII' THEN address ELSE address||',\rHAWAII' END WHERE country_name='HAWAII' AND country IS DISTINCT FROM 'US';
UPDATE stage.person SET country='US', address=CASE WHEN address ~* 'Hawaii' THEN address ELSE address||',\rHawaii' END WHERE country_name='HAWAI''I' AND country IS DISTINCT FROM 'US';
UPDATE stage.person SET country='US', address=CASE WHEN address ~* 'KANSAS' THEN address ELSE address||',\rKANSAS' END WHERE country_name='KANSAS' AND country IS DISTINCT FROM 'US';
UPDATE stage.person SET country='US', address=CASE WHEN address ~* 'MAINE' THEN address ELSE address||',\rMAINE' END WHERE country_name='MAINE' AND country IS DISTINCT FROM 'US';
UPDATE stage.person SET country='US', address=CASE WHEN address ~* 'MARYLAND' THEN address ELSE address||',\rMARYLAND' END WHERE country_name='MARYLAND' AND country IS DISTINCT FROM 'US';
UPDATE stage.person SET country='US', address=CASE WHEN address ~* 'OHIO' THEN address ELSE address||',\rOHIO' END WHERE country_name='OHIO' AND country IS DISTINCT FROM 'US';
UPDATE stage.person SET country='US', address=CASE WHEN address ~* 'OREGON' THEN address ELSE address||',\rOREGON' END WHERE country_name='OREGON' AND country IS DISTINCT FROM 'US';
UPDATE stage.person SET country='US', address=CASE WHEN address ~* 'TEXAS' THEN address ELSE address||',\rTEXAS' END WHERE country_name='TEXAS' AND country IS DISTINCT FROM 'US';
UPDATE stage.person SET country='UY' WHERE country_name='URUGAY' AND country IS DISTINCT FROM 'UY';
UPDATE stage.person SET country='VN' WHERE country_name='SOCIALIST REPUBLIC OF VIETNAM' AND country IS DISTINCT FROM 'VN';
--
UPDATE address
SET city=trim(city), address=trim(address)
WHERE city!=trim(city) OR address!=trim(address);
--
WITH c AS (
	SELECT DISTINCT
		upper(a.city) AS city,
		upper(a.country) AS country_code,
		upper(cc.name) AS country_name
	FROM "address" AS a LEFT JOIN "country" AS c ON c.name ~* a.city
	  LEFT JOIN "country" AS cc ON cc.code=a.country
	WHERE c.code IS NULL AND a.city IS NOT NULL AND a.city!= ''
)
UPDATE stage.person AS s
SET
    city=c.city,
    country=coalesce(s.country, c.country_code)
FROM c
WHERE (s.city IS NULL OR c.city='')
	AND s.address IS NOT NULL
	AND s.address!= ''
	AND s.address ~* c.city;

\echo populate with address entries:
MERGE INTO "address" AS a
USING (SELECT DISTINCT country, city, address FROM stage.person) AS s
  ON s.country IS NOT DISTINCT FROM a.country
	  AND s.city IS NOT DISTINCT FROM a.city
	  AND s.address IS NOT DISTINCT FROM a.address
WHEN NOT MATCHED AND NOT (s.country IS NOT NULL AND city IS NOT NULL AND address IS NOT NULL) THEN
INSERT (country, city, address)
VALUES (
    s.country,
    s.city,
    CASE
      WHEN s.address IS NULL OR s.address='' THEN FORMAT('%s/%s', s.city, s.country)
      ELSE s.address
    END
);

-- link address entries to the person:
ALTER TABLE stage.person ADD COLUMN IF NOT EXISTS address_id int;
WITH a AS (
	SELECT max(a.id) AS "id", a.country, a.city, a.address
	FROM "address" AS a JOIN stage.person AS s
	  ON s.country IS NOT DISTINCT FROM a.country
		  AND s.city IS NOT DISTINCT FROM a.city
		  AND (s.address IS NOT DISTINCT FROM a.address
			OR FORMAT('%s/%s', s.city, s.country) = a.address)
	GROUP BY a.country, a.city, a.address
)
UPDATE stage.person AS s
SET address_id = a.id
FROM a
WHERE s.address_id IS NULL
  AND s.country IS NOT DISTINCT FROM a.country
  AND s.city IS NOT DISTINCT FROM a.city
  AND (s.address IS NOT DISTINCT FROM a.address
	OR FORMAT('%s/%s', s.city, s.country) = a.address);
EOF

psql <<EOF
/*
-- Update "gender" (NB! execute only once!):
ALTER TABLE person RENAME COLUMN gender TO "_gender";
ALTER TABLE person_history RENAME COLUMN gender TO "_gender";
ALTER TABLE person ADD COLUMN gender char(1) NULL;
ALTER TABLE person_history ADD COLUMN gender char(1) NULL;
UPDATE perso  WHERE _gender=0;
UPDATE person SET gender=CASE _gender WHEN 0 THEN 'X' WHEN 1 THEN 'M' WHEN 2 THEN 'F' WHEN 3 THEN 'D' ELSE '0' END  WHERE _gender IS NOT NULL;
UPDATE person_history SET gender=CASE _gender WHEN 0 THEN 'X' WHEN 1 THEN 'M' WHEN 2 THEN 'F' WHEN 3 THEN 'D' ELSE '0' END  WHERE _gender IS NOT NULL;
*/
UPDATE stage.person SET email=lower(trim(email)) WHERE email!=lower(trim(email));
UPDATE stage.person SET code=upper(trim(code)) WHERE code!=upper(trim(code));
ALTER TABLE stage.person ADD COLUMN IF NOT EXISTS user_id int NULL;
WITH u AS (
  SELECT DISTINCT ON (s.code)
      s.code,
      coalesce(ea.user_id, p.user_id) AS user_id,
      s.email
  FROM stage.person AS s LEFT JOIN account_emailaddress AS ea
    ON ea.email=s.email
  LEFT JOIN person AS p ON p.code=s.code
  WHERE
    s.user_id IS NULL
    AND (ea.user_id IS NOT NULL OR p.user_id IS NOT NULL)
)
UPDATE stage.person AS s
SET user_id=s.user_id
FROM u
WHERE
  u.code=s.code AND s.user_id IS NULL;
-- Merge persons:
MERGE INTO person AS d
USING stage.person AS s ON s.code=d.code OR s.email=d.email
WHEN NOT MATCHED AND s.institution IS NOT NULL THEN INSERT(
	user_id,
	created_at,
	updated_at,
	activity,
	code,
	date_of_birth,
	email,
	first_name,
	friendly_name,
	gender,
	initials,
	label_name,
	last_name,
	orcid,
	other_names,
	salutation,
	is_maori_decendent,
	title,
	is_active,
	address_id,
	is_accepted,
	has_protection_patterns
) VALUES (
	s.user_id,
	s.date_added,
	s.date_changed,
	s.activity,
	s.code,
	s.date_of_birth,
	s.email,
	s.firstname,
	s.friendly_name,
	s.gender,
	s.initials,
	s.label_name,
	s.lastname,
	s.orcid,
	s.other_names,
	s.salutation,
	s.maori_descent,
	s.title_code,
	s.active,
	s.address_id,
	true,
	true
)
WHEN MATCHED AND (
    d.user_id IS NULL OR d.activity IS NULL OR d.code IS NULL
    OR d.date_of_birth IS NULL OR d.email IS NULL OR d.first_name IS NULL
    OR d.friendly_name IS NULL OR d.gender IS NULL OR d.initials IS NULL
    OR d.label_name IS NULL OR d.last_name IS NULL OR d.orcid IS NULL
    OR d.other_names IS NULL OR d.salutation IS NULL OR d.is_maori_decendent IS NULL
    OR d.title IS NULL OR d.is_active IS NULL OR d.address_id IS NULL)
THEN UPDATE
SET
	user_id=coalesce(d.user_id, s.user_id),
	code=coalesce(d.code, s.code),
	created_at=coalesce(d.created_at, s.date_added),
	updated_at=coalesce(d.updated_at, s.date_changed),
	activity=coalesce(d.activity, s.activity),
	date_of_birth=coalesce(d.date_of_birth, s.date_of_birth),
	email=coalesce(d.email, s.email),
	first_name=coalesce(d.first_name, s.firstname),
	friendly_name=coalesce(d.friendly_name, s.friendly_name),
	gender=coalesce(d.gender, s.gender),
	initials=coalesce(d.initials, s.initials),
	label_name=coalesce(d.label_name, s.label_name),
	last_name=coalesce(d.last_name, s.lastname),
	orcid=coalesce(d.orcid, s.orcid),
	other_names=coalesce(d.other_names, s.other_names),
	salutation=coalesce(d.salutation, s.salutation),
	is_maori_decendent=coalesce(d.is_maori_decendent, s.maori_descent),
	title=coalesce(d.title, s.title_code),
	is_active=coalesce(d.is_active, s.active),
	address_id=coalesce(d.address_id, s.address_id);
EOF

# POSTACTION:
psql <<EOF
\echo *** UPDATE organisation AS d SET coordinator_id=p.id ...
UPDATE organisation AS d SET coordinator_id=p.id
FROM stage.source AS s JOIN person AS p ON p.code=s.coordinator_code
WHERE d.code=s.code AND d.coordinator_id IS NULL AND s.coordinator_id IS NOT NULL;
EOF
