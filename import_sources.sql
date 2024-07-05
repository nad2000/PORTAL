INSERT INTO organisation (code, is_active, name, legal_name, alt_name, grid, notes)
SELECT source, isactive, institution, legalname, altname, s.grid, s.notes
FROM source AS s LEFT JOIN organisation AS o
  ON upper(trim(s.institution))=upper(trim(o.name)) OR upper(trim(s.source))=upper(trim(o.code))
WHERE o.id IS NULL;

INSERT INTO address(address) SELECT trim(s.address)/*, source, isactive, institution, legalname, altname, s.grid, s.notes*/
FROM source AS s JOIN organisation AS o ON upper(trim(s.institution))=upper(trim(o.name)) OR upper(trim(s.source))=upper(trim(o.code))
LEFT JOIN address AS a ON a.id=o.address_id
WHERE a.id IS NULL and s.address IS NOT NULL AND trim(s.address)!='';

UPDATE organisation SET address_id=a_id
FROM (
	SELECT  max(a1.id) a_id, o.id
	FROM source as s join organisation AS o
          ON upper(trim(s.institution))=upper(trim(o.name)) or upper(trim(s.source))=upper(trim(o.code))
	LEFT JOIN address AS a ON a.id=o.address_id
	JOIN address AS a1 ON a1.address=trim(s.address)
	WHERE a.id IS NULL AND s.address IS NOT NULL AND trim(s.address)!='' GROUP BY o.id
) AS d
WHERE address_id IS NULL and organisation.id=d.id;

UPDATE organisation SET ro_email='researchfunding@vuw.ac.nz' WHERE code='VUW' AND (ro_email IS NULL OR ro_email='');

UPDATE organisation SET grid=d.grid
FROM (
	SELECT o.id, s.grid
	FROM source AS s JOIN organisation AS o
          ON upper(trim(s.institution))=upper(trim(o.name)) OR upper(trim(s.source))=upper(trim(o.code))
	WHERE o.grid IS NULL OR o.grid = ''
) AS d
WHERE (organisation.grid IS NULL OR organisation.grid = '') AND organisation.id=d.id;

UPDATE organisation SET notes=d.notes
FROM (
	SELECT o.id, s.notes
	FROM source AS s JOIN organisation AS o
          ON upper(trim(s.institution))=upper(trim(o.name)) OR upper(trim(s.source))=upper(trim(o.code))
	WHERE (o.notes IS NULL OR o.notes = '') AND (s.notes IS NOT NULL OR s.notes != '')
) AS d
WHERE (organisation.notes IS NULL OR organisation.notes = '') AND organisation.id=d.id;
