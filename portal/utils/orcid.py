from urllib.parse import urljoin

import requests
from django.conf import settings

from .. import models
from ..models import AFFILIATION_TYPES
from ..utils.date_utils import PartialDate


class OrcidHelper:
    """ORCID Data immport helper."""

    user = None
    person = None

    # The list of the ORCDI section that will be imported
    sections = None

    AFFILIATION_SECTION_MAP = {
        "employment": AFFILIATION_TYPES.EMP,
        "membership": AFFILIATION_TYPES.MEM,
        "service": AFFILIATION_TYPES.SER,
    }
    DEFAULT_SECTIONS = [
        "employment",
        "membership",
        "service",
        "education",
        "qualification",
        "funding",
        "externalid",
    ]

    def __init__(self, user, sections=None):
        # user = models.User.get(user.id)
        self.user = user
        self.person = user.person
        self.sections = sections or self.DEFAULT_SECTIONS

    @property
    def orcid_api_url(self):
        return urljoin(settings.ORCID_API_BASE, self.user.get_orcid())

    def get_orcid_profile(self, orcid_api_url=None, access_token=None):
        return self.get_orcid_data(orcid_api_url=orcid_api_url, access_token=access_token, path="")

    def get_orcid_data(self, orcid_api_url=None, access_token=None, path=None):
        """Retrieve the user ORCID profile."""
        headers = {
            "Accept": "application/json",
            "Content-Length": "0",
        }
        if not orcid_api_url:
            orcid_api_url = self.orcid_api_url
        if not access_token:
            access_token = self.user.orcid_access_token
        if access_token:
            headers["Authorization"] = f"Bearer {access_token.token}"
        if path:
            orcid_api_url = f"{orcid_api_url}{path}"

        resp = requests.get(orcid_api_url, headers=headers)
        if resp.status_code == 200:
            extra_data = resp.json()
            return (extra_data, True)
        return (None, False)

    def get_orcid_fundings(self):
        return self.get_orcid_data(path="/fundings")

    def org_from_orcid_data(self, orcid_data):
        org_name = orcid_data.get("organization").get("name")
        if not (org := models.Organisation.where(name=org_name).last()):
            org_code = models.default_organisation_code(org_name)
            org, created = models.Organisation.objects.get_or_create(
                name=org_name,
                code=org_code,
            )
        # TODO: send a notification to admins about a new entry
        return org

    def fetch_and_load_orcid_data(self):
        """Fetch the data from orcid. ["employment", "education", "qualification", ...]"""
        orcid = self.user.get_orcid()
        # if (
        #     not orcid
        #     and self.user.person
        #     and (
        #         ppi := models.PersonPersonIdentifier.where(
        #             person=self.user.person, code__code="02"
        #         )
        #         .order_by("-id")
        #         .first()
        #     )
        # ):
        #     orcid = ppi.value
        # if not orcid and (
        #     sa := self.user.socialaccount_set.all()
        #     .filter(provider="orcid")
        #     .order_by("-id")
        #     .first()
        # ):
        #     orcid = sa.uid

        if orcid:
            if orcid.startswith("https://") or orcid.startswith("http://"):
                orcid = orcid.split("/")[-1]

            url = urljoin(settings.ORCID_API_BASE, orcid)

            if not self.user.orcid:
                self.user.orcid = orcid
                self.user.save()

            access_token = self.user.orcid_access_token
            url = urljoin(settings.ORCID_API_BASE, orcid)

            if not orcid.startswith(settings.ORCID_API_BASE):
                access_token = None

            orcid_profile, user_has_linked_orcid = self.get_orcid_profile(url, access_token)

            if user_has_linked_orcid:
                count = 0
                for section in self.sections:
                    if section == "externalid":
                        count += self.import_externa_identifiers(orcid_profile)

                    if section in ["qualification", "education"]:
                        count += self.import_academic_records(orcid_profile, section)

                    if section in ["employment", "membership", "service"]:
                        count += self.import_affiliations(orcid_profile, section)

                    if section == "funding":
                        count += self.import_recognitions(orcid_profile)

                return (count, user_has_linked_orcid)
            else:
                return (-1, user_has_linked_orcid)

        return (-1, False)

    def import_affiliations(self, orcid_profile, section):
        count = 0
        for affiliation in [
            s.get(f"{section}-summary")
            for ag in orcid_profile.get("activities-summary")
            .get(f"{section}s")
            .get("affiliation-group", [])
            for s in ag.get("summaries", [])
        ]:
            org = self.org_from_orcid_data(affiliation)
            self.create_and_save_affiliation_record(org, affiliation, section)
            count += 1
        return count

    def create_and_save_affiliation_record(self, org, orcid_data, section):
        affiliation_obj, _ = models.Affiliation.objects.get_or_create(
            put_code=orcid_data.get("put-code"), person=self.person, org=org
        )
        affiliation_obj.type = self.AFFILIATION_SECTION_MAP[section]
        role_title = orcid_data.get("role-title")
        if role_title and len(role_title) > 512:
            affiliation_obj.role_title = role_title
            affiliation_obj.role = f"{role_title[:252]}...{role_title[-252:]}"
        else:
            affiliation_obj.role = role_title
        if orcid_data.get("start-date"):
            affiliation_obj.start_date = str(PartialDate.create(orcid_data.get("start-date")))
        if orcid_data.get("end-date"):
            affiliation_obj.end_date = str(PartialDate.create(orcid_data.get("end-date")))
        affiliation_obj.save()
        return True

    def import_academic_records(self, orcid_profile, section):
        count = 0
        for affiliation in [
            s.get(f"{section}-summary")
            for ag in orcid_profile.get("activities-summary")
            .get(f"{section}s")
            .get("affiliation-group", [])
            for s in ag.get("summaries", [])
        ]:
            org = self.org_from_orcid_data(affiliation)
            self.create_and_save_academic_record(org, affiliation)
            count += 1
        return count

    def create_and_save_academic_record(self, org, orcid_data):
        # Role-title is empty for ORCID vanilla record.
        qualification, _ = models.Qualification.objects.get_or_create(
            description=(orcid_data.get("role-title") if orcid_data.get("role-title") else "N/A")
        )
        academic_obj, _ = models.AcademicRecord.get_or_create(
            put_code=orcid_data.get("put-code"), person=self.person, awarded_by=org
        )
        academic_obj.qualification = qualification

        if orcid_data.get("start-date"):
            academic_obj.start_year = PartialDate.create(orcid_data.get("start-date")).year
        if orcid_data.get("end-date"):
            academic_obj.conferred_on = str(PartialDate.create(orcid_data.get("end-date")))
        academic_obj.save()
        return True

    def import_recognitions(self, orcid_profile):
        count = 0
        fundings = [
            w
            for g in orcid_profile.get("activities-summary").get("fundings").get("group", [])
            for w in g.get("funding-summary")
        ]
        access_token = self.user.orcid_access_token
        for funding in fundings:
            url = urljoin(settings.ORCID_API_BASE, self.user.orcid) + "/funding/{}".format(
                funding.get("put-code")
            )
            funding_record, _ = self.get_orcid_profile(url, access_token)
            funding_record = funding_record if funding_record else funding
            org = self.org_from_orcid_data(funding_record)
            if self.create_and_save_recognition_record(org, funding_record):
                count += 1
        return count

    def create_and_save_recognition_record(self, org, orcid_data):

        if orcid_data.get("type") in ["award", "salary-award"] and orcid_data.get("title", {}).get(
            "title", {}
        ).get("value", {}):
            award, _ = models.Award.objects.get_or_create(
                name=orcid_data.get("title").get("title").get("value")
            )
            rec_obj, created = models.Recognition.objects.get_or_create(
                put_code=orcid_data.get("put-code"),
                person=self.person,
                defaults=dict(awarded_by=org, award=award),
            )

            if not created:
                rec_obj.awarded_by = org
                rec_obj.award = award

            if orcid_data.get("start-date"):
                rec_obj.recognized_in = PartialDate.create(orcid_data.get("start-date")).year
            if orcid_data.get("amount"):
                rec_obj.amount = float(orcid_data.get("amount").get("value"))
                rec_obj.currency = orcid_data.get("amount").get("currency-code")
            rec_obj.save()
            return True
        return False

    def import_externa_identifiers(self, orcid_profile):
        count = 0
        external_ids = [
            g
            for g in orcid_profile.get("person")
            .get("external-identifiers")
            .get("external-identifier", [])
        ]
        for ei in external_ids:
            self.create_and_save_externa_identifier_record(self.user, ei)
            count += 1
        person_identifier_orcid, _ = models.PersonIdentifierType.objects.get_or_create(
            description="ORCID ID", code="02"
        )
        _, created = models.PersonPersonIdentifier.objects.get_or_create(
            person=self.person,
            code=person_identifier_orcid,
            value=self.user.orcid,
        )
        if created:
            count += 1
        return count

    def create_and_save_externa_identifier_record(self, org, orcid_data):
        code, _ = models.PersonIdentifierType.objects.get_or_create(
            description=orcid_data.get("external-id-type")
        )
        value = orcid_data.get("external-id-value")
        ext_obj, _ = models.PersonPersonIdentifier.get_or_create(
            person=self.person, put_code=orcid_data.get("put-code"), code=code
        )
        ext_obj.value = value
        ext_obj.save()
