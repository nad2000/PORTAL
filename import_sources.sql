insert into organisation (code, is_active, name, legal_name, alt_name, grid, notes)
select source, isactive, institution, legalname, altname, s.grid, s.notes
from source as s left join organisation as o
  on upper(trim(s.institution))=upper(trim(o.name)) or upper(trim(s.source))=upper(trim(o.code))
where o.id is null;
insert into address(address) select trim(s.address)/*, source, isactive, institution, legalname, altname, s.grid, s.notes*/
from source as s join organisation as o on upper(trim(s.institution))=upper(trim(o.name)) or upper(trim(s.source))=upper(trim(o.code))
left join address as a on a.id=o.address_id
where a.id is null and s.address is not null and trim(s.address)!='';
update organisation set address_id=a_id
from (
	select  max(a1.id) a_id, o.id
	from source as s join organisation as o on upper(trim(s.institution))=upper(trim(o.name)) or upper(trim(s.source))=upper(trim(o.code))
	left join address as a on a.id=o.address_id
	join address as a1 on a1.address=trim(s.address)
	where a.id is null and s.address is not null and trim(s.address)!='' group by o.id
) as d
where address_id is null and organisation.id=d.id;
