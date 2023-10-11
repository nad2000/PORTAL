import base64
import hashlib
import io
import os
import re
import secrets
import ssl
import subprocess
import tempfile
import time
from collections import OrderedDict
from datetime import date, datetime
from functools import lru_cache, partial, wraps
from urllib.parse import urljoin, urlparse

import simple_history
from admin_ordering.models import OrderableModel
from allauth.account.models import EmailAddress
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.sites.managers import CurrentSiteManager
from django.contrib.sites.models import Site
from django.core.exceptions import ValidationError
from django.core.files.base import File
from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
)
from django.db import connection
from django.db.models import (
    CASCADE,
    DO_NOTHING,
    PROTECT,
    SET_NULL,
    BooleanField,
    Case,
    CharField,
    DateField,
    DateTimeField,
    DecimalField,
    F,
    FileField,
    ForeignKey,
    Manager,
    ManyToManyField,
    OneToOneField,
    PositiveIntegerField,
    PositiveSmallIntegerField,
    Prefetch,
    Q,
    SmallIntegerField,
    Subquery,
    Sum,
    TextField,
    URLField,
    When,
    prefetch_related_objects,
)
from django.db.models.functions import Cast, Coalesce
from django.http import HttpRequest
from django.template.loader import get_template
from django.urls import reverse
from django.utils.translation import get_language, gettext
from django.utils.translation import gettext_lazy as _
from django_fsm import FSMField, FSMFieldMixin, transition
from django_fsm_log.helpers import FSMLogDescriptor
from limesurveyrc2api.limesurvey import LimeSurvey
from model_utils import Choices
from model_utils.fields import MonitorField, StatusField
from private_storage.fields import PrivateFileField
from PyPDF2 import PdfFileMerger, PdfFileReader
from sentry_sdk import capture_message
from simple_history.models import HistoricalRecords
from taggit.models import TagBase
from weasyprint import HTML

from common.models import (
    Base,
    EmailField,
    FixedCharField,
    HelperMixin,
    Model,
    PersonMixin,
    TimeStampMixin,
    Title,
)

from .utils import send_mail, vignere


def __(s):
    """Temporarily disabale 'gettex'"""
    return s


def site_contact_email(site_id=None):
    if site_id and site_id == 4 or settings.SITE_ID == 4:
        return "puanga@royalsociety.org.nz"
    return "pmscienceprizes@royalsociety.org.nz"


GENDERS = Choices(
    (0, _("Prefer not to say")), (1, _("Male")), (2, _("Female")), (3, _("Gender diverse"))
)

AFFILIATION_TYPES = Choices(
    ("EDU", _("Education")),
    ("EMP", _("Employment")),
    ("MEM", _("Membership")),
    ("SER", _("Service")),
)

ETHNICITIES = Choices(
    "Chinese",
    "Cook Islands Māori",
    "English",
    "European",
    "Filipino",
    "Indian",
    "Māori",
    "New Zealander",
    "Other",
    "Samoan",
    "Tongan",
)

QUALIFICATION_LEVEL = Choices(
    (0, _("No Qualification")),
    (1, _("Level 1 Certificate")),
    (2, _("Level 2 Certificate")),
    (3, _("Level 3 Certificate")),
    (4, _("Level 4 Certificate")),
    (5, _("Level 5 Diploma/Certificate")),
    (6, _("Level 6 Graduate Certificate, Level 6 Diploma/Certificate")),
    (7, _("Bachelor Degree, Level 7 Graduate Diploma/Certificate, Level 7 Diploma/ Certificate")),
    (8, _("Postgraduate Diploma/Certificate, Bachelor Honours")),
    (9, _("Masters Degree")),
    (10, _("Doctorate Degree")),
    (23, _("Overseas Secondary School Qualification")),
    (94, _("Don't Know")),
)

EMPLOYMENT_STATUS = Choices(
    (1, "Paid employee"),
    (2, "Employer"),
    (3, "Self-employed and without employees"),
    (4, "Unpaid family worker"),
    (6, "Student"),
    (5, "Not stated"),
)

LANGUAGES = Choices(
    "Afrikaans",
    "Arabic",
    "Bahasa Indonesia",
    "Chinese (not further defined)",
    "Cook Islands Māori",
    "Dutch",
    "English (New Zealand English)",
    "Fijian",
    "French",
    "German",
    "Gujarati",
    "Hindi",
    "Italian",
    "Japanese",
    "Khmer",
    "Korean",
    "Malayalam",
    "Malaysian",
    "Mandarin Chinese",
    "Min Chinese",
    "Māori",
    "New Zealand Sign Language",
    "Niuean",
    "Other",
    "Persian",
    "Punjabi",
    "Russian",
    "Samoan",
    "Serbo-Croatian",
    "Sinhala",
    "Spanish",
    "Tagalog",
    "Tamil",
    "Thai",
    "Tongan",
    "Urdu",
    "Vietnamese",
    "Yue Chinese (Cantonese)",
)


def fsm_log(func=None, allow_inline=False):
    # Combines fsm_log_by and fsm_log_description with defaulting
    # to the request user usnigng simple_history context
    if func is None:
        return partial(fsm_log, allow_inline=allow_inline)

    @wraps(func)
    def wrapped(instance, *args, **kwargs):
        by = kwargs.get("by")
        request = kwargs.get("request")
        context = simple_history.models.HistoricalRecords.context
        if not request:
            request = getattr(context, "request", None)
        if not by and request and (u := request.user):
            kwargs["by"] = by = u
        with FSMLogDescriptor(instance, "by", by):
            with FSMLogDescriptor(instance, "description") as descriptor:
                description = (
                    kwargs.get("description")
                    or (
                        request
                        and (request.POST.get("description") or request.POST.get("resolution"))
                    )
                    or descriptor
                )
                if description:
                    if isinstance(description, str):
                        description = description.strip()
                    descriptor.set(description)
                    if "description" not in kwargs:
                        kwargs["description"] = description
                else:
                    description = descriptor
                    if allow_inline:
                        kwargs["description"] = descriptor

                if description and not getattr(instance, "_change_reason", None):
                    instance._change_reason = description
                return func(instance, *args, **kwargs)

    return wrapped


def get_request(*args, **kwargs):
    if "request" in kwargs:
        return kwargs["request"]
    for v in args:
        if isinstance(v, HttpRequest):
            return v


class PdfFileMixin:
    """Mixin for handling attached file update and conversion to a PDF copy."""

    @property
    def file_size(self):
        return os.path.getsize(self.file.path)

    @property
    def filename(self):
        return os.path.basename(self.file.name)

    @property
    def pdf_file(self):
        if self.file:
            if self.file.name.lower().endswith(".pdf"):
                return self.file
            if not self.converted_file:
                self.update_converted_file()
            return self.converted_file.file

    @property
    def pdf_filename(self):
        if self.file:
            if self.file.name.lower().endswith(".pdf"):
                return os.path.basename(self.file.name)
            return os.path.basename(self.pdf_file.name)

    def title_page(self):
        """Title page for composite export into PDF"""
        tp = {
            "TITLES": [
                f"{self.required_document}" f"{self.filename}",
            ]
            if hasattr(self, "required_document")
            else [
                f"{_('Attachment')} - {self.__class__.__name__}",
                self,
                f"({self.filename})",
            ],
            _("File Name"): self.filename,
            _("Submitted At"): self.updated_at or self.created_at,
        }
        if hasattr(self, "full_name"):
            tp[_("Submitted By")] = self.full_name
        return tp

    @property
    def is_pdf_content(self):
        """The content is PDF."""
        return self.file.name and self.file.name.lower().endswith(".pdf")

    def update_converted_file(self):
        """If the attached file is not PDF convert and update the PDF version."""

        if self.file.name and self.file.name.lower().endswith(".pdf") and self.converted_file:
            self.converted_file = None
            return

        elif self.file.name and not self.file.name.lower().endswith(".pdf"):
            cp = subprocess.run(
                [
                    "loffice",
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    tempfile.gettempdir(),
                    self.file.path,
                ],
                capture_output=True,
            )
            if cp.returncode or (
                (stderr := (cp.stderr and cp.stderr.decode())) and "error" in stderr.lower()
            ):
                if cp.returncode:
                    raise Exception(
                        _(
                            "Failed to convert your application form into PDF. "
                            "Please save your application form into PDF format and try to upload it again."
                        ),
                    )

                raise Exception(
                    _(
                        "Failed to convert your application form into PDF: %s. "
                        "Please save your application form into PDF format and try to upload it again."
                    )
                    % stderr,
                )

            output_filename, ext = os.path.splitext(os.path.basename(self.file.name))
            output_filename = f"{output_filename}.pdf"
            output_path = os.path.join(tempfile.gettempdir(), output_filename)

            with open(output_path, "rb") as of:
                cf = ConvertedFile()
                cf.file.save(output_filename, File(of))
                cf.save()

            self.converted_file = cf
            return cf


class StateField(FSMFieldMixin, StatusField):
    def __init__(self, *args, **kwargs):
        # kwargs.setdefault("max_length", 50)
        kwargs.setdefault("choices_name", "STATES")
        super().__init__(*args, **kwargs)


# class StateKeyField(FSMFieldMixin, StatusField):
#     def __init__(self, *args, **kwargs):
#         # kwargs.setdefault("max_length", 50)
#         kwargs.setdefault("choices_name", "STATES")
#         super().__init__(*args, **kwargs)

#     def get_state(self, instance):
#         return instance.__dict__[self.attname]

#     def set_state(self, instance, state):
#         instance.__dict__[self.attname] = self.to_python(state)


def hash_int(
    value,
):
    return hashlib.shake_256(bytes(value)).hexdigest(5)


User = get_user_model()

simple_history.register(EmailAddress, app="portal", table_name="email_address_history")


class ApplicationSiteManager(Manager):
    """Select only applications linked to the current site."""

    def get_queryset(self):
        return super().get_queryset().filter(application__site=Site.objects.get_current())


class RoundSiteManager(Manager):
    """Select only rounds linked to the current site."""

    def get_queryset(self):
        return super().get_queryset().filter(round__site=Site.objects.get_current())


class Subscription(Model):
    site = ForeignKey(Site, on_delete=PROTECT, default=Model.get_current_site_id)
    objects = CurrentSiteManager()
    all_objects = Manager()

    email = EmailField(max_length=120)
    name = CharField(max_length=120, null=True, blank=True)
    is_confirmed = BooleanField(null=True, blank=True)

    def __str__(self):
        return self.name or self.email

    class Meta:
        db_table = "subscription"


class Ethnicity(Model):
    code = CharField(max_length=5, primary_key=True)
    description = CharField(max_length=40)
    level_three_code = CharField(max_length=3)
    level_three_description = CharField(max_length=40)
    level_two_code = CharField(max_length=2)
    level_two_description = CharField(max_length=40)
    level_one_code = CharField(max_length=20)
    level_one_description = CharField(max_length=40)
    definition = CharField(max_length=120, null=True, blank=True)

    def __str__(self):
        description = self.description
        if description.endswith(" nfd"):
            return description[:-4]
        elif description.endswith(" nec"):
            return f"{_('Other')} {description[:-4]}"
        return description

    class Meta:
        db_table = "ethnicity"
        ordering = ["code"]
        verbose_name_plural = _("ethnicities")


class Language(Model):
    code = CharField(max_length=7, primary_key=True)
    description = CharField(max_length=100)
    definition = CharField(max_length=120, null=True, blank=True)

    def __str__(self):
        return self.description

    class Meta:
        db_table = "language"
        ordering = ["code"]


DOCUMENT_ROLES = Choices(
    ("AB", _("Award Budget")),
    ("AF", _("Application Form")),
    ("AIMS", _("Research Aims")),
    ("B", _("Budget")),
    ("CV", _("Curriculum Vitae")),
    ("E", _("Ethics Statement")),
    ("F", _("Form")),
    ("PB", _("Proposal Budget")),
    ("PT", _("Project Timeline")),
)


class DocumentType(Model):
    # site = ForeignKey(Site, on_delete=PROTECT, default=Model.get_current_site_id)
    # objects = CurrentSiteManager()
    role = CharField(max_length=10, choices=DOCUMENT_ROLES, null=True, blank=True)
    name = CharField(_("Name"), max_length=200)

    def __str__(self):
        return self.name

    class Meta:
        db_table = "document_type"


class RoleType(Model):
    code = FixedCharField(primary_key=True, max_length=2)
    name = CharField(max_length=255, blank=True, null=True)
    description = CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.code}: {self.name}"

    class Meta:
        db_table = "role_type"


class CareerStage(Model):
    code = CharField(max_length=2, primary_key=True)
    description = CharField(max_length=40)
    definition = TextField(max_length=1000)

    def __str__(self):
        return self.description

    class Meta:
        db_table = "career_stage"
        ordering = ["code"]


class PersonIdentifierType(Model):
    code = CharField(max_length=2, null=True, blank=True)
    description = CharField(max_length=40)
    definition = TextField(max_length=200, null=True, blank=True)

    def __str__(self):
        return self.description

    class Meta:
        db_table = "person_identifier_type"
        ordering = ["description"]


class PersonIdentifierPattern(Model):
    person_identifier_type = ForeignKey(PersonIdentifierType, on_delete=CASCADE)
    pattern = CharField(max_length=100)

    class Meta:
        db_table = "person_identifier_pattern"


class IwiGroup(Model):
    code = CharField(max_length=4, primary_key=True)
    description = CharField(max_length=80)
    parent_code = CharField(max_length=2)
    parent_description = CharField(max_length=100)
    definition = TextField(max_length=200)

    def __str__(self):
        return self.description

    class Meta:
        db_table = "iwi_group"
        ordering = ["code"]


class ProtectionPattern(Model):
    code = PositiveSmallIntegerField(_("code"), primary_key=True)
    description = CharField(_("description"), max_length=80)
    pattern = CharField(_("pattern"), max_length=80)
    comment = TextField(_("comment"), max_length=200, null=True, blank=True)

    def __str__(self):
        return f"{self.code}: {self.description}"

    class Meta:
        db_table = "protection_pattern"
        ordering = ["description"]


class ApplicationDecision(Model):
    code = CharField(max_length=2, primary_key=True)
    description = CharField(max_length=80)
    definition = TextField(max_length=200)

    def __str__(self):
        return self.description

    class Meta:
        db_table = "application_decision"
        ordering = ["description"]


# class VisionMatauranga(Model):
#     code = CharField(max_length=3, primary_key=True)
#     framework = CharField(max_length=255, blank=True, null=True)
#     description = TextField(blank=True, null=True)

#     def __str__(self):
#         return f"{self.code}: {self.framework}"

#     class Meta:
#         db_table = "vision_matauranga"
#         verbose_name = "Vision Mātauranga"


class SocioEconomicObjective(Model):
    # Version	Code	Description	Definition	Two_Digit_Code	Two_Digit_Description	Four_Digit_Code	Four_Digit_Description
    version = CharField(max_length=10, default="1.0.0")
    code = CharField(max_length=6, primary_key=True)
    description = CharField(max_length=150, blank=True, null=True)
    definition = CharField(max_length=200, null=True, blank=True)
    # two_digit_code = CharField(max_length=2)
    # two_digit_description = CharField(max_length=60)
    # four_digit_code = CharField(max_length=4)
    # four_digit_description = CharField(max_length=100)
    source = CharField(max_length=255, blank=True, null=True)

    history = HistoricalRecords(table_name="seo_history")

    def __str__(self):
        return f"{self.code}: {self.description}"

    class Meta:
        db_table = "socio_economic_objective"
        verbose_name = "SEO"
        verbose_name_plural = "SEOs"


# class TypeOfActivity(Model):
#     code = CharField(max_length=2, primary_key=True)
#     description = CharField(max_length=255, blank=True, null=True)
#     source = CharField(max_length=255, blank=True, null=True)

#     def __str__(self):
#         return f"{self.code}: {self.description}"

#     class Meta:
#         db_table = "type_of_activity"
#         verbose_name = "ToA"
#         verbose_name_plural = "ToAs"


class Rcc(Model):
    rcc = CharField(max_length=8)
    description = CharField(max_length=80, blank=True, null=True)
    source = CharField(max_length=255, blank=True, null=True)
    code = CharField(max_length=255, blank=True, null=True)

    def natural_key(self):
        return (self.rcc,)

    def __str__(self):
        return f"{self.rcc}: {self.description}"

    class Meta:
        db_table = "rcc"
        verbose_name = _("RCC")
        verbose_name_plural = _("RCCs")


class FieldOfResearch(Model):
    version = CharField(max_length=10, default="1.0.0")
    code = CharField(max_length=6, primary_key=True)
    description = CharField(_("description"), max_length=200)
    definition = CharField(max_length=280, null=True, blank=True)
    two_digit_code = CharField(max_length=2)
    two_digit_description = CharField(max_length=60)
    four_digit_code = CharField(max_length=4)
    four_digit_description = CharField(max_length=100)
    rcc = CharField(max_length=10, null=True, blank=True)
    is_stem = BooleanField(
        _("is STEM"),
        default=False,
        help_text=_("Science, Technology, Engineering, and Mathematics.."),
    )

    def __str__(self):
        return f"{self.code}: {self.description}"

    class Meta:
        db_table = "field_of_research"
        verbose_name_plural = _("fields of research")


class FieldOfStudy(Model):
    version = CharField(max_length=20, default="ISCED-F 2013")
    code = CharField(max_length=6, primary_key=True, verbose_name=_("code"))
    description = CharField(_("description"), max_length=100)
    two_digit_code = CharField(max_length=2)
    two_digit_description = CharField(max_length=60)
    four_digit_code = CharField(max_length=4)
    four_digit_description = CharField(max_length=100)
    definition = CharField(max_length=200, null=True, blank=True)

    def __str__(self):
        return self.description

    class Meta:
        db_table = "field_of_study"
        ordering = ["description"]
        verbose_name_plural = _("fields of study")


class ProfileCareerStage(Model):
    profile = ForeignKey("Profile", on_delete=CASCADE)
    career_stage = ForeignKey(CareerStage, on_delete=CASCADE, verbose_name=_("career stage"))
    year_achieved = PositiveSmallIntegerField(
        _("year achieved"),
        null=True,
        blank=True,
        validators=[MinValueValidator(1900), MaxValueValidator(2100)],
        help_text=_("Year that you first attained the career stage"),
    )

    class Meta:
        db_table = "profile_career_stage"


ORCID_ID_REGEX = re.compile(r"^([X\d]{4}-?){3}[X\d]{4}$")


def validate_orcid_id(value):
    """Sanitize and validate ORCID iD (both format and the check-sum)."""
    if not value:
        return

    if "/" in value:
        value = value.split("/")[-1]

    if not ORCID_ID_REGEX.match(value):
        raise ValidationError(
            _(
                "Invalid ORCID iD %(value)s. It should be in the form of 'xxxx-xxxx-xxxx-xxxx' where x is a digit."
            ),
            params={"value": value},
        )
    check = 0
    for n in value:
        if n == "-":
            continue
        check = (2 * check + int(10 if n == "X" else n)) % 11
    if check != 1:
        raise ValidationError(
            _("Invalid ORCID iD %(value)s checksum. Make sure you have entered correct ORCID iD."),
            params={"value": value},
        )

    return value


class ProfilePersonIdentifier(Model):
    profile = ForeignKey(
        "Profile",
        on_delete=CASCADE,
    )
    code = ForeignKey(
        PersonIdentifierType,
        on_delete=DO_NOTHING,
        verbose_name=_("type"),
        help_text=_("Choose a type or enter a new identifier or reference type"),
    )
    value = CharField(_("Identifier or reference (e.g. reference/ID number)"), max_length=100)
    put_code = PositiveIntegerField(_("put-code"), null=True, blank=True, editable=False)

    class Meta:
        db_table = "profile_person_identifier"

    def clean(self, *args, **kwargs):
        super().clean(*args, **kwargs)
        if self.code_id:
            if self.code.code == "02":
                validate_orcid_id(self.value)
            elif self.code.code == "03":
                v = self.value
                if len(v) < 16:
                    raise ValidationError(
                        _("ISNI value %(value)s should be at least 16 characters long."),
                        params={"value": v},
                    )
                v = v[-16:].upper()
                if not re.match(r"\d{15}[\dX]", v):
                    raise ValidationError(
                        _(
                            "ISNI value %(value)s pattern in not valid. "
                            "It should contain digits or 'X' as the final character."
                        ),
                        params={"value": v},
                    )
                if sum(int(c) for c in v[:15]) % 11 != (10 if v[-1] == "X" else int(v[-1])):
                    raise ValidationError(
                        _("ISNI value %(value)s checksum does not match the given control value."),
                        params={"value": v},
                    )

    def __str__(self):
        return f"{self.code} / {self.value}"


class OrgIdentifierType(Model):
    code = CharField(max_length=2, primary_key=True)
    description = CharField(max_length=20)
    definition = TextField(max_length=200)

    def __str__(self):
        return self.description

    class Meta:
        db_table = "org_identifier_type"
        verbose_name = _("organisation identifier type")
        ordering = ["code"]


class Qualification(Model):
    code = CharField(max_length=2, null=True, blank=True)
    description = CharField(max_length=100)
    definition = TextField(max_length=100, null=True, blank=True)
    is_nzqf = BooleanField(
        _("the New Zealand Qualifications Framework Qualification level"),
        default=True,
    )

    def __str__(self):
        return self.description

    class Meta:
        db_table = "qualification"
        ordering = ["definition"]


def default_organisation_code(name):
    name = "".join(c for c in name.lower() if c.isalnum() or c == " ")
    prefix = "".join(w[0] for w in name.split() if w).upper()
    code = prefix[:8]
    suffix = 1
    while Organisation.where(code=code).exists():
        if len(prefix) > 7:
            prefix = prefix[:7]
        code = f"{prefix}{suffix}"
        suffix += 1
    return code


class Organisation(Model):
    name = CharField(max_length=200)
    identifier_type = ForeignKey(OrgIdentifierType, null=True, blank=True, on_delete=SET_NULL)
    identifier = CharField(max_length=24, null=True, blank=True)
    code = CharField(max_length=10, blank=True, default="", unique=True)

    history = HistoricalRecords(table_name="organisation_history")

    def __str__(self):
        return self.name

    def __init__(self, *args, **kwargs):
        if kwargs.get("name") and not kwargs.get("code"):
            kwargs["code"] = default_organisation_code(kwargs.get("name"))
        super().__init__(*args, **kwargs)

    def get_code(self):
        return self.code or default_organisation_code(self.name)

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = default_organisation_code(self.name)
        original_code = self.id and self.get(self.id).code
        super().save(*args, **kwargs)
        if original_code and self.code.strip() and self.code != original_code:
            if org_applications := list(
                Application.where(
                    org=self, number__icontains=f"-{original_code}-", state__in=["new", "draft"]
                )
            ):
                for a in org_applications:
                    ApplicationNumber.get_or_create(application=a, number=a.number)
                    # a.number = a.number.replace(f"-{original_code}-", f"-{self.code}-")
                    a.number = default_application_number(a)
                    a.save(update_fields=["number"])

    class Meta:
        db_table = "organisation"


class OrgName(Model):
    org = ForeignKey(
        Organisation,
        on_delete=CASCADE,
        verbose_name=_("organisation"),
        related_name="alternative_names",
    )
    name = CharField(max_length=200)

    history = HistoricalRecords(table_name="org_name_history")

    def __str__(self):
        return f"{self.org}: {self.name}"

    class Meta:
        db_table = "org_name"


class Affiliation(Model):
    profile = ForeignKey("Profile", on_delete=CASCADE, related_name="affiliations")
    org = ForeignKey(Organisation, on_delete=CASCADE, verbose_name=_("organisation"))
    type = CharField(_("type"), max_length=10, choices=AFFILIATION_TYPES)
    role = CharField(
        _("role"),
        max_length=512,
        null=True,
        blank=True,
        help_text="position or role, e.g., student, postdoc, etc.",
    )
    qualification = CharField(
        _("qualification"), max_length=512, null=True, blank=True
    )  # , help_text="position or degree")
    start_date = DateField(_("start date"), null=True, blank=True)
    end_date = DateField(_("end date"), null=True, blank=True)
    put_code = PositiveIntegerField(_("put-code"), null=True, blank=True, editable=False)

    history = HistoricalRecords(table_name="affiliation_history")

    def __str__(self):
        if not (self.start_date or self.end_date):
            return f"{self.org}"
        if not self.end_date:
            return f"{self.org}: {self.start_date}"
        if not self.start_date:
            return f"{self.org}: until {self.end_date}"
        return f"{self.org}: {self.start_date} to {self.end_date}"

    class Meta:
        db_table = "affiliation"


def validate_bod(value):
    if value and value >= date.today():
        raise ValidationError(
            _("Date of birth cannot be in the future: %(value)s"),
            params={"value": value},
        )


class Profile(PersonMixin, Model):
    user = OneToOneField(User, on_delete=CASCADE, verbose_name=_("user"), related_name="profile")
    gender = PositiveSmallIntegerField(
        _("gender"), choices=GENDERS, null=True, blank=False, default=0
    )
    date_of_birth = DateField(_("date of birth"), null=True, blank=True, validators=[validate_bod])
    ethnicities = ManyToManyField(
        Ethnicity, db_table="profile_ethnicity", blank=True, verbose_name=_("ethnicities")
    )
    is_ethnicities_completed = BooleanField(default=True)
    # CharField(max_length=20, null=True, blank=True, choices=ETHNICITIES)
    education_level = PositiveSmallIntegerField(
        _("education level"), null=True, blank=True, choices=QUALIFICATION_LEVEL
    )
    employment_status = PositiveSmallIntegerField(
        _("employment status"), null=True, blank=True, choices=EMPLOYMENT_STATUS
    )
    # years since arrival in New Zealand
    primary_language_spoken = CharField(
        _("primary language spoken"), max_length=40, null=True, blank=True, choices=LANGUAGES
    )
    languages_spoken = ManyToManyField(
        Language, db_table="profile_language", blank=True, verbose_name=_("languages spoken")
    )
    iwi_groups = ManyToManyField(
        IwiGroup, db_table="profile_iwi_group", blank=True, verbose_name=_("iwi groups")
    )
    is_iwi_groups_completed = BooleanField(default=True)
    # study participation
    # legally registered relationship status
    # highest secondary school qualification
    # total personal income
    # job indicator work and labour force status
    # hours usually worked
    # status in employment
    # occupation
    is_accepted = BooleanField(_("privacy policy accepted"), default=False)
    career_stages = ManyToManyField(
        CareerStage, blank=True, through="ProfileCareerStage", verbose_name=_("career stages")
    )
    is_career_stages_completed = BooleanField(default=False)
    external_ids = ManyToManyField(
        PersonIdentifierType,
        blank=True,
        through="ProfilePersonIdentifier",
        verbose_name=_("external IDs"),
    )
    # affiliations = ManyToManyField(Organisation, blank=True, through="Affiliation")

    is_external_ids_completed = BooleanField(default=False)

    history = HistoricalRecords(table_name="profile_history")
    has_protection_patterns = BooleanField(default=True)
    account_approval_message_sent_at = DateTimeField(null=True, blank=True, editable=False)

    @property
    def employments(self):
        return self.affiliations.filter(type="EMP")

    is_employments_completed = BooleanField(default=False)

    @property
    def educations(self):
        return self.affiliations.filter(type="EDU")

    is_professional_bodies_completed = BooleanField(default=False)

    is_academic_records_completed = BooleanField(default=False)
    is_recognitions_completed = BooleanField(default=False)
    # is_professional_memberships_completed = BooleanField(default=False)
    is_cvs_completed = BooleanField(default=False)

    @property
    def protection_patterns(self):
        return ProtectionPatternProfile.get_data(self)

    def __str__(self):
        u = self.user
        return (
            (
                f"{u.name} ({u.username})'s profile"
                if u.name and u.username
                else f"{u.name or u.username or u.email}'s profile"
            )
            if u
            else f"Profile: ID={self.id}"
        )

    def save(self, *args, **kwargs):
        created = not self.id
        super().save(*args, **kwargs)
        if created:
            ProfileProtectionPattern.objects.bulk_create(
                [
                    ProfileProtectionPattern(profile=self, protection_pattern_id=code)
                    for code in [5, 6]
                ]
            )

    def get_absolute_url(self):
        return reverse("profile-instance", kwargs={"pk": self.pk})

    @property
    def is_completed(self):
        return (
            self.is_career_stages_completed
            and self.is_employments_completed
            and self.is_ethnicities_completed
            and self.is_professional_bodies_completed
            and self.is_recognitions_completed
            and self.is_iwi_groups_completed
            and self.is_external_ids_completed
            and self.is_cvs_completed
            and self.is_accepted
        )

    @is_completed.setter
    def is_completed(self, value):
        self.is_career_stages_completed = value
        self.is_professional_bodies_completed = value
        self.is_employments_completed = value
        self.is_ethnicities_completed = value
        self.is_recognitions_completed = value
        self.is_iwi_groups_completed = value
        self.is_external_ids_completed = value
        self.is_cvs_completed = value
        self.is_accepted = value

    class Meta:
        db_table = "profile"


class ProfileProtectionPattern(Model):
    profile = ForeignKey(Profile, on_delete=CASCADE, related_name="profile_protection_patterns")
    protection_pattern = ForeignKey(
        ProtectionPattern,
        on_delete=CASCADE,
        related_name="profile_protection_patterns",
        verbose_name=_("protection pattern"),
    )
    expires_on = DateField(_("expires on"), null=True, blank=True)

    def __str__(self):
        return f"{self.protection_pattern} of {self.profile}"

    class Meta:
        db_table = "profile_protection_pattern"
        unique_together = ("profile", "protection_pattern")


class ProtectionPatternProfile(Model):
    code = PositiveSmallIntegerField(_("code"), primary_key=True)
    description = CharField(_("description"), max_length=80)
    pattern = CharField(_("pattern"), max_length=80)
    comment = TextField(_("comment"), null=True, blank=True)
    profile = ForeignKey(Profile, null=True, on_delete=DO_NOTHING, verbose_name=_("profile"))
    expires_on = DateField(_("expires on"), null=True, blank=True)

    @classmethod
    # for people only demographic, identifiable and professional protections make sense
    def get_data(cls, profile):
        q = cls.objects.raw(
            """
            SELECT
                pp.code,
                pp.description,
                pp.pattern,
                pp.description_en,
                pp.description_mi,
                pp.comment_en,
                pp.comment_mi,
                ppp.expires_on,
                ppp.profile_id,
                ppp.created_at,
                ppp.updated_at
            FROM protection_pattern AS pp
            LEFT JOIN profile_protection_pattern AS ppp
                ON ppp.protection_pattern_id=pp.code AND ppp.profile_id=%s
            WHERE pp.code IN (5, 6, 7, 9)
            ORDER BY description_"""
            + get_language(),
            [profile.id],
        )

        prefetch_related_objects(q, "profile")
        return q

    class Meta:
        managed = False


class AcademicRecord(Model):
    profile = ForeignKey(Profile, related_name="academic_records", on_delete=CASCADE)
    start_year = PositiveIntegerField(
        _("start year"),
        validators=[MinValueValidator(1960), MaxValueValidator(2099)],
        null=True,
        blank=True,
    )
    qualification = ForeignKey(
        Qualification, null=True, blank=True, on_delete=DO_NOTHING, verbose_name=_("qualification")
    )
    conferred_on = DateField(_("conferred on"), null=True, blank=True)
    discipline = ForeignKey(
        FieldOfStudy, on_delete=CASCADE, null=True, blank=True, verbose_name=_("discipline")
    )
    awarded_by = ForeignKey(Organisation, on_delete=CASCADE, verbose_name=_("awarded by"))
    research_topic = CharField(_("research topic"), max_length=80, null=True, blank=True)
    put_code = PositiveIntegerField(_("put-code"), null=True, blank=True, editable=False)

    history = HistoricalRecords(table_name="academic_record_history")

    class Meta:
        db_table = "academic_record"


class Award(Model):
    name = CharField(_("prestigious prize or medal"), max_length=200)

    def __str__(self):
        return self.name

    class Meta:
        db_table = "award"


class Recognition(Model):
    profile = ForeignKey(Profile, related_name="recognitions", on_delete=CASCADE)
    recognized_in = PositiveSmallIntegerField(_("year of recognition"), null=True, blank=True)
    award = ForeignKey(Award, on_delete=CASCADE, verbose_name=_("award"))
    awarded_by = ForeignKey(Organisation, on_delete=CASCADE, verbose_name=_("awarded by"))
    amount = DecimalField(
        max_digits=9, decimal_places=2, null=True, blank=True, verbose_name=_("amount")
    )
    currency = CharField(_("Currency code"), null=True, blank=True, max_length=3)
    put_code = PositiveIntegerField(null=True, blank=True, editable=False)

    history = HistoricalRecords(table_name="recognition_history")

    def __str__(self):
        return self.award.name

    class Meta:
        db_table = "recognition"


# class Nominee(Model):
#     title = CharField(max_length=40, null=True, blank=True)
#     # email = EmailField(max_length=119)
#     email = EmailField("email address")
#     first_name = CharField(max_length=30)
#     middle_names = CharField(
#         _("middle names"),
#         blank=True,
#         null=True,
#         max_length=280,
#         help_text=_("Comma separated list of middle names"),
#     )
#     last_name = CharField(max_length=150)

#     user = ForeignKey(User, null=True, blank=True, on_delete=SET_NULL)

#     class Meta:
#         db_table = "nominee"


class ConvertedFile(HelperMixin, Base):
    site = ForeignKey(Site, on_delete=PROTECT, default=Model.get_current_site_id)
    objects = CurrentSiteManager()
    all_objects = Manager()

    file = PrivateFileField(upload_to="converted/%Y/%m/%d")

    @property
    def file_size(self):
        return os.path.getsize(self.file.path)

    def __str__(self):
        return self.file.name


APPLICATION_STATES = Choices(
    (None, None),
    ("new", _("new")),
    ("draft", _("draft")),
    ("tac_accepted", _("TAC accepted")),
    ("submitted", _("submitted")),
    ("cancelled", _("cancelled")),
    ("withdrawn", _("withdrawn")),
    ("approved", _("approved")),
)


class FundManager(Manager):
    def get_by_natural_key(self, code, *args, **kwargs):
        return self.get(code=code)


class Fund(Model):
    code = FixedCharField(max_length=2, primary_key=True, db_column="code")
    code3 = FixedCharField(max_length=3, null=True, blank=True)
    description = TextField(_("description"), max_length=10000, null=True, blank=True)
    cost_centre = PositiveSmallIntegerField(_("Cost Center"), null=True, blank=True)
    catalyst_cost_centre = PositiveSmallIntegerField(
        _("Catalyst Cost Center"), null=True, blank=True
    )
    site = ForeignKey(Site, on_delete=PROTECT, default=Model.get_current_site_id)
    history = HistoricalRecords(table_name="fund_history")
    objects = FundManager()

    def __str__(self):
        return f"{self.code}: {self.description}"

    class Meta:
        db_table = "fund"
        # unique_together = ("code", "site")


class Category(Model):
    code = CharField(max_length=5, primary_key=True, db_column="code")
    # site = ForeignKey(Site, on_delete=PROTECT, default=Model.get_current_site_id)
    # objects = CurrentSiteManager()
    description = TextField(_("short description"), max_length=10000, null=True, blank=True)

    class Meta:
        db_table = "category"
        # unique_together = ("code", "site")


class LetterOfSupport(PdfFileMixin, Model):
    file = PrivateFileField(
        upload_subfolder=lambda instance: [
            "letters_of_support",
        ],
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "pdf",
                    "odt",
                    "ott",
                    "oth",
                    "odm",
                    "doc",
                    "docx",
                    "docm",
                    "docb",
                ]
            )
        ],
    )
    converted_file = ForeignKey(
        ConvertedFile, null=True, blank=True, on_delete=SET_NULL, verbose_name=_("converted file")
    )

    def __str__(self):
        return self.filename

    class Meta:
        db_table = "letter_of_support"


def default_application_number(application, exclude_numbers=None):
    code = application.round.scheme.code
    org_code = application.org.get_code()
    year = f"{application.round.opens_on.year}"
    last_number = (
        Application.all_objects.filter(
            # round=application.round,
            number__isnull=False,
            number__istartswith=f"{code}-{org_code}-{year}",
        )
        .order_by("-number")
        .values("number")
        .first()
    )
    application_number = int(last_number["number"].split("-")[-1]) + 1 if last_number else 1
    while True:
        number = f"{code}-{org_code}-{year}-{application_number:03}"
        if not exclude_numbers or number not in exclude_numbers:
            return number
        application_number += 1


class ApplicationFor(Model):
    application = ForeignKey("Application", on_delete=CASCADE, related_name="application_fors")
    code = ForeignKey(FieldOfResearch, on_delete=CASCADE, db_column="code", verbose_name="FoR")
    share = PositiveSmallIntegerField(null=True, blank=True, default=None)

    def __str__(self):
        return self.code_id

    class Meta:
        # auto_created = True
        db_table = "application_for"
        unique_together = (("application", "code"),)
        verbose_name = "application FOR"
        verbose_name_plural = "application FORs"


class ApplicationSeo(Model):
    application = ForeignKey("Application", on_delete=CASCADE, related_name="application_seos")
    code = ForeignKey(
        SocioEconomicObjective, on_delete=CASCADE, db_column="code", verbose_name="SEO"
    )
    share = PositiveSmallIntegerField(null=True, blank=True, default=None)

    def __str__(self):
        return self.code_id

    class Meta:
        # auto_created = True
        db_table = "application_seo"
        unique_together = (("application", "code"),)
        verbose_name = "application SEO"
        verbose_name_plural = "application SEOs"


# class ApplicationToa(Model):
#     application = ForeignKey("Application", on_delete=CASCADE)
#     code = ForeignKey(TypeOfActivity, on_delete=CASCADE, db_column="code", verbose_name="ToA")
#     share = PositiveSmallIntegerField(null=True, blank=True, default=None)

#     def __str__(self):
#         return self.code_id

#     class Meta:
#         # auto_created = True
#         db_table = "application_toa"
#         unique_together = (("application", "code"),)
#         verbose_name = "application ToA"
#         verbose_name_plural = "application ToAs"


# class ApplicationVM(Model):
#     application = ForeignKey("Application", on_delete=CASCADE)
#     code = ForeignKey(VisionMatauranga, on_delete=CASCADE, db_column="code", verbose_name="VM")
#     share = PositiveSmallIntegerField(null=True, blank=True, default=None)

#     def __str__(self):
#         return self.code_id

#     class Meta:
#         # auto_created = True
#         db_table = "application_vm"
#         unique_together = (("application", "code"),)
#         verbose_name = "application VM"
#         verbose_name_plural = "application VMs"


class ApplicationMixin:
    STATES = APPLICATION_STATES


def photo_identity_help_text():
    if Site.objects.get_current().domain != "international.royalsociety.org.nz":
        return _(
            "Please upload a scanned copy of your passport or drivers license in PDF, JPG, or PNG format"
        )
    return _("Please upload a scanned copy of your passport in PDF, JPG, or PNG format")


class Keyword(TagBase):
    class Meta:
        verbose_name = _("Keyword")
        verbose_name_plural = _("Keywords")
        db_table = "keyword"


# class KeywordItem(GenericTaggedItemBase, TaggedItemBase):

#     tag = ForeignKey(
#         Keyword,
#         on_delete=CASCADE,
#         related_name="%(app_label)s_%(class)s_items",
#     )

#     class Meta:
#         verbose_name = _("keyworded item")
#         verbose_name_plural = _("keyworded items")
#         db_table = 'keyword_item'


class ApplicationKeyword(Model):
    application = ForeignKey("Application", on_delete=CASCADE)
    keyword = ForeignKey(Keyword, on_delete=CASCADE)

    class Meta:
        db_table = "application_keyword"


class Application(ApplicationMixin, PersonMixin, PdfFileMixin, Model):
    # objects = RoundSiteManager()
    site = ForeignKey(Site, on_delete=PROTECT, default=Model.get_current_site_id)
    objects = CurrentSiteManager()
    all_objects = Manager()

    is_preliminary = BooleanField(_("is preliminary"), null=True, blank=True, default=False)
    preliminary = ForeignKey(
        "self",
        on_delete=CASCADE,
        null=True,
        blank=True,
        help_text=_("Expression of Interest or preliminary application"),
    )
    number = CharField(
        _("number"), max_length=24, null=True, blank=True, editable=False, unique=True
    )
    submitted_by = ForeignKey(
        User, null=True, blank=True, on_delete=SET_NULL, verbose_name=_("submitted by")
    )
    cv = ForeignKey(
        "CurriculumVitae",
        editable=True,
        null=True,
        blank=True,
        on_delete=PROTECT,
        verbose_name=_("curriculum vitae"),
    )
    application_title = CharField(
        max_length=200, null=True, blank=True, verbose_name=_("application name")
    )

    round = ForeignKey(
        "Round", on_delete=PROTECT, related_name="applications", verbose_name=_("round")
    )
    # Members of the team must also complete the "Team Members & Signatures" Form.
    is_team_application = BooleanField(default=False, verbose_name=_("team application"))
    team_name = CharField(max_length=200, null=True, blank=True, verbose_name=_("team name"))

    # Applicant or nominator:
    # title = CharField(
    #     max_length=40, null=True, blank=True, choices=TITLES, verbose_name=_("title")
    # )
    title = ForeignKey(
        Title,
        null=True,
        blank=True,
        verbose_name=_("title"),
        db_column="title",
        on_delete=DO_NOTHING,
    )
    first_name = CharField(_("first name"), max_length=30)
    middle_names = CharField(
        _("middle names"),
        blank=True,
        null=True,
        max_length=280,
        help_text=_("Comma separated list of middle names"),
    )
    last_name = CharField(max_length=150, verbose_name=_("last name"))
    research_experience_in_years = PositiveSmallIntegerField(
        _("research experience in years "), null=True, blank=True
    )
    org = ForeignKey(
        Organisation,
        blank=False,
        null=True,
        on_delete=SET_NULL,
        verbose_name=_("organisation"),
        related_name="applications",
    )
    organisation = CharField(max_length=200, verbose_name=_("organisation"))
    position = CharField(
        max_length=80,
        verbose_name=_("position"),
        help_text="position or role, e.g., student, postdoc, etc.",
    )
    postal_address = CharField(max_length=120, verbose_name=_("postal address"))
    city = CharField(max_length=80, verbose_name=_("city"))
    postcode = CharField(max_length=4, verbose_name=_("postcode"))
    daytime_phone = CharField(_("daytime phone number"), max_length=24, null=True, blank=True)
    mobile_phone = CharField(_("mobile phone number"), max_length=24, null=True, blank=True)
    email = EmailField(_("email address"), blank=True)
    is_bilingual = BooleanField(default=False, verbose_name=_("is bilingual"))
    summary = TextField(blank=True, null=True, verbose_name=_("summary"))
    file = PrivateFileField(
        blank=True,
        null=True,
        verbose_name=_("completed application form"),
        help_text=_("Please upload completed application form"),
        upload_subfolder=lambda instance: ["applications", hash_int(instance.round_id)],
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "pdf",
                    "odt",
                    "ott",
                    "oth",
                    "odm",
                    "doc",
                    "docx",
                    "docm",
                    "docb",
                ]
            )
        ],
    )
    converted_file = ForeignKey(
        ConvertedFile, null=True, blank=True, on_delete=SET_NULL, verbose_name=_("converted file")
    )
    photo_identity = PrivateFileField(
        null=True,
        blank=True,
        upload_subfolder=lambda instance: ["ids", hash_int(instance.submitted_by_id)],
        verbose_name=_("Photo Identity"),
        help_text=photo_identity_help_text,
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "jpg", "jpeg", "png"])],
    )
    presentation_url = URLField(
        null=True,
        blank=True,
        verbose_name=_("Presentation URL"),
        help_text=_("Please enter the URL where your presentation video can be viewed"),
    )

    state = StateField(default="new", verbose_name=_("state"))
    is_tac_accepted = BooleanField(
        default=False, verbose_name=_("I have read and accept the Terms and Conditions")
    )
    tac_accepted_at = MonitorField(
        monitor="state",
        when=["tac_accepted"],
        null=True,
        blank=True,
        default=None,
        verbose_name=_("Terms and Conditions accepted at"),
    )
    budget = PrivateFileField(
        blank=True,
        null=True,
        verbose_name=_("completed application budget spreadsheet"),
        help_text=_("Please upload completed application budget spreadsheet"),
        upload_subfolder=lambda instance: ["budgets", hash_int(instance.round_id)],
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "xls",
                    "xlw",
                    "xlt",
                    "xml",
                    "xlsx",
                    "xlsm",
                    "xltx",
                    "xltm",
                    "xlsb",
                    "csv",
                    "ctv",
                ]
            )
        ],
    )
    letter_of_support = ForeignKey(LetterOfSupport, on_delete=SET_NULL, blank=True, null=True)

    fors = ManyToManyField(
        FieldOfResearch,
        blank=True,
        through=ApplicationFor,
        related_name="applications",
        verbose_name="FoRs",
    )
    seos = ManyToManyField(
        SocioEconomicObjective,
        blank=True,
        through=ApplicationSeo,
        related_name="applications",
        verbose_name="SEOs",
    )
    keywords = ManyToManyField(
        Keyword,
        verbose_name=_("Keywords"),
        through=ApplicationKeyword,
        blank=True,
        related_name="applications",
    )
    vm_ecs = PositiveSmallIntegerField(
        "Indigenous Innovation",
        help_text=_(
            "Contributing to Economic Growth through Distinctive R&D. New Zealand needs "
            "its businesses and for-profit enterprises to perform at an optimum level and "
            "contribute to economic growth. This theme concerns the development of distinctive "
            "products, processes, systems and services from Māori knowledge, resources and people. "
            "Of particular interest are products that may be distinctive in the international marketplace."
        ),
        null=True,
        blank=True,
        default=0,
    )
    vm_ens = PositiveSmallIntegerField(
        "Taiao",
        help_text=_(
            "Achieving Environmental Sustainability through Iwi and Hapū relationships with land "
            "and sea. Like all communities, Māori communities aspire to live in sustainable communities "
            "dwelling in healthy environments. Much general environmental research is relevant to Māori. "
            "Distinctive environmental research arising in Māori communities relates to the expression of "
            "iwi and hapū knowledge, culture and experience – including Kaitiakitanga - in New Zealand land and seascapes."
        ),
        null=True,
        blank=True,
        default=0,
    )
    vm_hsw = PositiveSmallIntegerField(
        "Hauora/Oranga",
        help_text=_(
            "Improving Māori Health and Social Well-being. Distinctive challenges to Māori health "
            "and social well-being continue to arise within Māori communities disadvantaging them "
            "in relation to the general population. Research is needed to meet these ongoing needs."
        ),
        null=True,
        blank=True,
        default=0,
    )
    vm_ink = PositiveSmallIntegerField(
        "Mātauranga",
        help_text=_(
            "Exploring Indigenous Knowledge and RS&T. This exploratory theme aims to develop a body "
            "of knowledge, as a contribution to RS&T, at the interface between indigenous knowledge "
            "including mātauranga Māori – and research, science and technology."
        ),
        null=True,
        blank=True,
        default=0,
    )
    is_vm_na = BooleanField(_("Vision Mātauranga N/A"), default=False)
    vm_rationane = TextField(_("Rationale"), null=True, blank=True)

    toa_basic = PositiveSmallIntegerField(
        _("Basic"),
        help_text=_("Pure basic research"),
        null=True,
        blank=True,
        default=0,
    )
    toa_experimental = PositiveSmallIntegerField(
        _("Experimental"),
        help_text=_("Experimental development"),
        null=True,
        blank=True,
        default=0,
    )
    toa_applied = PositiveSmallIntegerField(
        _("Applied"),
        help_text=_("Applied research"),
        null=True,
        blank=True,
        default=0,
    )
    toa_strategic = PositiveSmallIntegerField(
        _("Strategic"),
        help_text=_("Strategic basic research"),
        null=True,
        blank=True,
        default=0,
    )

    @property
    def contract(self):
        """The latest contract."""
        return self.contracts.last()

    @property
    def thread_index(self):
        if n := Nomination.where(application=self).last():
            idx = n.id
        else:
            idx = self.id
        return base64.b64encode(f"{self.site_id}:{idx}".encode()).decode()

    @property
    def thread_topic(self):
        return self.number

    def is_applicant(self, user):
        """Is user the mail applicant or a member."""
        return (
            self.submitted_by == user
            or self.members.all().filter(Q(user=user) | Q(email=user.email)).exists()
        )

    def user_can_view(self, user):
        return (
            user.is_superuser
            or user.is_staff
            or self.is_applicant(user)
            or (
                hasattr(self, "nomination")
                and (self.nomination.nominator == user or self.nomination.user == user)
            )
            or (self.referees.filter(Q(user=user) | Q(email=user.email)).exists())
            or (self.round.panellists.filter(Q(user=user) | Q(email=user.email)).exists())
            or (self.org.research_offices.filter(user=user).exists())
        )

    def get_score_entries(self, user=None, panellist=None):
        if not panellist:
            panellist = Panellist.get(user=user, round=self.round)
        return self.round.criteria.filter(
            Q(scores__evaluation__panellist=panellist)
            | Q(scores__evaluation__panellist__isnull=True)
        ).prefetch_related("scores")

    def save(self, *args, **kwargs):
        if not self.application_title:
            self.application_title = self.round.title
        if not self.number:
            self.number = default_application_number(self)
        super().save(*args, **kwargs)

    @fsm_log
    @transition(field=state, source=["draft", "new", "tac_accepted"], target="draft")
    def save_draft(self, *args, **kwargs):
        pass

    @fsm_log
    @transition(field=state, source=["draft", "new", "tac_accepted"], target="draft")
    def accept_tac(self, *args, **kwargs):
        self.is_tac_accepted = True

    @fsm_log
    @transition(
        field=state, source=["new", "draft", "submitted", "tac_accepted"], target="submitted"
    )
    def submit(self, *args, **kwargs):
        request = kwargs.get("request")
        round = self.round
        site_id = settings.SITE_ID
        if round.budget_template and not (
            self.budget or self.documents.filter(~Q(file=""), document_type__role="B").exists()
        ):
            raise Exception(_("You must upload a budget spreadsheet to complete your application"))
        if not self.is_tac_accepted:
            if request and request.user:
                if self.submitted_by == request.user:
                    raise Exception(
                        _(
                            "You must accept the Prize's Terms and Conditions to submit an application"
                        )
                    )
                else:
                    raise Exception(
                        _("Your team lead has not yet accepted the Prize's Terms and Conditions")
                    )

        if (
            not self.file
            and not self.summary
            and not self.documents.filter(~Q(file=""), document_type__role="AF").exists()
        ):
            raise Exception(
                _(
                    "The application is not completed. Missing summary "
                    "and/or uploaded application form"
                )
            )
        if (
            round
            and round.pid_required
            and self.submitted_by.needs_identity_verification
            and not (self.photo_identity or IdentityVerification.where(application=self).exists())
        ):
            if self.photo_identity or IdentityVerification.where(application=self).exists():
                raise Exception(
                    _(
                        "Your identity has not been verified yet by the administration. "
                        "We will notify you when it is verified and you can complete your application."
                    )
                )
            raise Exception(
                _(
                    "Your identity has not been verified. "
                    "Please upload a scan of a document proving your identity."
                )
            )

        if site_id == 4:
            if (
                self.round.required_referees
                and self.referees.filter(~Q(state__in=["bounced", "opted_out"])).count()
                < self.round.required_referees
            ):
                raise Exception(
                    (_("You need to nominate at least %d referee(s)."))
                    % self.round.required_referees,
                )
        else:
            if self.referees.filter(
                Q(testified_at__isnull=True)
                | Q(user__isnull=True)
                | ~Q(testimonial__state="submitted"),
                ~Q(state__in=["submitted", "opted_out", "testified"]),
            ).exists():
                raise Exception(
                    _(
                        "Not all nominated referees have responded which prevents your submission. "
                        "Please either contact your referees, or replace them with one that will respond."
                    )
                )

            if (
                round.required_referees
                and self.referees.filter(state="testified").count() < round.required_referees
            ):
                raise Exception(
                    _("You need to procure reviews of your application from at least %d referees.")
                    % round.required_referees
                )

        if self.members.filter(Q(authorized_at__isnull=True) | Q(user__isnull=True)).exists():
            raise Exception(
                _(
                    "Not all team members have given their consent to be part of the team "
                    " which prevents your submission. "
                    "Please either contact your team's members, or modify the team membership"
                )
            )

        nomination = Nomination.where(application=self).last()
        nominator = nomination and nomination.nominator
        if site_id == 4 and nominator:
            url = request.build_absolute_uri(reverse("application", args=[str(self.id)]))
            send_mail(
                __("Application '%s' Submitted") % self,
                html_message=__(
                    "<p>Kia ora %(nominator)s</p>"
                    '<p>The nominee has submitted an application <a href="%(url)s">%(number)s: '
                    "%(title)s</a></p>"
                    "<p>Please reveiw and approve the submitted application.</p>"
                )
                % {
                    "nominator": nominator,
                    "url": url,
                    "number": self.number,
                    "title": self.application_title or round.title,
                },
                recipient_list=[nominator.full_email_address],
                cc=[
                    ro.user.full_email_address
                    for ro in ResearchOffice.where(org=self.org)
                    if ro.user != nominator
                ],
                fail_silently=False,
                request=request,
                reply_to=settings.DEFAULT_FROM_EMAIL,
                thread_index=self.thread_index,
                thread_topic=self.thread_topic,
            )
        elif round.notify_nominator and nominator:
            url = request.build_absolute_uri(reverse("application", args=[str(self.id)]))
            send_mail(
                __("Application '%s' Submitted") % self,
                html_message=__(
                    "<p>Kia ora %(nominator)s</p>"
                    '<p>The nominee has submitted an application <a href="%(url)s">%(number)s: '
                    '"%(title)s</a></p>'
                )
                % {
                    "nominator": nominator,
                    "url": url,
                    "number": self.number,
                    "title": self.application_title or round.title,
                },
                recipient_list=[nominator.full_email_address],
                fail_silently=False,
                request=request,
                reply_to=settings.DEFAULT_FROM_EMAIL,
                thread_index=self.thread_index,
                thread_topic=self.thread_topic,
            )

    @fsm_log
    @transition(field=state, source=["submitted", "approved"], target="approved")
    def approve(self, request=None, by=None, description=None, *args, **kwargs):
        resolution = kwargs.get("reason") or kwargs.get("resolution") or description
        if resolution and isinstance(description, str):
            resolution = resolution.strip()
        if not by and request:
            by = request.user
        # approved by the R.O.
        recipients = [self.submitted_by, *self.members.all()]
        url = request.build_absolute_uri(reverse("application", kwargs={"pk": self.id}))
        if ResearchOffice.where(user=by, org=self.org).exists():
            if not resolution:
                resolution = f'The Research Office approved has apprved the application "{self}"'
            subject = f'The Research Office approved has apprved your application "{self}"'
        else:
            if not resolution:
                resolution = f'The application "{self}" was approved by {by.full_email_address}.'
            subject = f'The application "{self}" was APPROVED'
        if not getattr(self, "_change_reason", None):
            self._change_reason = resolution

        params = {
            "user_display": ", ".join(r.full_name for r in recipients),
            "number": self.number,
            "user": by and by.full_name_with_email,
            "title": self.title or self.round.title,
            "url": url,
            "resolution": resolution,
        }
        send_mail(
            subject,
            (
                "Kia ora %(user_display)s\n\n"
                'Your application "%(number)s: %(title)s" was approved: %(url)s by %(user)s.\n\n'
                "Resolution:\n"
                "===========\n\n%(resolution)s\n\n"
            )
            % params,
            html_message=(
                "<p>Kia ora %(user_display)s</p>"
                '<p>Your application <a href="%(url)s">%(number)s: %(title)s</a> was approved.</p>'
                "<h3>Resolution</h3>\n"
                "<pre>%(resolution)s</pre>\n\n"
            )
            % params,
            recipient_list=[r.full_email_address for r in recipients],
            fail_silently=False,
            request=request,
            reply_to=settings.DEFAULT_FROM_EMAIL,
            thread_index=self.thread_index,
            thread_topic=self.thread_topic,
        )
        messages.success(
            request,
            "Successfully sent notificatio to %s"
            % ", ".join(u.full_name_with_email for u in recipients),
        )

    @fsm_log
    @transition(field=state, source=["submitted", "draft"], target="draft")
    def request_resubmission(self, request=None, by=None, description=None, *args, **kwargs):
        resolution = kwargs.get("reason") or kwargs.get("resolution") or description
        if resolution and isinstance(description, str):
            resolution = resolution.strip()
        if ResearchOffice.where(user=by, org=self.org).exists():
            if not resolution:
                resolution = (
                    "The Research Office approved has requested reviewing and "
                    f'resubmission of the application "{self}"'
                )
            subject = (
                "The Research Office approved has requested reviewing and "
                f'resubmission of your application "{self}"'
            )
        else:
            if not resolution:
                resolution = f'{by.full_email_address} requested reviewing and resubmission of your application "{self}".'
            subject = f'The application "{self}" requires your attention'
        if not getattr(self, "_change_reason", None):
            self._change_reason = resolution

        recipients = [self.submitted_by, *self.members.all()]
        url = request.build_absolute_uri(reverse("application-update", kwargs={"pk": self.id}))
        params = {
            "user_display": ", ".join(r.full_name for r in recipients),
            "number": self.number,
            "user": by and by.full_name_with_email,
            "title": self.title or self.round.title,
            "url": url,
            "resolution": resolution or "Requested for reviewing and re-drafting.",
        }
        send_mail(
            subject,
            __(
                "Kia ora %(user_display)s\n\n"
                "Please review your application %(number)s: %(title)s here %(url)s.\n\n"
                "Resolution:\n"
                "===========\n\n%(resolution)s\n\n"
            )
            % params,
            html_message=__(
                "<p>Kia ora %(user_display)s</p>"
                '<p>Please review your application <a href="%(url)s">%(number)s: %(title)s</a></p>'
                "<h3>Resolution</h3>\n"
                "<pre>%(resolution)s</pre>\n\n"
            )
            % params,
            recipient_list=[r.full_email_address for r in recipients],
            fail_silently=False,
            request=request,
            reply_to=settings.DEFAULT_FROM_EMAIL,
            thread_index=self.thread_index,
            thread_topic=self.thread_topic,
        )
        messages.success(
            request,
            "Successfully sent notificatio to review applicant to %s"
            % ", ".join(u.full_name_with_email for u in recipients),
        )

    @fsm_log
    @transition(field=state, source=["submitted", "draft"], target="cancelled")
    def cancel(self, request=None, by=None, description=None, *args, **kwargs):
        resolution = kwargs.get("reason") or kwargs.get("resolution") or description
        if resolution and isinstance(description, str):
            resolution = resolution.strip()
        if ResearchOffice.where(user=by, org=self.org).exists():
            if not resolution:
                resolution = f'The Research Office approved has cancelled the application "{self}"'
            subject = f'The Research Office approved has cancelled your application "{self}"'
        else:
            if not resolution:
                resolution = f'{by.full_email_address} cancelled your application "{self}".'
            subject = f'The application "{self}" has been CANCELLED'
        if not getattr(self, "_change_reason", None):
            self._change_reason = resolution

        recipients = [self.submitted_by, *self.members.all()]
        url = request.build_absolute_uri(reverse("application-update", kwargs={"pk": self.id}))
        params = {
            "user_display": ", ".join(r.full_name for r in recipients),
            "number": self.number,
            "user": by and by.full_name_with_email,
            "title": self.title or self.round.title,
            "url": url,
            "resolution": resolution or "Requested for reviewing and re-drafting.",
        }
        send_mail(
            subject,
            __(
                "Kia ora %(user_display)s\n\n"
                'Your application "%(number)s: %(title)s" was cancelled: %(url)s by %(user)s.\n\n'
                "Resolution:\n"
                "===========\n\n%(resolution)s\n\n"
            )
            % params,
            html_message=__(
                "<p>Kia ora %(user_display)s</p>"
                '<p>Your application <a href="%(url)s">%(number)s: %(title)s</a> was cancelled by %(user)s.</p>'
                "<h3>Resolution</h3>\n"
                "<pre>%(resolution)s</pre>\n\n"
            )
            % params,
            recipient_list=[r.full_email_address for r in recipients],
            fail_silently=False,
            request=request,
            reply_to=settings.DEFAULT_FROM_EMAIL,
            thread_index=self.thread_index,
            thread_topic=self.thread_topic,
        )
        messages.success(
            request,
            "Successfully sent notificatio to review applicant to %s"
            % ", ".join(u.full_name_with_email for u in recipients),
        )

    def __str__(self):
        if self.site_id == 4 and self.submitted_by:
            return f"{self.number}: {self.submitted_by.full_name}"
        title = self.application_title or self.round.title
        if self.number:
            title = f"{title} ({self.number})"
        return title

    @property
    def was_submitted(self):
        return self.state in ["submitted", "approved", "cancelled"]

    @property
    def deadline_days(self):
        return self.round.deadline_days

    @property
    def lead(self):
        value = f"{self.title} " if self.title else ""
        value += self.first_name or self.submitted_by and self.submitted_by.first_name
        if (
            middle_names := self.middle_names
            or self.submitted_by
            and self.submitted_by.middle_names
        ):
            value = f"{value} {middle_names}"
        return f"{value} {self.last_name or self.submitted_by and self.submitted_by.last_name}"

    @property
    def lead_with_email(self):
        return f"{self.lead} ({self.submitted_by and self.submitted_by.email or self.email})"

    def get_absolute_url(self):
        return reverse("application", args=[str(self.id)])

    @classmethod
    def user_applications(
        cls, user, state=None, round=None, select_related=True, include_inactive=False
    ):
        q = cls.objects.all()
        # q = cls.where(round__site=Site.objects.get_current())

        if select_related:
            prefetch_related_objects(q, "round")

        if state:
            if isinstance(state, (list, tuple)):
                q = q.filter(state__in=state)
            else:
                q = q.filter(state=state)
        else:
            q = q.filter(~Q(state="archived"))

        if round:
            q = q.filter(round=round)

        if not round and not ((user.is_staff or user.is_superuser) and include_inactive):
            q = q.filter(round__in=Scheme.objects.all().values("current_round"))

        if user.is_staff or user.is_superuser:
            return q

        f = (
            Q(members__user=user, members__state="authorized")
            | Q(referees__user=user)
            | Q(nomination__user=user)
            | Q(submitted_by=user)
            | Q(org__research_offices__user=user)
        )
        if Panellist.where(user=user).exists():
            f = f | Q(
                round__panellists__user=user,
                conflict_of_interests__panellist__user=user,
                conflict_of_interests__has_conflict=False,
                conflict_of_interests__has_conflict__isnull=False,
            )

        q = q.filter(f)
        q = q.distinct()

        return q

    @classmethod
    def user_application_count(cls, user, state=None, round=None):
        return cls.user_applications(
            user=user, state=state, round=round, select_related=False
        ).count()

    @classmethod
    def user_draft_applications(cls, user):
        return cls.user_applications(user, ["draft", "new"])

    def get_testimonials(self, has_testified=None):
        sql = (
            "SELECT DISTINCT tm.* FROM referee AS r "
            "JOIN application AS a "
            "  ON a.id = r.application_id "
            "LEFT JOIN testimonial AS tm ON r.id = tm.referee_id "
            "WHERE (r.application_id=%s OR a.id=%s) AND a.site_id=%s "
        )
        if has_testified:
            sql += " AND r.state='testified'"

        return Testimonial.objects.raw(sql, [self.id, self.id, self.current_site_id])

    def to_pdf(self, request=None, user=None, add_headers=None):
        """Create PDF file for export and return PdfFileMerger"""

        r = self.round
        if not user and request:
            user = request.user

        attachments = []
        cvs = []
        if self.file:
            attachments.append(
                (_("Application Form"), settings.PRIVATE_STORAGE_ROOT + "/" + str(self.pdf_file))
            )

        if (
            r.applicant_cv_required
            and not self.documents.filter(document_type__role="CV").exists()
            and (cv := self.cv or CurriculumVitae.last_user_cv(self.submitted_by))
        ):
            cvs.append(cv)
            attachments.append(
                (
                    f"{cv.full_name} {_('Curriculum Vitae')}",
                    settings.PRIVATE_STORAGE_ROOT + "/" + str(cv.pdf_file),
                    cv.title_page,
                )
            )

        if (
            user.is_superuser
            or user.is_staff
            or (
                self.site_id != 4
                and self.conflict_of_interests.filter(
                    panellist__user=user, has_conflict=False, has_conflict__isnull=False
                ).exists()
            )
        ):
            for n in Nomination.where(application=self, nominator__isnull=False):
                if n.file:
                    attachments.append(
                        (
                            _("Nomination Submitted By %s") % n.nominator.full_name,
                            settings.PRIVATE_STORAGE_ROOT + "/" + str(n.pdf_file),
                            n.title_page,
                        )
                    )

                    if (
                        r.nominator_cv_required
                        and (nominator_cv := n.cv or CurriculumVitae.last_user_cv(n.nominator))
                        and nominator_cv not in cvs
                    ):
                        cvs.append(nominator_cv)
                        attachments.append(
                            (
                                f"{nominator_cv.full_name} {_('Curriculum Vitae')}",
                                settings.PRIVATE_STORAGE_ROOT + "/" + str(nominator_cv.pdf_file),
                                nominator_cv.title_page,
                            )
                        )

            for t in self.get_testimonials():
                if t.file and t.referee:
                    attachments.append(
                        (
                            _("Testimonial Form Submitted By %s") % t.referee.full_name,
                            settings.PRIVATE_STORAGE_ROOT + "/" + str(t.pdf_file),
                            t.title_page,
                        )
                    )

                    if (
                        r.referee_cv_required
                        and (referee_cv := t.cv or CurriculumVitae.last_user_cv(t.referee.user))
                        and referee_cv not in cvs
                    ):
                        cvs.append(referee_cv)
                        attachments.append(
                            (
                                f"{referee_cv.full_name} {_('Curriculum Vitae')}",
                                settings.PRIVATE_STORAGE_ROOT + "/" + str(referee_cv.pdf_file),
                                referee_cv.title_page,
                            )
                        )
        if (
            self.round.letter_of_support_required
            and self.letter_of_support
            and self.letter_of_support.file
        ):
            attachments.append(
                (
                    _("Letter of Support"),
                    settings.PRIVATE_STORAGE_ROOT + "/" + str(self.letter_of_support.pdf_file),
                    self.letter_of_support.title_page,
                )
            )

        for d in self.documents.order_by("required_document__ordering"):
            attachments.append(
                (
                    f"{d.required_document}",
                    settings.PRIVATE_STORAGE_ROOT + "/" + str(d.pdf_file),
                    d.title_page,
                )
            )

        ssl._create_default_https_context = ssl._create_unverified_context

        merger = PdfFileMerger(strict=False)
        merger.addMetadata(
            {"/Title": f"{self.number}: {self.application_title or self.round.title}"}
        )
        merger.addMetadata({"/Author": self.lead_with_email})
        merger.addMetadata({"/Subject": self.round.title})
        merger.addMetadata({"/Number": self.number})
        # merger.addMetadata({"/Keywords": self.round.title})

        objects = []
        # if (
        #     request
        #     and (u := request.user)
        #     and not (self.submitted_by == u or self.members.all().filter(user=u).exists())
        # ):
        #     objects.extend(self.get_testimonials())
        site = Site.objects.get_current()
        domain = site.domain
        logo_url = logo_1_url = logo_2_url = None

        if (
            self.round.research_summary_required
            and (self.summary_en or self.summary_mi)
            and (
                (self.summary_en and ("<img" in self.summary_en or "<iframe" in self.summary_en))
                or (
                    self.summary_mi and ("<img" in self.summary_mi or "<iframe" in self.summary_mi)
                )
            )
        ):
            number = vignere.encode(self.number)
            url = reverse("application-exported-view", kwargs={"number": number})
            if request:
                summary_url = request.build_absolute_uri(url)
            else:
                summary_url = f"https://{urljoin(domain, url)}"
            html = HTML(summary_url)
        else:
            if domain == "international.royalsociety.org.nz":
                logo_path = os.path.join(
                    settings.STATIC_ROOT, f"images/{domain}/alt_logo_small.png"
                )
                if os.path.exists(logo_path):
                    logo_url = f"file://{logo_path}"

            elif self.site_id == 4:
                logo_path = os.path.join(settings.STATIC_ROOT, f"images/{domain}/MBIE_logo.jpg")
                if os.path.exists(logo_path):
                    logo_1_url = f"file://{logo_path}"

                logo_path = os.path.join(settings.STATIC_ROOT, f"images/{domain}/RS_logo.png")
                if os.path.exists(logo_path):
                    logo_2_url = f"file://{logo_path}"

            template = get_template("application-export.html")
            context = {
                "application": self,
                "objects": objects,
                "user": user,
                "site": site,
                "domain": domain,
                "logo": logo_url,
                "logo_1": logo_1_url,
                "logo_2": logo_2_url,
            }
            html = HTML(string=template.render(context))

        pdf_object = html.write_pdf(presentational_hints=True)
        # converting pdf bytes to stream which is required for pdf merger.
        pdf_stream = io.BytesIO(pdf_object)
        merger.append(
            pdf_stream,
            bookmark=(self.application_title or self.round.title),
            import_bookmarks=True,
        )
        for title, a, *rest in attachments:
            # merger.append(PdfFileReader(a, "rb"), bookmark=title, import_bookmarks=True)
            if self.site_id != 4 and rest and (title_page := rest[0]):
                template = get_template("application-export-attachment-title-page.html")
                html = HTML(
                    string=template.render(
                        {
                            "application": self,
                            "title_page": title_page,
                            "title": title,
                            # "objects": objects,
                            "user": user,
                            "site": site,
                            "domain": domain,
                            "logo": logo_url,
                            "logo_1": logo_1_url,
                            "logo_2": logo_2_url,
                        }
                    )
                )
                pdf_object = html.write_pdf(presentational_hints=True)
                # converting pdf bytes to stream which is required for pdf merger.
                pdf_stream = io.BytesIO(pdf_object)
                merger.append(
                    pdf_stream,
                    # bookmark=(self.application_title or self.round.title),
                    import_bookmarks=True,
                )

            merger.append(a, bookmark=title, import_bookmarks=True)

        if add_headers or self.site_id == 4:
            template = get_template("headers.html")
            html = HTML(
                string=template.render({"page_count": len(merger.pages), "application": self})
            )
            header_file = PdfFileReader(io.BytesIO(html.write_pdf(presentational_hints=True)))
            for dp, hp in zip(merger.pages, header_file.pages):
                dp.pagedata.mergePage(hp)

        return merger

    class Meta:
        db_table = "application"


class ApplicationNumber(Model):
    """Historical or alternative application numbers."""

    application = ForeignKey(Application, on_delete=CASCADE, related_name="numbers")
    number = CharField(
        _("number"), max_length=24, null=True, blank=True, editable=False, unique=True
    )
    is_active = BooleanField(default=False)
    history = HistoricalRecords(table_name="application_number_history")

    class Meta:
        db_table = "application_number"


class EthicsStatement(PdfFileMixin, Model):
    application = OneToOneField(Application, on_delete=CASCADE, related_name="ethics_statement")
    file = PrivateFileField(
        verbose_name=_("ethics statement"),
        help_text=_("Please upload human or animal ethics statement."),
        upload_subfolder=lambda instance: ["statements", hash_int(instance.application_id)],
        blank=True,
        null=True,
    )
    not_relevant = BooleanField(default=False, verbose_name=_("Not Applicable"))
    comment = TextField(_("Comment"), max_length=1000, null=True, blank=True)

    class Meta:
        db_table = "ethics_statement"


MEMBER_STATES = Choices(
    ("accepted", _("accepted")),
    ("authorized", _("authorized")),
    ("bounced", _("bounced")),
    ("new", _("new")),
    ("opted_out", _("opted out")),
    ("sent", _("sent")),
    (None, None),
)


class MemberMixin:
    """Workaround for simple history."""

    STATES = MEMBER_STATES


class Member(PersonMixin, MemberMixin, Model):
    """Application team member."""

    objects = ApplicationSiteManager()
    all_objects = Manager()

    application = ForeignKey(Application, on_delete=CASCADE, related_name="members")
    email = EmailField(max_length=120)
    first_name = CharField(max_length=30, null=True, blank=True)
    middle_names = CharField(
        _("middle names"),
        blank=True,
        null=True,
        max_length=280,
        help_text=_("Comma separated list of middle names"),
    )
    last_name = CharField(max_length=150, null=True, blank=True)
    role = CharField(max_length=200, null=True, blank=True)
    # has_authorized = BooleanField(null=True, blank=True)
    user = ForeignKey(User, null=True, blank=True, on_delete=SET_NULL)
    state = StateField(null=True, blank=True, default="new")
    state_changed_at = MonitorField(monitor="state", null=True, blank=True, default=None)
    authorized_at = MonitorField(
        monitor="state", when=["authorized"], null=True, blank=True, default=None
    )

    @property
    def thread_index(self):
        if self.application_id and (n := Nomination.where(application=self.application_id)):
            idx = n.id
        else:
            idx = self.application_id
        site_id = self.application and self.application.site_id or settings.SITE_ID
        return base64.b64encode(f"{site_id}:{idx}".encode()).decode()

    @property
    def thread_topic(self):
        return self.application and self.application.number

    @property
    def mail_log_error(self):
        if ml := MailLog.where(invitation__member=self, error__isnull=False).last():
            return ml.error

    @property
    def has_authorized(self):
        if self.state == "authorized":
            return True
        elif self.state == "opted_out":
            return False

    def __getattribute__(self, name):
        if name.startswith("fte_"):
            i = int(name.split("_")[1])
            if me := self.efforts.filter(period=i).first():
                return me.fte
            return None
        return super().__getattribute__(name)

    def clean(self):
        super().clean()
        if not (application := getattr(self, "application", None)):
            raise ValidationError(_("Missing application"))
        member_id = getattr(self, "id", None)
        q = application.members.filter(email=self.email)
        if member_id:
            q = q.filter(~Q(id=member_id))
        if q.exists():
            raise ValidationError(
                _("Team member with the email address %(email)s was alrady added"),
                params={"email": self.email},
            )

    @fsm_log
    @transition(field=state, source=["new", "sent"], target="accepted")
    def accept(self, *args, **kwargs):
        pass

    @fsm_log
    @transition(field=state, source=["*"], target="authorized")
    def authorize(self, *args, **kwargs):
        # self.has_authorized = True
        request = get_request(*args, **kwargs)
        for i in Invitation.where(~Q(state="accepted"), member=self):
            i.accept(request)
            i.save()

        if recipient_email := (
            self.application.submitted_by
            and self.application.submitted_by.email
            or self.application.email
        ):
            send_mail(
                __("A team member accepted your invitation"),
                __("Your team member %s has accepted your invitation.") % self,
                recipient_list=[recipient_email],
                fail_silently=False,
                request=request,
                reply_to=self.full_email_address,
                thread_index=self.thread_index,
                thread_topic=self.thread_topic,
            )

    @fsm_log
    @transition(field=state, source=["*"], target="bounced")
    def bounce(self, *args, **kwargs):
        pass

    @fsm_log
    @transition(field=state, source=["*"], target="opted_out")
    def opt_out(self, *args, **kwargs):
        # self.has_authorized = False
        request = get_request(*args, **kwargs)
        if self.application.submitted_by.email:
            send_mail(
                __("A team member opted out of application"),
                __("Your team member %s has opted out of application") % self,
                recipient_list=[self.application.submitted_by.email],
                fail_silently=False,
                request=request,
                reply_to=self.full_email_address,
                thread_index=self.thread_index,
                thread_topic=self.thread_topic,
            )

    @fsm_log
    @transition(field=state, source=["*"], target="sent")
    def send(self, *args, **kwargs):
        pass

    def __str__(self):
        return self.full_name_with_email

    @classmethod
    def outstanding_requests(cls, user):
        return cls.objects.raw(
            "SELECT DISTINCT m.* FROM member AS m JOIN account_emailaddress AS ae ON ae.email = m.email "
            "WHERE (m.user_id=%s OR ae.user_id=%s) "
            "  AND NOT (m.state IS NULL OR m.state IN ('authorized', 'opted_out'))",
            [user.id, user.id],
        )

    class Meta:
        db_table = "member"
        unique_together = ["application", "email"]


simple_history.register(
    Member, inherit=True, table_name="member_history", bases=[MemberMixin, Model]
)


class MemberEffort(Model):
    member = ForeignKey(Member, on_delete=CASCADE, related_name="efforts")
    period = PositiveSmallIntegerField()
    fte = DecimalField(
        _("FTE"), help_text=_("Full-Time Equivalent"), max_digits=3, decimal_places=2
    )

    history = HistoricalRecords(table_name="member_effort_history")

    class Meta:
        db_table = "member_effort"
        unique_together = ["member", "period"]


REFEREE_STATES = Choices(
    ("accepted", _("accepted")),
    ("bounced", _("bounced")),
    ("new", _("new")),
    ("opted_out", _("opted out")),
    ("sent", _("sent")),
    ("testified", _("testified")),
    (None, None),
)


class RefereeMixin:
    """Workaround for simple history."""

    STATES = REFEREE_STATES


class Referee(RefereeMixin, PersonMixin, Model):
    """Application referee."""

    objects = ApplicationSiteManager()
    all_objects = Manager()

    application = ForeignKey(Application, on_delete=CASCADE, related_name="referees")
    email = EmailField(verbose_name=_("email"), max_length=120)
    first_name = CharField(_("first name"), max_length=30, null=True, blank=True)
    middle_names = CharField(
        _("middle names"),
        blank=True,
        null=True,
        max_length=280,
        help_text=_("Comma separated list of middle names"),
    )
    last_name = CharField(_("last name"), max_length=150, null=True, blank=True)
    # has_testifed = BooleanField(null=True, blank=True)
    user = ForeignKey(User, null=True, blank=True, on_delete=SET_NULL)
    state = StateField(_("state"), null=True, blank=True, default="new")
    state_changed_at = MonitorField(monitor="state", null=True, blank=True, default=None)
    testified_at = MonitorField(
        monitor="state", when=["testified"], null=True, blank=True, default=None
    )
    survey_token_id = PositiveIntegerField(null=True, blank=True, default=None)
    survey_token = CharField(max_length=100, null=True, blank=True, default=None)
    survey_invitation_sent_at = DateTimeField(null=True, blank=True, default=None)
    survey_completed_at = DateTimeField(null=True, blank=True, default=None)

    @property
    def mail_log_error(self):
        if ml := MailLog.where(invitation__referee=self, error__isnull=False).last():
            return ml.error

    @property
    def has_testified(self):
        return self.state == "testified"

    def clean(self):
        super().clean()
        if not (application := getattr(self, "application", None)):
            raise ValidationError(_("Missing application"))
        referee_id = getattr(self, "id", None)
        if application and application.pk:
            q = application.referees.filter(email=self.email)
            if referee_id:
                q = q.filter(~Q(id=referee_id))
            if q.exists():
                raise ValidationError(
                    _("Referee with the email address %(email)s was alrady added"),
                    params={"email": self.email},
                )

    @fsm_log
    @transition(field=state, source=["*"], target="accepted")
    def accept(self, *args, **kwargs):
        pass

    @property
    @lru_cache(1)
    def survey_api(self):
        api_url = self.application.round.survey_api_url
        api = LimeSurvey(url=api_url, username=settings.LIMESURVEY_API_USERNAME)
        api.open(password=settings.LIMESURVEY_API_PASSWORD)
        return api

    def add_to_survey(self, api=None):
        # Inviation to participate in the survey:
        if survey_id := self.application.round.survey_id:
            u = self.user
            if not u and (ea := EmailAddress.objects.filter(email=self.email).first()):
                u = ea.user
            first_name = self.first_name or u and u.first_name or ""
            last_name = self.last_name or u and u.last_name or ""

            if not api:
                api = self.survey_api
            if not self.survey_token:
                participant = {"email": self.email.lower()}
                if first_name:
                    participant["firstname"] = self.first_name
                if last_name:
                    participant["lastname"] = self.last_name
                participant["token"] = base64.urlsafe_b64encode(
                    hashlib.shake_256(
                        bytes(int(time.time()) if settings.DEBUG else self.id)
                    ).digest(21)
                ).decode()
                resp = api.token.add_participants(survey_id, [participant], create_token_key=False)
                if not isinstance(resp, list):
                    limesurvey_status = resp.get("state")
                    raise Exception(
                        _(
                            "Failed to add the referee: %s. Please constact a portal administration."
                        )
                        % limesurvey_status
                    )

                for r in resp:
                    if r.get("email") == self.email.lower():
                        self.survey_token_id = r.get("tid")
                        self.survey_token = r.get("token")
                        properties = api.token.get_participant_properties(
                            survey_id, self.survey_token_id
                        )
                        if (
                            int(properties.get("tid")) != int(self.survey_token_id)
                            or properties.get("token") != self.survey_token
                        ):
                            raise Exception(
                                f"Failed to sync with LimeSurveyt of {self}", resp, properties
                            )

    def invite_to_survey(self, api=None):
        if survey_id := self.application.round.survey_id:
            if not api:
                api = self.survey_api
            if not self.survey_token_id:
                self.add_to_survey(api)

            if self.survey_token_id:
                api = self.survey_api
                # resp = api.token.invite_participants(survey_id, [self.survey_token_id,])
                resp = api.query(
                    method="invite_participants",
                    params=OrderedDict(
                        [
                            ("sSessionKey", api.session_key),
                            ("iSurveyID", survey_id),
                            ("aTokenIds", [self.survey_token_id]),
                            ("bEmail", True),
                            ("continueOnError", True),
                        ]
                    ),
                )
                resp_type = type(resp)

                if resp_type is dict and "status" in resp:
                    status = resp["status"].lower()
                    error_messages = [
                        "invalid session key",
                        "error: invalid survey id",
                        "error: no token table",
                        "error: no candidate tokens",
                        "no permission",
                    ]
                    for message in error_messages:
                        if status == message:
                            # raise LimeSurveyError(method, status)
                            capture_message(
                                f"Failed to invite surevey participant - referee {self}: {status}",
                                level="error",
                            )
                            break
                    else:
                        self.survey_invitation_sent_at = datetime.now()

    @property
    def survey_url(self):
        if (
            self.application
            and (r := self.application.round)
            and (survey_id := r.survey_id)
            and (token := self.survey_token)
            and (server_url := r.survey_server_url)
        ):
            if server_url.endswith("/"):
                return f"{server_url}{survey_id}?token={token}"
            return f"{server_url}/{survey_id}?token={token}"

    @fsm_log
    @transition(field=state, source=["*"], target="testified")
    def testify(self, *args, request=None, by=None, description=True, commit=True, **kwargs):
        for i in Invitation.where(~Q(state="accepted"), referee=self):
            if not by:
                if i.user:
                    by = i.user
                elif request:
                    by = request.user
            if by and not self.user:
                self.user = by
            i.accept(
                *args, request=request, by=by, description=description, commit=False, **kwargs
            )
            if commit:
                i.save()

    @fsm_log
    @transition(field=state, source=["*"], target="bounced")
    def bounce(self, *args, **kwargs):
        pass

    @fsm_log
    @transition(field=state, source=["*"], target="opted_out")
    def opt_out(self, *args, **kwargs):
        # self.has_testifed = False
        pass

    @fsm_log
    @transition(field=state, source=["*"], target="sent")
    def send(self, *args, **kwargs):
        pass

    def __str__(self):
        return f"{self.application.number}: {self.user or self.email}"

    @classmethod
    def outstanding_requests(cls, user):
        return cls.objects.raw(
            "SELECT DISTINCT r.*, tm.id AS testimonial_id "
            "FROM referee AS r JOIN account_emailaddress AS ae ON "
            "ae.email = r.email LEFT JOIN testimonial AS tm ON r.id = tm.referee_id "
            "WHERE (r.user_id=%s OR ae.user_id=%s) AND r.state NOT IN ('testified', 'opted_out')",
            [user.id, user.id],
        )

    class Meta:
        db_table = "referee"
        unique_together = ["application", "email"]


simple_history.register(
    Referee, inherit=True, table_name="referee_history", bases=[RefereeMixin, Model]
)


PANELLIST_STATES = Choices(
    (None, None),
    ("new", _("new")),
    ("sent", _("sent")),
    ("accepted", _("accepted")),
    ("bounced", _("bounced")),
)


class PanellistMixin:
    """Workaround for simple history."""

    STATES = PANELLIST_STATES


class Panellist(PanellistMixin, PersonMixin, Model):
    """Round Panellist."""

    site = ForeignKey(Site, on_delete=PROTECT, default=Model.get_current_site_id)
    objects = CurrentSiteManager()
    all_objects = Manager()

    state = StateField(null=True, blank=True, default="new")
    round = ForeignKey("Round", editable=True, on_delete=DO_NOTHING, related_name="panellists")
    email = EmailField(max_length=120)
    first_name = CharField(max_length=30, null=True, blank=True)
    middle_names = CharField(
        _("middle names"),
        blank=True,
        null=True,
        max_length=280,
        help_text=_("Comma separated list of middle names"),
    )
    last_name = CharField(max_length=150, null=True, blank=True)
    # person = models.ForeignKey(Person, blank=True, null=True, on_delete=models.CASCADE, related_name="+")
    user = ForeignKey(User, null=True, blank=True, on_delete=SET_NULL)
    state_changed_at = MonitorField(monitor="state", null=True, blank=True, default=None)

    panel = ForeignKey(
        "Panel", blank=True, null=True, on_delete=SET_NULL, related_name="panellists"
    )

    role = CharField(
        max_length=20,
        blank=True,
        null=True,
        choices=Choices(
            ("CHAIR", _("Chair")),
            ("COCONVENOR", _("Co-convenor")),
            ("COMMITTEE", _("Committee")),
            ("CONVENOR", _("Convenor")),
            ("PANELLIST", _("Panellist")),
        ),
    )
    elected_on = DateField(blank=True, null=True)
    expires_on = DateField(blank=True, null=True)
    is_active = BooleanField(_("is active"), default=True)
    # fund = models.CharField(max_length=2, blank=True, null=True)
    ## fund = ForeignKey("Fund", on_delete=SET_NULL, blank=True, null=True)
    ## fund_type = CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.role}: {self.person}"

    @property
    def mail_log_error(self):
        if ml := MailLog.where(invitation__panellist=self, error__isnull=False).last():
            return ml.error

    # TODO: refactor and move to a common mixin
    def get_or_create_invitation(self, by=None):
        u = self.user or User.objects.filter(email=self.email).first()
        if not u and (ea := EmailAddress.objects.filter(email=self.email).first()):
            u = ea.user
        first_name = self.first_name or u and u.first_name or ""
        last_name = self.last_name or u and u.last_name or ""
        middle_names = self.middle_names or ""  ## or u and u.middle_names or ""

        if hasattr(self, "invitation"):
            i = self.invitation
            if self.email != i.email:
                i.email = self.email
                i.first_name = first_name
                i.middle_names = middle_names
                i.last_name = last_name
                i.sent_at = None
                # i.state = "submitted"
                i.submit()
                i.save()
            return (i, False)
        else:
            return Invitation.get_or_create(
                type=INVITATION_TYPES.P,
                panellist=self,
                email=self.email,
                defaults=dict(
                    panellist=self,
                    round=self.round,
                    first_name=first_name,
                    middle_names=middle_names,
                    last_name=last_name,
                    inviter=by,
                ),
            )

    def has_all_coi_statements_submitted_for(self, round_id=None):
        if round_id and (r := Round.get(round_id)):
            return not r.applications.filter(
                ~Q(state__in=["new", "draft", "archived"]),
                ~Q(
                    id__in=self.conflict_of_interests.filter(has_conflict__isnull=False).values(
                        "application_id"
                    )
                ),
            ).exists()

        return not self.round.applications.filter(
            ~Q(state__in=["new", "draft", "archived"]),
            ~Q(
                id__in=self.conflict_of_interests.filter(has_conflict__isnull=False).values(
                    "application_id"
                )
            ),
        ).exists()

    @property
    def has_all_coi_statements_submitted(self):
        return self.has_all_coi_statements_submitted_for()

    @fsm_log
    @transition(field=state, source=["new", "sent", "bounced"], target="accepted")
    def accept(self, *args, **kwargs):
        pass

    @fsm_log
    @transition(field=state, source=["*"], target="bounced")
    def bounce(self, *args, **kwargs):
        pass

    @fsm_log
    @transition(field=state, source=["*"], target="sent")
    def send(self, *args, **kwargs):
        pass

    def __str__(self):
        return str(self.user or self.email)

    @classmethod
    def outstanding_requests(cls, user):
        q = cls.objects.raw(
            "SELECT DISTINCT p.* FROM panellist AS p JOIN account_emailaddress AS ae ON ae.email = p.email "
            "JOIN application AS a ON a.round_id = p.round_id AND a.state NOT IN ('new', 'draft', 'archived') "
            "JOIN scheme AS s ON s.current_round_id=p.round_id "
            "LEFT JOIN conflict_of_interest AS coi ON coi.application_id = a.id AND coi.panellist_id = p.id "
            "LEFT JOIN evaluation AS e ON e.application_id = a.id AND e.panellist_id = p.id "
            "WHERE (p.user_id=%s OR ae.user_id=%s) "
            "  AND (coi.has_conflict IS NULL OR NOT coi.has_conflict) "
            "  AND (e.state IS NULL OR e.state <> 'submitted')"
            "  AND a.site_id=%s",
            [user.id, user.id, cls.get_current_site_id()],
        )
        prefetch_related_objects(q, "round")
        return q

    class Meta:
        db_table = "panellist"
        unique_together = ["round", "email"]
        # unique_together = (("panel", "person", "elected_on", "expires_on"),)


simple_history.register(
    Panellist, inherit=True, table_name="panellist_history", bases=[PanellistMixin, Model]
)


class ConflictOfInterest(Model):
    panellist = ForeignKey(
        Panellist, null=True, blank=True, on_delete=CASCADE, related_name="conflict_of_interests"
    )
    application = ForeignKey(Application, on_delete=CASCADE, related_name="conflict_of_interests")
    has_conflict = BooleanField(null=True, blank=True, default=True)
    comment = TextField(_("Comment"), max_length=1000, null=True, blank=True)
    statement_given_at = DateTimeField(auto_now_add=True, null=True, blank=True)

    def __str__(self):
        return _("Statement of Conflict of Interest of %s") % self.panellist

    class Meta:
        db_table = "conflict_of_interest"
        verbose_name_plural = _("conflicts of interest")


def get_unique_invitation_token():
    while True:
        token = secrets.token_urlsafe(8)
        if not Invitation.objects.filter(token=token).exists():
            return token


INVITATION_TYPES = Choices(
    ("A", _("apply")),
    ("J", _("join")),
    ("R", _("testify")),
    ("T", _("authorize")),
    ("P", _("panellist")),
)

INVITATION_STATES = Choices(
    ("accepted", _("accepted")),
    ("autoreplied", _("autoreplied")),
    ("bounced", _("bounced")),
    ("draft", _("draft")),
    ("expired", _("expired")),
    ("read", _("read")),
    ("revoked", _("revoked")),
    ("sent", _("sent")),
    ("submitted", _("submitted")),
)


class InvitationMixin:
    """Workaround for simple history."""

    STATES = INVITATION_STATES


class Invitation(InvitationMixin, PersonMixin, Model):
    site = ForeignKey(Site, on_delete=PROTECT, default=Model.get_current_site_id)
    objects = CurrentSiteManager()
    all_objects = Manager()

    token = CharField(max_length=42, default=get_unique_invitation_token, unique=True)
    url = CharField(max_length=200, null=True, blank=True)
    inviter = ForeignKey(User, null=True, blank=True, on_delete=SET_NULL)
    type = CharField(max_length=1, default=INVITATION_TYPES.J, choices=INVITATION_TYPES)
    email = EmailField(_("email address"))
    first_name = CharField(_("first name"), max_length=30, null=True, blank=True)
    middle_names = CharField(
        _("middle names"),
        blank=True,
        null=True,
        max_length=280,
        help_text=_("Comma separated list of middle names"),
    )
    last_name = CharField(_("last name"), max_length=150, null=True, blank=True)
    organisation = CharField(
        _("organisation"), max_length=200, null=True, blank=True
    )  # entered name
    org = ForeignKey(
        Organisation, verbose_name=_("organisation"), on_delete=SET_NULL, null=True, blank=True
    )  # the org matched with the entered name
    application = ForeignKey(
        Application, null=True, blank=True, on_delete=SET_NULL, related_name="invitations"
    )
    nomination = ForeignKey(
        "Nomination", null=True, blank=True, on_delete=SET_NULL, related_name="invitations"
    )
    member = OneToOneField(
        Member, null=True, blank=True, on_delete=SET_NULL, related_name="invitation"
    )
    referee = OneToOneField(
        Referee, null=True, blank=True, on_delete=SET_NULL, related_name="invitation"
    )
    panellist = OneToOneField(
        Panellist, null=True, blank=True, on_delete=SET_NULL, related_name="invitation"
    )
    round = ForeignKey(
        "Round", null=True, blank=True, on_delete=SET_NULL, related_name="invitations"
    )
    state = StateField(default="draft")
    state_changed_at = MonitorField(monitor="state", null=True, blank=True, default=None)
    submitted_at = MonitorField(
        monitor="state", when=["submitted"], null=True, blank=True, default=None
    )
    sent_at = MonitorField(monitor="state", when=["sent"], null=True, blank=True, default=None)
    accepted_at = MonitorField(
        monitor="state", when=["accepted"], null=True, blank=True, default=None
    )
    read_at = MonitorField(monitor="state", when=["read"], null=True, blank=True, default=None)
    expired_at = MonitorField(
        monitor="state", when=["expired"], null=True, blank=True, default=None
    )
    bounced_at = MonitorField(
        monitor="state", when=["bounced"], null=True, blank=True, default=None
    )

    # TODO: need to figure out how to propagate STATUS to the historical rec model:
    # history = HistoricalRecords(table_name="invitation_history")

    @property
    def thread_index(self):
        if self.nomination_id:
            idx = self.nomination_id
        elif self.application_id:
            if n := Nomination.where(application=self.application_id).first():
                idx = n.id
            else:
                idx = self.application_id
        elif self.member_id:
            if n := Nomination.where(application__members=self.member_id).first():
                idx = n.id
            else:
                idx = self.member.application_id
        elif self.referee_id:
            if n := Nomination.where(application__referees=self.referee_id).first():
                idx = n.id
            else:
                idx = self.referee.application_id
        elif self.panellist_id:
            idx = self.panellist.round_id
        else:
            idx = self.id
        return base64.b64encode(f"{self.site_id}:{idx}".encode()).decode()

    @property
    def thread_topic(self):
        if self.application_id and (a := self.application):
            return a.number
        elif self.nomination_id:
            if a := Application.all_objects.filter(nomination=self.nomination_id).last():
                return a.number
            else:
                return f"{self.nomination.round}"
        elif self.member_id and (
            a := Application.all_objects.filter(member=self.member_id).last()
        ):
            return a.number
        elif self.referee_id and (
            a := Application.all_objects.filter(referee=self.referee_id).last()
        ):
            return a.number
        elif self.panellist_id:
            return f"{self.panellist.round}"

    @property
    def handler_url(self):
        if self.state == "revoked":
            return reverse("index")
        elif self.type == INVITATION_TYPES.A and self.nomination_id:
            if a := self.nomination.application:
                if a.state != "submitted":
                    return reverse("application-update", kwargs=dict(pk=a.id))
                else:
                    return reverse("application", kwargs=dict(pk=a.id))
            return reverse("nomination-detail", kwargs=dict(pk=self.nomination_id))
        elif self.type == INVITATION_TYPES.T and self.member:
            return reverse("application", kwargs=dict(pk=self.member.application_id))
        elif self.type == INVITATION_TYPES.R and (r := self.referee):
            if r.survey_token_id and not r.survey_completed_at:
                return reverse("application", kwargs=dict(pk=r.application_id))
            if t := Testimonial.where(referee=r).first():
                return reverse("review-update", kwargs=dict(pk=t.id))
            return reverse("application", kwargs=dict(pk=r.application_id))
        elif self.type == INVITATION_TYPES.P and (p := self.panellist):
            if p.round_id:
                if p.has_all_coi_statements_submitted or p.round.has_online_scoring:
                    return reverse("round-application-list", kwargs=dict(round_id=p.round.id))
                return reverse("round-coi", kwargs=dict(round=p.round.id))
        elif self.type in INVITATION_TYPES:
            return reverse("index")
        return self.token and reverse("onboard-with-token", kwargs=dict(token=self.token))

    @classmethod
    def user_inviations(cls, user):
        """All invitations sent to the user"""
        return cls.where(
            Q(email=user.email)
            | Q(nomination__user=user)
            | Q(member__user=user)
            | Q(referee__user=user)
            | Q(panellist__user=user)
            | Q(email__in=user.emailaddress_set.values("email"))
        ).distinct()

    @fsm_log
    @transition(
        field=state,
        source=["*"],
        target="submitted",
    )
    def submit(self, *args, **kwargs):
        pass

    @fsm_log
    @transition(
        field=state,
        source=["*"],
        target="revoked",
    )
    def revoke(self, request=None, by=None, *args, **kwargs):
        site = Site.objects.get_current()
        site_name = site.name

        subject = __("The invitation sent from %(site_name)s portal was revoked") % {
            "site_name": site_name
        }
        html_body = __(
            "<p>Tēnā koe,</p>"
            "<p>The invitation previouly sent from %(site_name)s portal was revoked.</p>"
        ) % {"site_name": site_name}

        send_mail(
            subject,
            html_message=html_body,
            recipient_list=[self.email],
            fail_silently=False,
            request=request,
            reply_to=by.email if by else settings.DEFAULT_FROM_EMAIL,
            invitation=self,
            thread_index=self.thread_index,
            thread_topic=self.thread_topic,
        )

        self.referee = None
        self.member = None
        self.panellist = None

    @fsm_log
    @transition(
        field=state,
        source=["draft", "sent", "submitted", "bounced", "autoreplied"],
        target="sent",
    )
    def send(self, request=None, by=None, *args, **kwargs):
        if not by:
            by = request.user if request else self.inviter
        url = reverse("onboard-with-token", kwargs=dict(token=self.token))
        site = (
            self.site or request and getattr(request, "site", None) or Site.objects.get_current()
        )
        site_id, site_name = site.id, site.name
        if request:
            # url = request.build_absolute_uri(url)
            url = request.build_absolute_uri(url)
        else:
            url = f"https://{urljoin(site.domain, url)}"
        self.url = url

        # TODO: handle the rest of types
        if self.type == INVITATION_TYPES.T:
            subject = __("You are invited to be part of a %(site_name)s application") % {
                "site_name": site_name
            }
            body = __(
                "Tēnā koe,\n\n"
                "You have been invited to join %(inviter)s's team for their %(site_name)s application. "
                "\n\nTo review this invitation, please follow the link: %(url)s\n\n"
                "Ngā mihi"
            ) % dict(inviter=by.full_name, url=url, site_name=site_name)
            html_body = __(
                "Tēnā koe,<br><br>You have been invited to join %(inviter)s's team for their "
                "%(site_name)s application.<br><br>"
                "To review this invitation, please follow the link: <a href='%(url)s'>%(url)s</a><br>"
            ) % dict(inviter=by.full_name, url=url, site_name=site_name)
        elif self.type == INVITATION_TYPES.R:
            referee = self.referee
            contact_email = site_contact_email(site_id)
            subject = __("You are invited as a referee for a %(site_name)s application") % {
                "site_name": site_name
            }
            if survey_url := (
                referee.user
                and referee.application.round.survey_id
                and referee.survey_token_id
                and reverse("survey-referee", kwargs=dict(referee_id=self.referee_id))
            ):
                if request:
                    survey_url = request.build_absolute_uri(survey_url)
                else:
                    survey_url = f"https://{urljoin(site.domain, survey_url)}"
                survey_url = f"{survey_url}?token={self.token}"

            body = (
                (
                    "Tēnā koe,\n\n"
                    "You have been invited to be a referee for %(inviter)s's application to "
                    "the %(application)s. \n\n"
                    "We strongly advise clicking on the Referee Guidelines before clicking  "
                    "on the portal link below: %(guidelines)s\n\n"
                    "Please fill out the referee report at %(survey_url)s.\n\n"
                    "If you have any further questions, please contact: %(contact_email)s\n\n"
                    "Ngā mihi nui"
                )
                if survey_url
                else (
                    "Tēnā koe,\n\n"
                    "You have been invited to be a referee for %(inviter)s's application to "
                    "the %(application)s. \n\n"
                    "We strongly advise clicking on the Referee Guidelines before clicking  "
                    "on the portal link below: %(guidelines)s\n\n"
                    "To review this invitation, please follow the link: %(url)s\n\n"
                    "If you have any further questions, please contact: %(contact_email)s\n\n"
                    "Ngā mihi nui"
                )
            ) % dict(
                inviter=by.full_name,
                main_applicant=self.referee.application.submitted_by.full_name,
                url=url,
                survey_url=survey_url,
                site_name=site_name,
                application=self.referee.application,
                guidelines=self.referee.application.round.get_guidelines(),
                contact_email=contact_email,
            )
            html_body = (
                (
                    "<p>Tēnā koe,</p><p>You have been invited by %(inviter)s to be a referee "
                    "for %(main_applicant)s's application to the "
                    "%(application)s application.</p>"
                    "<p>We strongly advise clicking on the Referee Guidelines <strong>before</strong> clicking  "
                    "on the portal link below.</p>"
                    "<p><a href='%(guidelines)s'>Referee Guidelines</a></p>"
                    "<p>Please fill out the <strong>referee report</strong> at \n"
                    "<a href='%(survey_url)s'>%(survey_url)s</a>.</p>\n"
                    "<p>If you have any further questions, please contact "
                    "<a href='%(contact_email)s'>%(contact_email)s</a></p>"
                )
                if survey_url
                else (
                    "<p>Tēnā koe,</p><p>You have been invited by %(inviter)s to be a referee "
                    "for %(main_applicant)s's application to the "
                    "%(application)s application.</p>"
                    "<p>We strongly advise clicking on the Referee Guidelines <strong>before</strong> clicking  "
                    "on the portal link below.</p>"
                    "<p><a href='%(guidelines)s'>Referee Guidelines</a></p>"
                    "<p><strong>To review this invitation, you are required to follow the portal link</strong>: "
                    "<a href='%(url)s'>%(url)s</a> after you have read about the process.</p>"
                    "<p>If you have any further questions, please contact "
                    "<a href='%(contact_email)s'>%(contact_email)s</a></p>"
                )
            ) % dict(
                inviter=by.full_name,
                main_applicant=self.referee.application.submitted_by.full_name,
                url=url,
                survey_url=survey_url,
                site_name=site_name,
                application=self.referee.application,
                guidelines=self.referee.application.round.get_guidelines(),
                contact_email=contact_email,
            )
        elif self.type == INVITATION_TYPES.A:
            subject = __("You have been nominated for %s") % self.nomination.round
            body = __(
                "Tēnā koe,\n\n"
                "Congratulations on being nominated for the %(round)s by %(inviter)s.\n\n"
                "Before you click on the portal link we strongly advise you "
                "to read about the application process: %(guidelines)s.\n\n"
                "To accept the nomination, please follow the portal link %(url)s\n\n\n"
                "Ngā mihi nui"
            ) % dict(
                round=self.nomination.round,
                inviter=by.full_name,
                guidelines=self.nomination.round.get_guidelines(),
                url=url,
            )
            html_body = (
                __(
                    "<p>Tēnā koe,</p>"
                    "<p>Congratulations on being nominated for the %(round)s by %(inviter)s.</p>"
                    "<p>Before you click on the portal link we strongly advise you "
                    'to read about the <a href="%(guidelines)s">application process</a>.</p>'
                    "<p>To accept the nomination, please follow the portal link: "
                    "<a href='%(url)s'>%(url)s</a><br></p></br>"
                )
            ) % dict(
                round=self.nomination.round,
                inviter=by.full_name,
                guidelines=self.nomination.round.get_guidelines(),
                url=url,
            )
        elif self.type == INVITATION_TYPES.P:
            subject = __("You are invited to be a Panellist for the %(site_name)s") % {
                "site_name": site_name
            }
            body = __(
                "Tēnā koe\n\n"
                "You are invited to be a panellist for the %(site_name)s.\n\n"
                "To review this invitation, please follow the link: %(url)s \n\n"
                "Ngā mihi"
            ) % {"url": url, "site_name": site_name}
            html_body = __(
                "Tēnā koe,<br><br>You are invited to be a panellist for the %(site_name)s.<br><br>"
                "To review this invitation, please follow the link: <a href='%(url)s'>%(url)s</a><br>"
            ) % {"url": url, "site_name": site.name}
        else:
            subject = __("You have been given access to the %(site_name)s portal") % {
                "site_name": site_name
            }
            body = __(
                "Tēnā koe,\n\n You have been given access to the %(site_name)s portal.\n\n"
                "To confirm this access, please follow the link: %(url)s \n\n"
                "Ngā mihi"
            ) % {"site_name": site_name, "url": url}
            html_body = __(
                "Tēnā koe,<br><br>You have been given access to the %(site_name)s portal.<br><br>"
                "To confirm this access, please follow the link: <a href='%(url)s'>%(url)s</a><br>"
            ) % {"url": url, "site_name": site_name}

        resp = send_mail(
            subject,
            body,
            html_message=html_body,
            recipient_list=[self.email],
            fail_silently=False,
            request=request,
            reply_to=by.email if by else settings.DEFAULT_FROM_EMAIL,
            invitation=self,
            thread_index=self.thread_index,
            thread_topic=self.thread_topic,
        )

        if self.type == INVITATION_TYPES.T:
            if self.member:
                self.member.send(request)
                self.member.save()
        elif self.type == INVITATION_TYPES.R:
            if self.referee:
                self.referee.send(request)
                self.referee.save()
        elif self.type == INVITATION_TYPES.P:
            if self.panellist:
                self.panellist.send(request)
                self.panellist.save()
        return resp

    @fsm_log
    @transition(field=state, source=["*"], target="read")
    def mark_read(self, request=None, by=None, description=None, commit=True, *args, **kwargs):
        pass

    @fsm_log
    @transition(field=state, source=["*"], target="autoreplied")
    def mark_autoreplied(
        self, request=None, by=None, description=None, commit=True, *args, **kwargs
    ):
        pass

    @fsm_log
    @transition(
        field=state,
        source=[
            "draft",
            "sent",
            "accepted",
            "bounced",
            "read",
            "autoreplied",
        ],
        target="accepted",
    )
    def accept(self, request=None, by=None, description=None, commit=True, *args, **kwargs):
        if not by and request:
            by = request.user
        if not by:
            if not request or not request.user:
                raise Exception("User unknown!")
            by = request.user
        if (
            self.type == INVITATION_TYPES.T
            and (m := self.member)
            and m.state not in ["accepted", "authorized"]
        ):
            m.user = by
            m.accept(request)
            if commit:
                m.save()
        elif self.type == INVITATION_TYPES.A:
            if self.nomination:
                n = self.nomination
                n.user = by
                if commit:
                    n.save()
        elif (
            self.type == INVITATION_TYPES.R
            and (r := self.referee)
            and r.state not in ["accepted", "opted_out", "testified"]
        ):
            r.user = by
            r.accept(request, by=by, description=description, commit=False, *args, **kwargs)
            if commit:
                r.save()
            if self.state != "accepted":
                t, _ = Testimonial.get_or_create(referee=r)
        elif self.type == INVITATION_TYPES.P:
            p = self.panellist
            if p:
                p.user = by
                if p.state != "accepted":
                    p.accept(request)
                    if commit:
                        p.save()
            else:
                self.revoke()

    @fsm_log
    @transition(field=state, source=["*"], target="bounced")
    def bounce(self, request=None, by=None, *args, **kwargs):
        def get_absolute_uri(request, url):
            if request:
                url = request.build_absolute_uri(url)
            elif self.url:
                pr = urlparse(self.url)
                url = urljoin(f"{pr.scheme}://{pr.netloc}", url)
            else:
                url = f"https://{urljoin(Site.objects.get_current().domain, url)}"
            return url

        body = (
            __(
                "We are sorry to have to inform you that your invitation message could not be delivered to %s."
            )
            % self.email
        )
        url = None

        if self.type == INVITATION_TYPES.R and self.referee:
            self.referee.state = "bounced"
            self.referee.save()
            url = get_absolute_uri(
                request,
                reverse("application-update", kwargs={"pk": self.application.id}) + "?referees=1",
            )
        elif self.type == INVITATION_TYPES.T and self.member:
            self.member.state = "bounced"
            self.member.save()
            url = get_absolute_uri(
                request, reverse("application-update", kwargs={"pk": self.application.id})
            )
        elif self.type == INVITATION_TYPES.P and self.panellist:
            self.panellist.state = "bounced"
            self.panellist.save()
            url = get_absolute_uri(
                request, reverse("panellist-invite", kwargs={"round": self.round.id})
            )

        if url:
            body += (
                "\n\n" + __("Please correct the email address to resend the invitation: %s") % url
            )

        if self.inviter:
            send_mail(
                __("Your Invitation Undelivered"),
                body,
                recipient_list=[self.inviter.email],
                fail_silently=False,
                request=request,
                reply_to=by.email if by else settings.DEFAULT_FROM_EMAIL,
                invitation=self,
                thread_index=self.thread_index,
                thread_topic=self.thread_topic,
            )

    @classmethod
    def outstanding_invitations(cls, user):
        site_id = cls.get_current_site_id()
        return cls.objects.raw(
            "SELECT i.* FROM invitation AS i JOIN account_emailaddress AS ae ON ae.email = i.email "
            "WHERE ae.user_id=%s AND i.state NOT IN ('accepted', 'expired', 'revoked') AND i.site_id=%s "
            "UNION SELECT * FROM invitation WHERE email=%s AND state NOT IN ('accepted', 'expired', 'revoked') "
            "  AND site_id=%s",
            [user.id, site_id, user.email, site_id],
        )

    def __str__(self):
        return f"Invitation for {self.first_name} {self.last_name} ({self.email})"

    class Meta:
        db_table = "invitation"


simple_history.register(
    Invitation, inherit=True, table_name="invitation_history", bases=[InvitationMixin, Model]
)


TESTIMONIAL_STATES = Choices(
    (None, None),
    ("new", _("new")),
    ("draft", _("draft")),
    ("submitted", _("submitted")),
)


class TestimonialMixin:
    STATES = TESTIMONIAL_STATES


class Testimonial(TestimonialMixin, PersonMixin, PdfFileMixin, Model):
    """A Testimonial/endorsement/feedback given by a referee."""

    site = ForeignKey(Site, on_delete=PROTECT, default=Model.get_current_site_id)
    objects = CurrentSiteManager()
    all_objects = Manager()

    referee = OneToOneField(
        Referee, related_name="testimonial", on_delete=CASCADE, verbose_name=_("referee")
    )
    summary = TextField(blank=True, null=True, verbose_name=_("summary"))
    file = PrivateFileField(
        verbose_name=_("endorsement, testimonial, or feedback"),
        help_text=_("Please upload your endorsement, testimonial, or feedback"),
        upload_subfolder=lambda instance: ["testimonials", hash_int(instance.referee_id)],
        blank=True,
        null=True,
    )
    converted_file = ForeignKey(
        ConvertedFile, null=True, blank=True, on_delete=SET_NULL, verbose_name=_("converted file")
    )
    cv = ForeignKey(
        "CurriculumVitae",
        editable=True,
        null=True,
        blank=True,
        on_delete=PROTECT,
        verbose_name=_("curriculum vitae"),
    )
    state = StateField(_("state"), default="new")

    @property
    def application(self):
        return self.referee.application

    @fsm_log
    @transition(field=state, source=["new", "draft"], target="draft")
    def save_draft(self, request=None, by=None, *args, **kwargs):
        pass

    @fsm_log
    @transition(field=state, source=["new", "draft"], target="submitted")
    def submit(self, request=None, by=None, *args, **kwargs):
        # self.referee.has_testifed = True
        # self.referee.state = "testified"
        # self.referee.testified_at = datetime.now()
        if not by and request:
            by = request.user
        if self.referee.state != "testified":
            self.referee.testify(request=request, by=by, *args, **kwargs)
            if description := kwargs.get("description"):
                self.referee._change_reason = description
            self.referee.save()

    @classmethod
    def user_testimonials(cls, user, state=None, round=None):
        q = cls.objects.all()
        if not (user.is_staff or user.is_superuser):
            q = q.filter(referee__user=user)
        if state == "draft":
            q = q.filter(state__in=[state, "new"])
        if state:
            q = q.filter(state=state)
        else:
            # q = q.filter(~Q(state="archived"), state__in=["draft", "submitted"])
            q = q.filter(state__in=["draft", "submitted"])
        q = q.filter(referee__application__round__in=Scheme.objects.all().values("current_round"))
        return q

    @classmethod
    def user_testimonial_count(cls, user, state=None, round=None):
        return cls.user_testimonials(user, state=state, round=round).count()

    def save(self, *args, **kwargs):
        if (
            not self.cv
            and self.referee
            and (u := self.referee.user)
            and (cv := CurriculumVitae.last_user_cv(u))
        ):
            self.cv = cv
        super().save(*args, **kwargs)

    def __str__(self):
        if self.referee_id:
            if self.site_id == 4:
                return _("Referee report by {0} for {1}").format(
                    self.referee, self.referee.application
                )
            return _("Testimonial By Referee {0} For Application {1}").format(
                self.referee, self.referee.application
            )
        return self.file.name if self.file else gettext("N/A")

    class Meta:
        db_table = "testimonial"


simple_history.register(
    Testimonial, inherit=True, table_name="testimonial_history", bases=[TestimonialMixin, Model]
)

FILE_TYPE = Choices("CV")


# class PrivateFile(Model):

#     profile = ForeignKey(Profile, null=True, blank=True, on_delete=CASCADE)
#     owner = ForeignKey(User, on_delete=CASCADE)
#     type = CharField(max_length=100, choices=FILE_TYPE)
#     title = CharField("title", max_length=200, null=True, blank=True)
#     # file = PrivateFileField(upload_subfolder=lambda instance: f"cv-{instance.owner.id}")
#     file = PrivateFileField()

#     class Meta:
#         db_table = "private_file"


class CurriculumVitae(PdfFileMixin, PersonMixin, Model):
    profile = ForeignKey(Profile, on_delete=CASCADE, verbose_name=_("profile"))
    owner = ForeignKey(User, on_delete=CASCADE, verbose_name=_("owner"))
    title = CharField(
        _("Title or name"),
        max_length=200,
        null=True,
        blank=True,
        help_text=_("A title or name you can assign to the upload CV file"),
    )
    file = PrivateFileField(
        upload_subfolder=lambda instance: ["cv", hash_int(instance.profile_id)],
        verbose_name=_("file"),
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "doc",
                    "docb",
                    "docm",
                    "docx",
                    "dot",
                    "dotm",
                    "dotx",
                    "odm",
                    "odt",
                    "oth",
                    "ott",
                    "pdf",
                    "rtf",
                    "tex",
                ]
            )
        ],
    )
    converted_file = ForeignKey(
        ConvertedFile, null=True, blank=True, on_delete=SET_NULL, verbose_name=_("converted file")
    )

    @classmethod
    def last_user_cv(cls, user):
        return cls.where(Q(owner=user) | Q(profile__user=user)).order_by("-id").first()

    def __str__(self):
        return self.filename

    def title_page(self):
        """Title page for composite export into PDF"""
        return {
            "TITLES": [_("Curriculum Vitae"), self.full_name],
            _("Submitted At"): self.updated_at or self.created_at,
        }

    @property
    def can_be_deleted(self):
        return not Application.where(cv=self).exists()

    class Meta:
        db_table = "curriculum_vitae"


def default_scheme_code(title):
    title = title.lower()
    code = "".join(w[0] for w in title.split() if w).upper()
    if not code.startswith("PM"):
        code = "PM" + code
    return code


class Scheme(Model):
    site = ForeignKey(Site, on_delete=PROTECT, default=Model.get_current_site_id)
    fund = ForeignKey(Fund, on_delete=SET_NULL, blank=True, null=True, db_column="fund")
    objects = CurrentSiteManager()
    all_objects = Manager()

    title = CharField(_("title"), max_length=100)
    # groups = ManyToManyField(
    #     Group, blank=True, verbose_name=_("who starts the application"), db_table="scheme_group"
    # )
    code = CharField(_("code"), max_length=10, blank=True, default="")
    category = ForeignKey(
        Category, on_delete=SET_NULL, blank=True, null=True, db_column="category"
    )
    current_round = OneToOneField(
        "Round", blank=True, null=True, on_delete=SET_NULL, related_name="+"
    )

    def save(self, *args, **kwargs):
        if self.fund and self.fund.site and self.site != self.fund.site:
            self.site = self.fund.site
        if not self.code:
            self.code = default_scheme_code(self.title)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

    def can_be_started_by(self, group_name):
        return self.groups.filter(name=group_name).exists()

    @property
    def can_be_applied_to(self):
        """Can be applied directly."""
        return self.can_be_started_by("APPLICANT")

    @property
    def can_be_nominated_to(self):
        return self.can_be_started_by("NOMINATOR")

    @property
    def guidelines(self):
        if self.current_round:
            return self.current_round.guidelines

    @property
    def description(self):
        if self.current_round:
            return self.current_round.description

    @property
    def research_summary_required(self):
        if self.current_round:
            return self.current_round.research_summary_required

    @property
    def team_can_apply(self):
        if self.current_round:
            return self.current_round.team_can_apply

    @property
    def presentation_required(self):
        if self.current_round:
            return self.current_round.presentation_required

    @property
    def pid_required(self):
        if self.current_round:
            return self.current_round.pid_required

    @property
    def ethics_statement_required(self):
        if self.current_round:
            return self.current_round.ethics_statement_required

    class Meta:
        db_table = "scheme"


def round_template_path(instance, filename):
    r = instance if hasattr(instance, "title") else instance.round
    title = (r.title or r.scheme.title).lower().replace(" ", "-")
    return f"rounds/{title}/{filename}"


class Round(Model):
    site = ForeignKey(Site, on_delete=PROTECT, default=Model.get_current_site_id)
    objects = CurrentSiteManager()
    all_objects = Manager()

    title = CharField(_("title"), max_length=100, null=True, blank=True)
    scheme = ForeignKey(Scheme, on_delete=CASCADE, related_name="rounds", verbose_name=_("scheme"))
    opens_on = DateField(_("opens on"), null=True, blank=True)
    closes_on = DateTimeField(_("closes on"), null=True, blank=True)

    guidelines = CharField(_("guideline link URL"), max_length=120, null=True, blank=True)
    description = TextField(_("short description"), null=True, blank=True)

    has_title = BooleanField(_("can have a title"), default=False)

    research_summary_required = BooleanField(_("research summary required"), default=False)
    team_can_apply = BooleanField(_("can be submitted by a team"), default=False)
    presentation_required = BooleanField(default=False)
    # cv_required = BooleanField(_("CVs required"), default=True)
    pid_required = BooleanField(_("photo ID required"), default=True)
    ethics_statement_required = BooleanField(default=False)
    # budget_required = BooleanField(_("Budget required"), default=False)
    applicant_cv_required = BooleanField(
        _("Applicant/Team representative CV required"), default=True
    )
    nominator_cv_required = BooleanField(_("Nominator CV required"), default=True)

    has_referees = BooleanField(_("can invite referees"), default=True)
    required_referees = PositiveSmallIntegerField(
        _("Required number of referees"),
        null=True,
        blank=True,
        default=0,
        choices=Choices(0, 1, 2, 3, 4),
        help_text="Minimum of referees the application needs to nominate",
    )
    is_flexible_number_of_referees = BooleanField(_("Flexible number of referees"), default=False)
    duration = PositiveSmallIntegerField(
        _("Duration"), help_text=_("Default contract duration"), null=True, blank=True
    )
    referee_cv_required = BooleanField(_("Referee CV required"), default=True)
    survey_id = PositiveIntegerField(help_text=_("LimeSurvey Survey ID"), null=True, blank=True)

    letter_of_support_required = BooleanField(default=False)
    research_experience_in_years_required = BooleanField(default=False)

    direct_application_allowed = BooleanField(default=True)
    can_nominate = BooleanField(default=True)
    notify_nominator = BooleanField(
        default=False,
        verbose_name=_("Notify nominator/principal/mentor"),
    )

    tac = TextField(
        _("T&C"), max_length=10000, null=True, blank=True, help_text=_("Terms and Conditions")
    )

    has_online_scoring = BooleanField(default=True)
    score_sheet_template = FileField(
        null=True,
        blank=True,
        upload_to=round_template_path,
        verbose_name=_("Score Sheet Template"),
        validators=[FileExtensionValidator(allowed_extensions=["xls", "xlsx"])],
    )
    # Categories
    has_fors = BooleanField(
        _("Has FoRs"), default=False, help_text=_("Has Field of Research Categories")
    )
    has_seos = BooleanField(
        _("Has SEOs"), default=False, help_text=_("Has Socio-Economic Objective Categories")
    )
    has_toas = BooleanField(
        _("Has ToA"), default=False, help_text=_("Has Type of Activity Categories")
    )
    has_vmts = BooleanField(
        _("Has VMTs"), default=False, help_text=_("Has Vision Mātauranga Theme Categories")
    )
    has_keywords = BooleanField(_("Has keywords"), default=False, help_text=_("Has Keywords"))

    @property
    def has_categories(self):
        return (
            self.has_fors or self.has_seos or self.has_toas or self.has_vmts or self.has_keywords
        )

    nomination_template = FileField(
        null=True,
        blank=True,
        upload_to=round_template_path,
        verbose_name=_("Nomination Template"),
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "doc",
                    "docx",
                    "dot",
                    "dotx",
                    "docm",
                    "dotm",
                    "docb",
                    "odt",
                    "ott",
                    "oth",
                    "odm",
                ]
            )
        ],
    )
    application_template = FileField(
        null=True,
        blank=True,
        upload_to=round_template_path,
        verbose_name=_("Application Template"),
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "doc",
                    "docx",
                    "dot",
                    "dotx",
                    "docm",
                    "dotm",
                    "docb",
                    "odt",
                    "ott",
                    "oth",
                    "odm",
                    "rtf",
                    "tex",
                ]
            )
        ],
    )
    referee_template = FileField(
        null=True,
        blank=True,
        upload_to=round_template_path,
        verbose_name=_("Referee Template"),
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "doc",
                    "docx",
                    "dot",
                    "dotx",
                    "docm",
                    "dotm",
                    "docb",
                    "odt",
                    "ott",
                    "oth",
                    "odm",
                ]
            )
        ],
    )
    budget_template = FileField(
        null=True,
        blank=True,
        upload_to=round_template_path,
        verbose_name=_("Budget Template"),
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "xls",
                    "xlw",
                    "xlt",
                    "xml",
                    "xlsx",
                    "xlsm",
                    "xltx",
                    "xltm",
                    "xlsb",
                    "csv",
                    "ctv",
                ]
            )
        ],
    )

    def get_guidelines(self):
        if not self.guidelines and (
            pr := Round.where(Q(guidelines__isnull=False) | ~Q(guidelines=""), scheme=self.scheme)
            .order_by("-id")
            .first()
        ):
            return pr.guidelines
        return self.guidelines

    @property
    def is_active(self):
        return self.scheme.current_round == self

    def clean(self):
        if (
            self.opens_on
            and self.closes_on
            and datetime.combine(self.opens_on, datetime.min.time()).timestamp()
            > self.closes_on.timestamp()
        ):
            raise ValidationError(_("the round cannot close before it opens."))
        if not self.title:
            self.title = self.scheme.title
            if self.opens_on:
                self.title = f"{self.title} {self.opens_on.year}"

    def save(self, *args, **kwargs):
        scheme = self.scheme
        created_new = not (self.id)
        super().save(*args, **kwargs)

        if created_new and (last_round := Round.where(scheme=scheme).order_by("-id").first()):
            Criterion.objects.bulk_create(
                [
                    Criterion(
                        round=self,
                        definition=c.definition,
                        comment=c.comment,
                        min_score=c.min_score,
                        max_score=c.max_score,
                        scale=c.scale,
                    )
                    for c in last_round.criteria.all()
                ]
            )

        if not scheme.current_round:
            scheme.current_round = self
            scheme.save(update_fields=["current_round"])

    def init_from_last_round(self, last_round=None):
        if not last_round and self.scheme:
            q = Round.where(scheme=self.scheme)
            if self.id:
                q = q.filter(~Q(id=self.id))
            last_round = q.order_by("-id").first()

        if last_round:
            scheme = self.scheme or last_round.scheme

            for f in [f.name for f in self._meta.fields]:
                if f in ["title", "opens_on", "closes_on", "id", "title_en", "title_mi"]:
                    continue
                v = getattr(last_round, f)
                if v and not getattr(self, f):
                    setattr(self, f, v)

            if not self.opens_on and last_round.opens_on:
                self.opens_on = last_round.opens_on + relativedelta(years=1)

            if not self.closes_on and last_round.closes_on:
                self.closes_on = last_round.closes_on + relativedelta(years=1)

        if not self.title_en:
            title = scheme.title_en
            if self.opens_on:
                title = f"{title} {self.opens_on.year}"
            self.title_en = title

        if self.title_en == scheme.title_en and self.opens_on:
            self.title_en = f"{self.title_en} {self.opens_on.year}"

        if not self.title_mi:
            title = scheme.title_mi
            if self.opens_on:
                title = f"{title} {self.opens_on.year}"
            self.title_mi = title

        if self.title_mi == scheme.title_mi and self.opens_on:
            self.title_mi = f"{self.title_mi} {self.opens_on.year}"

        if self.site_id == 4:
            for f in [
                "applicant_cv_required",
                "direct_application_allowed",
                "ethics_statement_required",
                "letter_of_support_required",
            ]:
                setattr(self, f, None)

        return self

    def clone(self):
        nr = Round(scheme=self.scheme)
        nr.init_from_last_round(last_round=self)
        if not nr.title:
            nr.title = self.scheme.title
        if nr.title == self.scheme.title and nr.opens_on:
            nr.title = f"{nr.title} {nr.opens_on.year}"
        nr.save()
        return nr

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        opens_on = kwargs.get("opens_on")
        if (
            not self.id
            and (scheme := kwargs.get("scheme"))
            and (last_round := Round.where(scheme=scheme).order_by("-id").first())
        ):
            site_id = settings.SITE_ID
            for f in [
                "has_title",
                "applicant_cv_required",
                "can_nominate",
                "notify_nominator",
                "description_en",
                "description_mi",
                "tac_en",
                "tac_mi",
                "direct_application_allowed",
                "ethics_statement_required",
                "guidelines",
                "nominator_cv_required",
                "pid_required",
                "presentation_required",
                "has_referees",
                "referee_cv_required",
                "letter_of_support_required",
                "research_summary_required",
                "team_can_apply",
                "required_referees",
                # "budget_required",
                "research_experience_in_years_required",
            ]:
                if f not in kwargs and (
                    site_id != 4
                    or f
                    not in [
                        "applicant_cv_required",
                        "direct_application_allowed",
                        "ethics_statement_required",
                        "letter_of_support_required",
                    ]
                ):
                    v = getattr(last_round, f)
                    if v:
                        kwargs[f] = getattr(last_round, f)
                        setattr(self, f, v)

            if not opens_on and last_round.opens_on:
                opens_on = last_round.opens_on + relativedelta(years=1)
                if "opens_on" not in kwargs:
                    kwargs["opens_on"] = opens_on
                    self.opens_on = opens_on

            if "closes_on" not in kwargs and last_round.closes_on:
                self.closes_on = kwargs["closes_on"] = last_round.closes_on + relativedelta(
                    years=1
                )

            if "title" not in kwargs:
                title = scheme.title
                if opens_on:
                    title = f"{title} {opens_on.year}"
                kwargs["title"] = title
                self.title = title

            if "score_sheet_template" not in kwargs and (
                pr1 := Round.where(scheme=scheme, score_sheet_template__isnull=False)
                .order_by("-id")
                .first()
            ):
                kwargs["score_sheet_template"] = pr1.score_sheet_template

            if "application_template" not in kwargs and (
                pr2 := Round.where(scheme=scheme, application_template__isnull=False)
                .order_by("-id")
                .first()
            ):
                kwargs["application_template"] = pr2.application_template

            if "nomination_template" not in kwargs and (
                pr3 := Round.where(scheme=scheme, nomination_template__isnull=False)
                .order_by("-id")
                .first()
            ):
                kwargs["nomination_template"] = pr3.nomination_template

            if "referee_template" not in kwargs and (
                pr4 := Round.where(scheme=scheme, referee_template__isnull=False)
                .order_by("-id")
                .first()
            ):
                kwargs["referee_template"] = pr4.referee_template

            if "budget_template" not in kwargs and (
                pr5 := Round.where(scheme=scheme, budget_template__isnull=False)
                .order_by("-id")
                .first()
            ):
                kwargs["budget_template"] = pr5.budget_template
            if "site" not in kwargs:
                kwargs["site"] = scheme.site

            if self.site_id == 4 or settings.SITE_ID == 4:
                for f in [
                    "applicant_cv_required",
                    "direct_application_allowed",
                    "ethics_statement_required",
                    "letter_of_support_required",
                ]:
                    setattr(self, f, None)

    def __str__(self):
        return self.title or self.scheme.title

    def get_absolute_url(self):
        return f"{reverse('applications')}?round={self.id}"

    def user_nominations(self, user):
        return Nomination.where(
            Q(user=user)
            | Q(email=user.email)
            | Q(email__in=Subquery(EmailAddress.objects.filter(user=user).values("email"))),
            state__in=["submitted", "accepted"],
            round=self,
        )

    def user_has_nomination(self, user):
        """User has a nomination to apply for the round."""

        return self.user_nominations(user).exists()

    @property
    def deadline_days(self):
        if closes_on := self.closes_on:
            now = datetime.now(tz=closes_on.tzinfo)
            if closes_on >= now:
                ts = closes_on - now
                return round(ts.total_seconds() / 86400)

    @property
    def is_open(self):
        return self.opens_on <= date.today() and (
            self.closes_on is None or self.closes_on >= datetime.now(tz=self.closes_on.tzinfo)
        )

    @property
    def has_closed(self):
        return self.closes_on and self.closes_on < datetime.now(tz=self.closes_on.tzinfo)

    @property
    def will_open(self):
        """The round will be open in the future."""
        today = date.today()
        return self.opens_on > today

    def all_coi_statements_given_by(self, user):
        return (
            not self.applications.all()
            .filter(
                Q(conflict_of_interests__isnull=True)
                | Q(
                    conflict_of_interests__has_conflict__isnull=True,
                    conflict_of_interests__panellist__user=user,
                )
            )
            .exists()
        )

    @property
    def avg_scores(self):
        site_id = self.current_site_id
        return Application.objects.raw(
            """SELECT a.*, t.total
            FROM application AS a JOIN (
                SELECT et.application_id, avg(et.total) AS total
                FROM (
                    SELECT e.id, e.application_id, sum(
                        CASE
                            WHEN c.scale IS NULL OR c.scale=0 THEN s.value
                            ELSE c.scale*s.value
                        END
                    ) AS total
                    FROM evaluation AS e JOIN score AS s ON s.evaluation_id=e.id
                        JOIN application AS a ON a.id=e.application_id
                        JOIN criterion AS c ON c.id=s.criterion_id
                    WHERE a.round_id=%s AND a.site_id=%s
                    GROUP BY e.id, e.application_id) AS et
                GROUP BY et.application_id
            ) AS t ON t.application_id=a.id
            WHERE a.round_id=%s AND a.site_id=%s
            ORDER BY a.number""",
            [self.id, site_id, self.id, site_id],
        )

    @property
    def scores(self):
        """Return list of all panellists and the scores given."""
        return (
            self.panellists.all()
            .prefetch_related(
                Prefetch(
                    "evaluations",
                    queryset=Evaluation.objects.filter(application__round=self)
                    .annotate(
                        total=Sum(
                            Case(
                                When(
                                    Q(scores__criterion__scale__isnull=True)
                                    | Q(scores__criterion__scale=0),
                                    then=F("scores__value"),
                                ),
                                default=F("scores__value")
                                * Cast(
                                    "scores__criterion__scale",
                                    output_field=PositiveIntegerField(),
                                ),
                            )
                        )
                    )
                    .order_by("application__number"),
                ),
                Prefetch(
                    "evaluations__application",
                    queryset=Application.objects.order_by("-number"),
                ),
                "evaluations__scores",
                Prefetch(
                    "evaluations__scores__criterion",
                    queryset=Criterion.where(round_id=F("round_id")).order_by("definition"),
                ),
            )
            .order_by(
                Coalesce("first_name", "user__first_name"),
                Coalesce("last_name", "user__last_name"),
            )
        )

    @property
    def summary(self):
        site_id = self.current_site_id
        return Application.objects.raw(
            """
            WITH summary AS (
                SELECt a.id, count(r.id) AS referee_count,
                    sum(CASE WHEN r.state='testified'
                    -- OR has_testifed
                    THEN 1 ELSE 0 END) AS submitted_reference_count
                FROM application AS a
                    LEFT JOIN referee AS r ON r.application_id=a.id
                WHERE a.round_id=%s AND a.site_id=%s
                GROUP BY a.id
            ), member_summary AS (
                SELECt a.id, count(m.id) AS member_count,
                    sum(CASE WHEN m.state='authorized' THEN 1 ELSE 0 END) AS member_authorized_count
                FROM application AS a
                    LEFT JOIN member AS m ON m.application_id=a.id
                WHERE a.round_id=%s AND a.site_id=%s
                GROUP BY a.id
            )
            SELECT
                a.*,
                s.referee_count,
                s.submitted_reference_count,
                ms.member_count,
                ms.member_authorized_count,
                u.is_identity_verified,
                p.is_accepted
            FROM application AS a JOIN summary AS s ON s.id=a.id
                LEFT JOIN member_summary AS ms ON ms.id=a.id
                LEFT JOIN users_user AS u ON u.id = a.submitted_by_id
                LEFT JOIN profile AS p ON p.user_id = u.id
                LEFT JOIN scheme ON scheme.current_round_id = a.round_id
            WHERE a.round_id=%s AND a.site_id=%s
            ORDER BY a.number
            """,
            [self.id, site_id, self.id, site_id, self.id, site_id],
        )

    @classmethod
    def current_rounds(cls):
        return cls.where(id=F("scheme__current_round__id"))

    @property
    @lru_cache(1)
    def survey_server_url(self):
        if "LIMESURVEY_SERVER_URL" in dir(settings):
            return settings.LIMESURVEY_SERVER_URL
        else:
            site = self.site or Site.objects.get_current()
            return f"https://{site.domain}/limesurvey"

    @property
    @lru_cache(1)
    def survey_api_url(self):
        if "LIMESURVEY_API_URL" in dir(settings):
            return settings.LIMESURVEY_API_URL
        elif server_url := self.survey_server_url:
            return f"{server_url}/admin/remotecontrol"
        else:
            site = self.site or Site.objects.get_current()
            return f"https://{site.domain}/limesurvey/admin/remotecontrol"

    class Meta:
        db_table = "round"


class RequiredDocument(TimeStampMixin, HelperMixin, OrderableModel):
    round = ForeignKey(Round, on_delete=CASCADE, related_name="required_documents")
    document_type = ForeignKey(DocumentType, on_delete=CASCADE, related_name="required_documents")
    title = CharField(
        _("Title"), max_length=200, null=True, blank=True, help_text=_("Title (e.g. Dr, Professor")
    )
    is_optional = BooleanField(default=False)
    min_pages = PositiveSmallIntegerField(null=True, blank=True)
    max_pages = PositiveSmallIntegerField(null=True, blank=True)

    def __str__(self):
        dt = self.document_type.name
        title = self.title or dt
        if title == dt:
            return title
        return f"{dt}: {title}"

    class Meta(OrderableModel.Meta):
        db_table = "required_document"


class RoundDocumentTemplate(Model):
    round = ForeignKey(Round, on_delete=CASCADE, related_name="templates")
    document_type = ForeignKey(DocumentType, on_delete=CASCADE)
    file = FileField(
        upload_to=round_template_path,
        verbose_name=_("Template"),
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "csv",
                    "ctv",
                    "doc",
                    "docb",
                    "docm",
                    "docx",
                    "dot",
                    "dotm",
                    "dotx",
                    "odm",
                    "odt",
                    "oth",
                    "ott",
                    "rtf",
                    "tex",
                    "xls",
                    "xlsb",
                    "xlsm",
                    "xlsx",
                    "xlt",
                    "xltm",
                    "xltx",
                    "xlw",
                    "xml",
                ]
            )
        ],
    )

    class Meta:
        db_table = "round_document_template"


class ApplicationFormTemplate(Model):
    round = ForeignKey(Round, on_delete=CASCADE, related_name="application_form_templates")
    file = FileField(
        upload_to=round_template_path,
        verbose_name=_("Template"),
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "doc",
                    "docx",
                    "dot",
                    "dotx",
                    "docm",
                    "dotm",
                    "docb",
                    "odt",
                    "ott",
                    "oth",
                    "odm",
                    "rtf",
                    "tex",
                ]
            )
        ],
    )

    class Meta:
        db_table = "application_form_template"


class CurriculumVitaeTemplate(Model):
    round = ForeignKey(Round, on_delete=CASCADE, related_name="curriculum_vitae_templates")
    file = FileField(
        upload_to=round_template_path,
        verbose_name=_("Template"),
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "doc",
                    "docx",
                    "dot",
                    "dotx",
                    "docm",
                    "dotm",
                    "docb",
                    "odt",
                    "ott",
                    "oth",
                    "odm",
                    "rtf",
                    "tex",
                ]
            )
        ],
    )

    class Meta:
        db_table = "curriculum_vitae_template"


class ApplicationDocument(PdfFileMixin, Model):
    application = ForeignKey(Application, on_delete=CASCADE, related_name="documents")
    document_type = ForeignKey(
        DocumentType, related_name="application_documents", on_delete=CASCADE
    )
    required_document = ForeignKey(RequiredDocument, on_delete=DO_NOTHING, related_name="+")
    page_count = PositiveSmallIntegerField(null=True, blank=True)
    file = PrivateFileField(
        blank=True,
        null=True,
        upload_subfolder=lambda instance: [
            "applications",
            hash_int(instance.application.round_id),
            hash_int(instance.application_id),
        ],
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "csv",
                    "ctv",
                    "doc",
                    "docb",
                    "docm",
                    "docx",
                    "dot",
                    "dotm",
                    "dotx",
                    "odm",
                    "odt",
                    "oth",
                    "ott",
                    "pdf",
                    "rtf",
                    "tex",
                    "xls",
                    "xlsb",
                    "xlsm",
                    "xlsx",
                    "xlt",
                    "xltm",
                    "xltx",
                    "xlw",
                    "xml",
                ]
            )
        ],
    )
    converted_file = ForeignKey(
        ConvertedFile, null=True, blank=True, on_delete=SET_NULL, verbose_name=_("converted file")
    )

    def save(self, *args, **kwargs):
        if not self.file.name:
            return
        if not self.document_type_id:
            self.document_type = self.required_document.document_type
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.document_type}: {os.path.basename(self.file.name)}"

    class Meta:
        db_table = "application_document"


class Criterion(Model):
    """Scoring criterion"""

    round = ForeignKey(Round, on_delete=CASCADE, related_name="criteria")
    definition = TextField(max_length=200)
    comment = BooleanField(
        default=True, help_text=_("The panellist should comment on their score")
    )
    min_score = PositiveSmallIntegerField(default=0)
    max_score = PositiveSmallIntegerField(default=10)
    scale = SmallIntegerField(null=True, blank=True)

    class Meta:
        db_table = "criterion"
        verbose_name_plural = _("criteria")

    def __str__(self):
        return self.definition


class EvaluationMixin:
    STATES = Choices(
        (None, None),
        ("new", _("new")),
        ("draft", _("draft")),
        ("submitted", _("submitted")),
        ("accepted", _("accepted")),
    )


class Evaluation(EvaluationMixin, Model):
    """Evaluation Score Sheet"""

    panellist = ForeignKey(Panellist, on_delete=CASCADE, related_name="evaluations")
    application = ForeignKey(Application, on_delete=CASCADE, related_name="evaluations")
    # file = PrivateFileField(
    #     blank=True,
    #     null=True,
    #     verbose_name=_("Score sheet"),
    #     help_text=_("Please upload completed application evaluation score sheet"),
    #     upload_subfolder=lambda instance: ["score-sheet", hash_int(instance.application.code)],
    # )
    comment = TextField(_("Overall Comment"))
    # scores = ManyToManyField(Criterion, blank=True, through="Score")
    total_score = PositiveIntegerField(_("Total Score"), default=0)
    state = StateField(null=True, blank=True, default="new")

    def calc_evaluation_score(self):
        return sum(
            s.value * s.criterion.scale if s.criterion.scale else s.value
            for s in Score.where(evaluation=self)
        )

    @fsm_log
    @transition(field=state, source=["draft", "new"], target="draft")
    def save_draft(self, *args, **kwargs):
        self.total_score = self.calc_evaluation_score()

    @fsm_log
    @transition(field=state, source=["new", "draft", "submitted"], target="submitted")
    def submit(self, *args, **kwargs):
        self.total_score = self.calc_evaluation_score()
        if not self.comment:
            raise ValidationError(_("The review is not completed. Missing an overall comment."))

    @classmethod
    def user_evaluations(cls, user, state=None, round=None):
        q = cls.objects.all()
        q = q.filter(application__round__in=Scheme.objects.values("current_round"))
        if not (user.is_staff and user.is_superuser):
            q = q.filter(panellist__user=user, application__state="submitted")
        if state:
            q = q.filter(state=state)
        else:
            q = q.filter(~Q(state="archived"))

        return q

    @classmethod
    def user_evaluation_count(cls, user, state=None, round=None):
        return cls.user_evaluations(user, state=state, round=round).count()

    def all_scores(self, criteria=None):
        """Get full list of the scores based on the list of the criteria"""
        if not criteria:
            criteria = self.application.round.criteria.all().order_by("definition")

        scores = {s.criterion_id: s for s in self.scores.all()}
        for c in criteria:
            yield scores.get(c.id, {"criteria": c})

    def __str__(self):
        return _("Evaluation of %s by %s") % (self.application, self.panellist)

    class Meta:
        db_table = "evaluation"


simple_history.register(
    Evaluation, inherit=True, table_name="evaluation_history", bases=[EvaluationMixin, Model]
)


class Score(Model):
    evaluation = ForeignKey(Evaluation, on_delete=CASCADE, related_name="scores")
    criterion = ForeignKey(Criterion, on_delete=CASCADE, related_name="scores")
    value = PositiveIntegerField(_("Score"), default=0)
    comment = TextField(null=True, blank=True)

    @property
    def effective_score(self):
        if (c := self.criterion) and c.scale:
            return self.value * c.scale
        return self.value

    def __str__(self):
        return self.criterion.definition

    class Meta:
        db_table = "score"


# class SchemeApplicationGroup(Base):
#     scheme = ForeignKey(
#         "SchemeApplication", on_delete=CASCADE, db_column="scheme_id", related_name="+"
#     )
#     group = ForeignKey(Group, on_delete=CASCADE, related_name="+")

#     class Meta:
#         managed = False
#         db_table = "scheme_group"


class SchemeApplication(Model):
    title = CharField(max_length=100, null=True, blank=True)
    scheme = ForeignKey(
        Scheme,
        null=True,
        blank=True,
        on_delete=DO_NOTHING,
        db_constraint=False,
        db_index=False,
        related_name="+",
    )
    # title = CharField(max_length=100)
    # groups = ManyToManyField(
    #     Group,
    #     blank=True,
    #     verbose_name=_("who starts"),
    #     through=SchemeApplicationGroup,
    # )
    # guidelines = CharField(_("guideline link URL"), max_length=120, null=True, blank=True)
    # description = TextField(_("short description"), max_length=1000, null=True, blank=True)

    current_round = ForeignKey(
        "Round", blank=True, null=True, on_delete=DO_NOTHING, related_name="+"
    )
    description = TextField(null=True, blank=True)
    # can_be_applied_to = BooleanField(null=True, blank=True)
    # can_be_nominated_to = BooleanField(null=True, blank=True)
    application = ForeignKey(
        Application,
        null=True,
        on_delete=DO_NOTHING,
        db_constraint=False,
        db_index=False,
        related_name="+",
    )
    application_number = CharField(max_length=24, null=True, blank=True)
    # application_submitted_by = ForeignKey(
    #     User,
    #     blank=True,
    #     on_delete=DO_NOTHING,
    #     db_constraint=False,
    #     db_index=False,
    #     related_name="+",
    # )
    # member_user = ForeignKey(
    #     User,
    #     null=True,
    #     blank=True,
    #     on_delete=DO_NOTHING,
    #     db_constraint=False,
    #     db_index=False,
    #     related_name="+",
    # )
    # panellist = ForeignKey(
    #     Panellist,
    #     null=True,
    #     blank=True,
    #     on_delete=DO_NOTHING,
    #     db_constraint=False,
    #     db_index=False,
    #     related_name="+",
    # )
    is_panellist = BooleanField(null=True, blank=True)
    has_submitted = BooleanField(null=True, blank=True)
    previous_application = ForeignKey(
        Application,
        db_column="previous_application_id",
        null=True,
        on_delete=DO_NOTHING,
        db_constraint=False,
        db_index=False,
        related_name="+",
    )
    previous_application_number = CharField(max_length=24, null=True, blank=True)
    previous_application_title = CharField(max_length=100, null=True, blank=True)
    previous_application_applicant_name = CharField(max_length=400, null=True, blank=True)
    previous_application_created_on = DateField(null=True, blank=True)

    @classmethod
    def get_data(cls, user):
        lang = get_language()
        site_id = cls.get_current_site_id()
        q = cls.objects.raw(
            f"""
            SELECT DISTINCT
                s.id,
                COALESCE(
                    NULLIF(r.title_{lang},''),
                    NULLIF(r.title_en,''),
                    NULLIF(s.title_{lang},''),
                    s.title_en) AS title,
                s.id AS scheme_id,
                la.app_count AS "count",
                la.id AS application_id,
                s.current_round_id,
                CASE
                    WHEN r.description_{lang} IS NULL THEN (COALESCE((
                        SELECT rr.description_{lang}
                        FROM "round" AS rr
                        WHERE rr.scheme_id = s.id
                            AND rr.description_{lang} IS NOT NULL
                            AND trim(rr.description_{lang}) != ''
                        ORDER BY rr.id DESC LIMIT 1),
                        (SELECT rr.description_en
                        FROM "round" AS rr
                        WHERE rr.scheme_id = s.id
                            AND rr.description_en IS NOT NULL
                            AND trim(rr.description_en) != ''
                        ORDER BY rr.id DESC LIMIT 1))
                    )
                    ELSE r.description_{lang}
                END AS description,
                p.id IS NOT NULL AS is_panellist,
                EXISTS (SELECT NULL FROM application WHERE submitted_by_id=%s AND round_id=r.id) AS has_submitted,
                pa.id AS previous_application_id,
                pa.number AS previous_application_number,
                pa.application_title AS previous_application_title,
                pa.created_on AS previous_application_created_on
            FROM scheme AS s
            LEFT JOIN round AS r ON r.id = s.current_round_id AND r.site_id = %s
            LEFT JOIN (
                SELECT
                    max(a.id) AS id,
                    count(*) AS app_count,
                    a.round_id
                FROM application AS a LEFT JOIN member AS m
                    ON m.application_id = a.id AND m.user_id = %s AND a.site_id = %s
                WHERE (m.user_id IS NULL AND a.submitted_by_id = %s)
                    OR m.user_id = %s
                GROUP BY a.round_id
            ) AS la ON la.round_id = r.id
            LEFT JOIN panellist AS p ON p.round_id = r.id AND p.user_id = %s
            LEFT JOIN (
                SELECT
                    a.id,
                    a.number,
                    r.scheme_id,
                    COALESCE(a.application_title, r.title_{lang}, r.title_en) AS application_title,
                    COALESCE(a.created_at, r.opens_on) AS created_on
                FROM application AS a LEFT JOIN round AS r ON r.id = a.round_id AND r.site_id = %s
                WHERE a.id IN (
                        SELECT
                            max(a.id)
                        FROM application AS a
                            JOIN "round" AS r ON r.id=a.round_id AND r.site_id = %s
                            LEFT JOIN scheme AS s ON s.current_round_id = a.round_id
                        WHERE s.id IS NULL AND a.site_id = %s AND a.submitted_by_id = %s
                        GROUP BY r.scheme_id)
                    OR (
                        a.state IN ('cancelled', 'approved')
                        AND a.submitted_by_id = %s
                    )
            ) AS pa ON pa.scheme_id = r.scheme_id AND la.id IS NULL
            WHERE
              s.site_id = %s
            ORDER BY 2;""",
            [
                user.id,
                site_id,
                user.id,
                site_id,
                user.id,
                user.id,
                user.id,
                site_id,
                site_id,
                site_id,
                user.id,
                user.id,
                site_id,
            ],
        )
        prefetch_related_objects(q, "application")
        prefetch_related_objects(q, "current_round")
        prefetch_related_objects(q, "scheme")
        prefetch_related_objects(q, "previous_application")
        return q

    class Meta:
        managed = False
        # db_table = "scheme_application_view"


NOMINATION_STATES = Choices(
    ("accepted", _("accepted")),
    ("bounced", _("bounced")),
    ("draft", _("draft")),
    ("new", _("new")),
    ("sent", _("sent")),
    ("submitted", _("submitted")),
    (None, None),
)


class NominationMixin:
    """Workaround for simple history."""

    STATES = NOMINATION_STATES


class Nomination(NominationMixin, PersonMixin, PdfFileMixin, Model):
    site = ForeignKey(Site, on_delete=PROTECT, default=Model.get_current_site_id)
    objects = CurrentSiteManager()
    all_objects = Manager()

    round = ForeignKey(
        Round, on_delete=CASCADE, related_name="nominations", verbose_name=_("round")
    )

    email = EmailField(_("email address"), help_text=_("Email address of the nominee"))
    # Nominee personal data
    # title = CharField(_("title"), max_length=40, null=True, blank=True, choices=TITLES)
    title = ForeignKey(
        Title,
        null=True,
        blank=True,
        verbose_name=_("title"),
        db_column="title",
        on_delete=DO_NOTHING,
    )
    first_name = CharField(_("first name"), max_length=30)
    middle_names = CharField(
        _("middle names"),
        blank=True,
        null=True,
        max_length=280,
        help_text=_("Comma separated list of middle names"),
    )
    last_name = CharField(_("last name"), max_length=150)
    org = ForeignKey(
        Organisation,
        null=True,
        blank=True,
        on_delete=CASCADE,
        verbose_name=_("organisation"),
        help_text=_("Organisation of the nominee"),
    )

    nominator = ForeignKey(User, on_delete=CASCADE, related_name="nominations")
    summary = TextField(blank=True, null=True)
    file = PrivateFileField(
        null=True,
        blank=True,
        upload_subfolder=lambda instance: ["nominations", hash_int(instance.nominator_id)],
        verbose_name=_("Nominator form"),
        help_text=_("Upload filled-in nominator form"),
    )
    converted_file = ForeignKey(ConvertedFile, null=True, blank=True, on_delete=SET_NULL)

    user = ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=SET_NULL,
        related_name="nominations_to_apply",
        verbose_name=_("Nominee"),
    )
    application = OneToOneField(
        Application,
        null=True,
        blank=True,
        on_delete=SET_NULL,
        related_name="nomination",
        verbose_name=_("application"),
    )
    cv = ForeignKey(
        CurriculumVitae,
        editable=True,
        null=True,
        blank=True,
        on_delete=PROTECT,
        verbose_name=_("Curriculum Vitae"),
    )

    state = StateField(_("state"), null=True, blank=True, default="new")

    def clean(self, *args, **kwargs):
        super().clean(*args, **kwargs)
        user = self.nominator
        if (
            user
            and not user.is_superuser
            and (
                self.email == user.email
                or EmailAddress.objects.filter(email=self.email, user=user)
            )
        ):
            raise ValidationError(_("You cannot nominate yourself for this round."))

    @fsm_log
    @transition(
        field=state,
        source=["new", "draft"],
        target="draft",
    )
    def save_draft(self, *args, **kwargs):
        pass

    def send_invitation(self, *args, **kwargs):
        i, created = Invitation.get_or_create(
            type=INVITATION_TYPES.A,
            nomination=self,
            email=self.email,
            defaults=dict(
                first_name=self.first_name,
                middle_names=self.middle_names,
                last_name=self.last_name,
                org=self.org,
                organisation=self.org and self.org.name,
                inviter=self.nominator,
            ),
        )
        i.send(*args, **kwargs)
        i.save()
        return (i, created)

    @fsm_log
    @transition(
        field=state,
        source=[
            "new",
            "draft",
            "submitted",
            "bounced",
        ],
        target="submitted",
    )
    def submit(self, *args, **kwargs):
        return self.send_invitation(*args, **kwargs)

    @fsm_log
    @transition(
        field=state,
        source=[
            "submitted",
            "bounced",
        ],
        target="accepted",
    )
    def accept(self, *args, **kwargs):
        pass

    @classmethod
    def user_nomination_count(cls, user, state=None):
        sql = """
            SELECT count(*) AS "count"
            FROM nomination AS n JOIN scheme AS s
              ON s.current_round_id=n.round_id
            WHERE (
                n.site_id=%s AND (
        """
        params = [
            cls.get_current_site_id(),
        ]
        if not (user.is_staff or user.is_superuser):
            sql += " n.nominator_id=%s AND "
            params.append(user.id)

        if state:
            if isinstance(state, (list, tuple)):
                state_list = ",".join(f"'{s}'" for s in state)
                sql += f" n.state IN ({state_list})"
            else:
                if state in ["draft", "new"]:
                    sql += " n.state IN ('new', 'draft') OR n.state IS NULL"
                else:
                    sql += " n.state=%s"
                    params.append(state)
        else:
            sql += " n.state IN ('new', 'draft', 'submitted') OR n.state IS NULL"
        sql += ")"
        if not state or (state == "submitted" or "submitted" in state):
            sql += " OR (n.state='submitted' AND (n.user_id=%s OR n.email=%s))"
            params.extend([user.id, user.email])
        sql += ")"

        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()[0]

    def get_absolute_url(self, *args, **kwargs):
        return reverse("nomination-update", kwargs={"pk": self.pk})

    def __str__(self):
        return _('Nomination for "%s"') % self.round

    class Meta:
        db_table = "nomination"


simple_history.register(
    Nomination, inherit=True, table_name="nomination_history", bases=[NominationMixin, Model]
)


class IdentityVerification(Model):
    file = PrivateFileField(
        null=True,
        blank=True,
        upload_subfolder=lambda instance: ["ids", hash_int(instance.user_id)],
        verbose_name=_("Photo Identity"),
    )
    application = OneToOneField(
        Application,
        on_delete=SET_NULL,
        null=True,
        blank=True,
        related_name="identity_verification",
    )
    user = ForeignKey(User, on_delete=CASCADE, related_name="identity_verifications")
    resolution = TextField(blank=True, null=True)
    state = FSMField(default="new", db_index=True)

    @property
    def thread_index(self):
        if self.application_id and (n := Nomination.where(application=self.application_id)):
            idx = n.id
        else:
            idx = self.application_id
        site_id = self.application and self.application.site_id or settings.SITE_ID
        return base64.b64encode(f"{site_id}:{idx}".encode()).decode()

    @property
    def thread_topic(self):
        return self.application and self.application.number

    @fsm_log
    @transition(field=state, source="new", target="draft")
    def save_draft(self, *args, **kwargs):
        pass

    @fsm_log
    @transition(field=state, source=["new", "draft", "needs-resubmission", "sent"], target="sent")
    def send(self, request, *args, **kwargs):
        url = request.build_absolute_uri(reverse("identity-verification", kwargs=dict(pk=self.id)))

        send_mail(
            _("User Identity Verification"),
            _(
                "User %(user)s submitted a photo identity for verification. Please review the ID here: %(url)s"
            )
            % dict(user=self.user, url=url),
            html_message=_(
                "<p>User <b>%(user)s</b> submitted a photo identity for verification. "
                "Please review the ID here: <a href='%(url)s'>%(url)s</a></p>"
            )
            % dict(user=self.user, url=url),
            recipient_list=list(
                User.where(staff_of_sites__id=settings.SITE_ID, is_staff=True)
                .distinct()
                .values_list("name", "email")
            ),
            fail_silently=False,
            request=request,
            reply_to=settings.DEFAULT_FROM_EMAIL,
            thread_index=self.thread_index,
            thread_topic=self.thread_topic,
        )

    @fsm_log
    @transition(field=state, source=["submitted", "sent", "accepted"], target="accepted")
    def accept(self, request=None, *args, **kwargs):
        self.user.is_identity_verified = True
        if request:
            self.identity_verified_by = request.user
        self.identity_verified_at = datetime.now()
        self.user.save()

    @fsm_log
    @transition(field=state, target="needs-resubmission")
    def request_resubmission(self, request, *args, **kwargs):
        url = request.build_absolute_uri(reverse("photo-identity"))
        subject = __("Your ID verification requires your attention")
        body = __("Please resubmit a new copy of your ID: %s") % url

        send_mail(
            subject,
            body,
            recipient_list=[self.user.email],
            fail_silently=False,
            request=request,
            reply_to=request.user.email
            if request and request.user
            else settings.DEFAULT_FROM_EMAIL,
            thread_index=self.thread_index,
            thread_topic=self.thread_topic,
        )
        self.user.is_identity_verified = False
        self.user.identity_verified_by = request and request.user
        self.user.identity_verified_at = datetime.now()
        self.user.save()

    def __str__(self):
        return _('Identity Verification of "%s"') % self.user

    class Meta:
        db_table = "identity_verification"


def get_unique_mail_token(length=10):
    while True:
        token = secrets.token_urlsafe(length)
        if not MailLog.objects.filter(token=token).exists():
            return token


class MailLog(Model):
    """Email log - the log of email sent from the Hub."""

    site = ForeignKey(Site, on_delete=PROTECT, default=Model.get_current_site_id)
    objects = CurrentSiteManager()
    all_objects = Manager()

    sent_at = DateTimeField(auto_now_add=True)
    user = ForeignKey(User, null=True, on_delete=SET_NULL)
    recipient = CharField(max_length=200, db_index=True)
    sender = CharField(max_length=200)
    subject = CharField(max_length=200)
    was_sent_successfully = BooleanField(null=True)
    error = TextField(null=True, blank=True)
    token = CharField(max_length=100, default=get_unique_mail_token, unique=True)
    invitation = ForeignKey(Invitation, null=True, on_delete=SET_NULL)
    thread_index = CharField(max_length=100, null=True, blank=True)
    thread_topic = CharField(max_length=200, null=True, blank=True)
    message = TextField(null=True, blank=True)
    html_message = TextField(null=True, blank=True)

    def __str__(self):
        return f"{self.recipient}: {self.token}/{self.sent_at}"

    class Meta:
        db_table = "mail_log"


class ScoreSheet(Model):
    objects = RoundSiteManager()
    all_objects = Manager()

    panellist = ForeignKey(Panellist, null=True, on_delete=SET_NULL)
    round = ForeignKey(Round, editable=False, on_delete=CASCADE, related_name="score_sheets")
    file = PrivateFileField(
        upload_subfolder=lambda instance: [
            "score-sheets",
            instance.round.title.lower().replace(" ", "-")
            if instance.round.title
            else hash_int(instance.round_id),
        ],
        verbose_name=_("Score Sheet"),
        help_text=_("Upload filled-in for all the applications in bulk"),
    )

    @classmethod
    def user_score_sheets(cls, user):
        return cls.where(panellist__user=user).filter(
            round__in=Scheme.objects.values("current_round")
        )

    @classmethod
    def user_score_sheet_count(cls, user):
        return cls.user_score_sheets(user).count()

    def __str__(self):
        return self.file.name

    class Meta:
        db_table = "score_sheet"


def clean_private_fils(dry_run=False):
    root_dir = settings.PRIVATE_STORAGE_ROOT
    total = 0

    for root, dirs, files in os.walk(root_dir):
        rel_dir = os.path.relpath(root, root_dir)
        for rel_name in files:
            filename = os.path.join(rel_dir, rel_name)
            if (
                (rel_dir.startswith("cv/") and not CurriculumVitae.where(file=filename).exists())
                or (
                    rel_dir.startswith("converted/")
                    and not ConvertedFile.where(file=filename).exists()
                )
                or (
                    rel_dir.startswith("ids/")
                    and not IdentityVerification.where(file=filename).exists()
                    and not Application.where(photo_identity=filename).exists()
                )
                or (
                    rel_dir.startswith("score-sheeets/")
                    and not ScoreSheet.where(file=filename).exists()
                )
                or (
                    rel_dir.startswith("nominations/")
                    and not Nomination.where(file=filename).exists()
                )
                or (
                    rel_dir.startswith("applications/")
                    and not Application.where(file=filename).exists()
                    and not ApplicationDocument.where(file=filename).exists()
                )
                or (
                    rel_dir.startswith("letters_of_support/")
                    and not LetterOfSupport.where(file=filename).exists()
                )
                or (
                    rel_dir.startswith("testimonials/")
                    and not Testimonial.where(file=filename).exists()
                )
                or (
                    rel_dir.startswith("score-sheets/")
                    and not ScoreSheet.where(file=filename).exists()
                )
                or (
                    rel_dir.startswith("statements/")
                    and not EthicsStatement.where(file=filename).exists()
                )
                or (
                    rel_dir.startswith("budget/")
                    and not Application.where(budget=filename).exists()
                )
            ):
                full_filename = os.path.join(root_dir, filename)
                size = os.path.getsize(full_filename)
                if dry_run:
                    os.remove(full_filename)
                print(f"*** Deleted ofphaned file: '{filename}' ({size} bytes)")
                total += size

    if total:
        total = round(total / 1048576, 2)
        print(f"*** Recovered {total}MiB")


class ResearchOffice(Model):
    org = ForeignKey(
        Organisation,
        on_delete=CASCADE,
        verbose_name=_("organisation"),
        related_name="research_offices",
    )
    user = ForeignKey(User, on_delete=CASCADE, related_name="research_offices")

    history = HistoricalRecords(table_name="research_office_history")

    class Meta:
        db_table = "research_office"


PANEL_STATES = Choices(
    ("new", _("new")),
    ("draft", _("draft")),
    ("preliminary", _("preliminary")),
    ("active", _("active")),
    ("archived", _("archived")),
)


class PanelManager(Manager):
    def get_by_natural_key(self, code, fund, state, *args, **kwargs):
        return self.get(code=code, fund=fund, state=state)


class PanelMixin:
    STATES = PANEL_STATES


class Panel(PanelMixin, Model):
    state = StateField(default="new")
    code = CharField(_("code"), max_length=3, blank=True, null=True)
    description = CharField(_("description"), max_length=255, blank=True, null=True)
    fund = ForeignKey("Fund", on_delete=SET_NULL, blank=True, null=True)
    # panellista = models.ManyToManyField(Person, through=Panellist, related_name="panels")

    objects = PanelManager()

    @property
    @admin.display(
        boolean=True,
        ordering="state",
        description="Is active?",
    )
    def is_active(self):
        return self.state and self.state == "active"

    def natural_key(self):
        return (self.code, self.fund_id, self.state)

    def __str__(self):
        return f"{self.code}: {self.description}"

    class Meta:
        db_table = "panel"


simple_history.register(Panel, inherit=True, table_name="panel_history", bases=[PanelMixin, Model])


def add_title_data(apps, schema_editor):
    """
    Add to the migrations:
    migrations.RunPython(portal.models.add_title_data, lambda *args, **kwargs: None),
    """
    Title = apps.get_model("portal", "Title")
    db_alias = schema_editor.connection.alias
    Title.objects.using(db_alias).bulk_create(
        [
            Title(code="MR", name="Mr", name_en="Mr"),
            Title(code="MRS", name="Mrs", name_en="Mrs"),
            Title(code="MS", name="Ms", name_en="Ms"),
            Title(code="DR", name="Dr", name_en="Dr"),
            Title(code="PROF", name="Prof", name_en="Prof"),
        ]
    )


# ORG_ROLE = Choices(
#     # ("SSIG", _("Society signatory")),
#     # ("PM", _("Programme Manager")),
#     # ("ADM", _("Administrator")),
#     # ("RA", _("Research Assessors")),
#     # For external users.
#     ("RO", _("Research Office")),
#     ("OSID", _("Organisation signatory")),
# )


# class UserOrgRole(Model):
#     user = ForeignKey(User, on_delete=CASCADE, related_name="org_roles")
#     org = ForeignKey(Organisation, on_delete=CASCADE, verbose_name=_("organisation"))
#     type = CharField(_("type"), max_length=10, choices=AFFILIATION_TYPES)
#     role = CharField(
#         _("role"),
#         max_length=512,
#         null=True,
#         blank=True,
#         help_text="position or role, e.g., student, postdoc, etc.",
#     )
#     qualification = CharField(
#         _("qualification"), max_length=512, null=True, blank=True
#     )  # , help_text="position or degree")
#     start_date = DateField(_("start date"), null=True, blank=True)
#     end_date = DateField(_("end date"), null=True, blank=True)
#     put_code = PositiveIntegerField(_("put-code"), null=True, blank=True, editable=False)

#     history = HistoricalRecords(table_name="affiliation_history")

#     def __str__(self):
#         if not (self.start_date or self.end_date):
#             return f"{self.org}"
#         if not self.end_date:
#             return f"{self.org}: {self.start_date}"
#         if not self.start_date:
#             return f"{self.org}: until {self.end_date}"
#         return f"{self.org}: {self.start_date} to {self.end_date}"

#     class Meta:
#         db_table = "affiliation"


class ContractKeyword(Model):
    application = ForeignKey("Contract", on_delete=CASCADE)
    keyword = ForeignKey(Keyword, on_delete=CASCADE)

    class Meta:
        db_table = "contract_keyword"


class ContractFor(Model):
    contract = ForeignKey("Contract", on_delete=CASCADE, related_name="contract_fors")
    code = ForeignKey(FieldOfResearch, db_column="code", on_delete=CASCADE, verbose_name="FoR")
    share = PositiveSmallIntegerField(null=True, blank=True, default=None)

    def __str__(self):
        return self.code_id

    class Meta:
        # auto_created = True
        db_table = "contract_for"
        unique_together = (("contract", "code"),)
        verbose_name = _("contract FOR")
        verbose_name_plural = _("contract FoRs")


class ContractSeo(Model):
    contract = ForeignKey("Contract", on_delete=CASCADE, related_name="contract_seos")
    code = ForeignKey(
        SocioEconomicObjective, on_delete=CASCADE, db_column="code", verbose_name="SEO"
    )
    share = PositiveSmallIntegerField(null=True, blank=True, default=None)

    def __str__(self):
        return self.code_id

    class Meta:
        # auto_created = True
        db_table = "contract_seo"
        unique_together = (("contract", "code"),)
        verbose_name = _("contract SEO")
        verbose_name_plural = _("contract SEOs")


class ContractMixin:
    STATES = Choices(
        (None, None),
        ("ASD", _("Awaiting start date")),
        ("COM", _("Completed")),
        ("CUR", _("Current ")),
        ("DCL", _("Declined")),
        ("SUS", _("Suspended")),
        ("TER", _("Terminated")),
        ("TRN", _("Transferred")),
        ("WTH", _("Withdrawn")),
        ("accepted", _("accepted")),
        ("approved", _("approved")),
        ("archived", _("archived")),
        ("cancelled", _("cancelled")),
        ("draft", _("WIP")),
        ("new", _("new")),
        ("preliminary", _("preliminary")),
        ("submitted", _("submitted")),
        # ("withdrawn", _("withdrawn")),
    )


# class ContractState(models.Model):
#     code = FixedCharField(max_length=3, primary_key=True)
#     description = models.CharField(max_length=255, blank=True, null=True)

#     def __str__(self):
#         return f"{self.code}: {self.description}"

#     class Meta:
#         db_table = "contract_state"
#         verbose_name_plural = "contract states"


# def add_contract_state_data(apps, schema_editor):
#     """
#     Add to the migrations:
#     migrations.RunPython(portal.models.add_contract_state_data, lambda *args, **kwargs: None),
#     """
#     ContractState = apps.get_model("portal", "ContractState")
#     db_alias = schema_editor.connection.alias
#     ContractState.objects.using(db_alias).bulk_create(
#         [
#             ContractState(
#                 code="ASD", description="Awaiting start date", description_en="Awaiting start date"
#             ),
#             ContractState(code="COM", description="Completed", description_en="Completed"),
#             ContractState(code="CUR", description="Current ", description_en="Current "),
#             ContractState(code="DCL", description="Declined", description_en="Declined"),
#             ContractState(code="SUS", description="Suspended", description_en="Suspended"),
#             ContractState(code="TER", description="Terminated", description_en="Terminated"),
#             ContractState(code="TRN", description="Transferred", description_en="Transferred"),
#             ContractState(code="WTH", description="Withdrawn", description_en="Withdrawn"),
#         ]
#     )


class ContractManager(CurrentSiteManager):
    def get_by_natural_key(self, number, email, *args, **kwargs):
        return self.get(email=email, contract__number=number)


class Contract(ContractMixin, PersonMixin, PdfFileMixin, Model):
    site = ForeignKey(Site, on_delete=PROTECT, default=Model.get_current_site_id)
    panel = ForeignKey(Panel, on_delete=SET_NULL, null=True, blank=True)
    objects = ContractManager()
    all_objects = Manager()

    number = CharField(_("number"), max_length=40, unique=True)
    refcode = CharField(null=True, blank=True, max_length=40, help_text=_("IE-Contracts REFCODE"))
    year = CharField(max_length=4, blank=True, null=True)
    org = ForeignKey(
        Organisation, on_delete=CASCADE, related_name="contracts", null=True, blank=True
    )
    # proposal = models.ForeignKey(Proposal, on_delete=models.CASCADE, blank=True, null=True)
    application = ForeignKey(
        Application, on_delete=CASCADE, blank=True, null=True, related_name="contracts"
    )

    submitted_by = ForeignKey(
        User, null=True, blank=True, on_delete=SET_NULL, verbose_name=_("submitted by")
    )
    project_title = CharField(
        max_length=200, null=True, blank=True, verbose_name=_("project title")
    )
    state = StateField(default="new", verbose_name=_("state"))

    start_date = DateField(blank=True, null=True)
    end_date = DateField(blank=True, null=True)
    duration = PositiveIntegerField(blank=True, null=True)

    notes = TextField(blank=True, null=True)
    abstract = TextField(blank=True, null=True)
    completed_on = DateField(blank=True, null=True)

    has_animal_use = BooleanField(
        _("has animal use"),
        null=True,
        blank=True,
        help_text=_("Does the proposed research use animals for research or teaching?"),
    )
    is_signatory_to_oa = BooleanField(
        _("is a signatory to the O.A."),
        null=True,
        blank=True,
        help_text=_("Is your institution a signatory to the ANZCCART Openness Agreement?"),
    )
    involves_childeren = BooleanField(
        _("involves children "),
        null=True,
        blank=True,
        help_text=_(
            "Does the research involve and will therefore be subject to Section 19 "
            "of the Vulnerable Children Act 2014?"
        ),
    )
    has_child_protection = BooleanField(
        _("has a child protection policy"),
        null=True,
        blank=True,
        help_text=_("If yes, does your institution have a child protection policy?"),
    )

    rccs = ManyToManyField(Rcc, blank=True, db_table="contract_rcc", related_name="contracts")
    fors = ManyToManyField(
        FieldOfResearch,
        blank=True,
        related_name="contracts",
        through=ContractFor,
        verbose_name="FoRs",
    )
    seos = ManyToManyField(
        SocioEconomicObjective,
        blank=True,
        through=ContractSeo,
        related_name="contracts",
        verbose_name="SEOs",
    )
    keywords = ManyToManyField(
        Keyword,
        verbose_name=_("Keywords"),
        through=ContractKeyword,
        blank=True,
        related_name="contracts",
    )
    fund = ForeignKey(Fund, on_delete=CASCADE, blank=True, null=True)
    # seo_keyword_list = models.CharField(max_length=800, blank=True, null=True)
    # seo_keywords = models.ManyToManyField(
    #     Keyword,
    #     verbose_name="SEO Keywords",
    #     db_table='stage"."contract_seo_keyword',
    #     related_name="+",
    # )
    url = CharField(max_length=120, blank=True, null=True)
    fin_received = BooleanField(blank=True, null=True)
    fin_supp = BooleanField(blank=True, null=True)
    ## code = models.CharField(max_length=3, blank=True, null=True)
    ## panel_code = models.CharField(max_length=3, blank=True, null=True)
    panels = ManyToManyField(
        Panel, blank=True, db_table="contract_panel", related_name="contracts"
    )

    # "ie-contracts"
    ## total_amount = IntegerField(null=True, blank=True)
    ## actual_amount = IntegerField(null=True, blank=True)
    ## currency = IntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.number}: {self.project_title or self.application.application_title or self.application.round.title}"

    def natural_key(self):
        return (self.number,)

    class Meta:
        db_table = "contract"


simple_history.register(
    Contract,
    inherit=True,
    table_name="contract_history",
    bases=[ContractMixin, PersonMixin, PdfFileMixin, Model],
)


class PartMixin:
    STATES = Choices(
        ("accepted", _("accepted")),
        ("approved", _("approved")),
        ("archived", _("archived")),
        ("cancelled", _("cancelled")),
        ("draft", _("WIP")),
        ("new", _("new")),
        ("released", _("released")),
        ("submitted", _("submitted")),
    )


class RequiredPart(TimeStampMixin, HelperMixin, OrderableModel):
    round = ForeignKey(Round, on_delete=CASCADE, related_name="required_parts")
    document_type = ForeignKey(DocumentType, on_delete=CASCADE, related_name="required_parts")
    title = CharField(
        _("Title"), max_length=200, null=True, blank=True, help_text=_("Contract part title")
    )
    is_optional = BooleanField(default=False)
    # min_pages = PositiveSmallIntegerField(null=True, blank=True)
    # max_pages = PositiveSmallIntegerField(null=True, blank=True)

    def __str__(self):
        dt = self.document_type.name
        title = self.title or dt
        if title == dt:
            return title
        return f"{dt}: {title}"

    class Meta(OrderableModel.Meta):
        db_table = "required_part"


class Part(PartMixin, PdfFileMixin, Model):
    contract = ForeignKey(Contract, on_delete=CASCADE, related_name="parts")
    state = StateField(default="new", verbose_name=_("state"))
    document_type = ForeignKey(
        DocumentType, related_name="contract_parts", on_delete=CASCADE, null=True, blank=True
    )
    required_part = ForeignKey(RequiredPart, on_delete=DO_NOTHING, related_name="+")
    page_count = PositiveSmallIntegerField(null=True, blank=True)
    file = PrivateFileField(
        blank=True,
        null=True,
        upload_subfolder=lambda instance: [
            "contract",
            hash_int(instance.application_id),
            hash_int(instance.contract_id),
        ],
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "csv",
                    "ctv",
                    "doc",
                    "docb",
                    "docm",
                    "docx",
                    "dot",
                    "dotm",
                    "dotx",
                    "odm",
                    "odt",
                    "oth",
                    "ott",
                    "pdf",
                    "rtf",
                    "tex",
                    "xls",
                    "xlsb",
                    "xlsm",
                    "xlsx",
                    "xlt",
                    "xltm",
                    "xltx",
                    "xlw",
                    "xml",
                ]
            )
        ],
    )
    converted_file = ForeignKey(
        ConvertedFile, null=True, blank=True, on_delete=SET_NULL, verbose_name=_("converted file")
    )

    def __str__(self):
        return f"{self.document_type}: {os.path.basename(self.file.name)}"

    class Meta:
        db_table = "contract_part"


simple_history.register(
    Part,
    inherit=True,
    table_name="contract_part_history",
    bases=[PartMixin, PdfFileMixin, Model],
)


class ContractMemberManager(Manager):
    def get_by_natural_key(self, number, email, role, *args, **kwargs):
        return self.get(email=emai, role_id=role, contract__number=number)


class ContractMember(PersonMixin, Model):
    """Contract team member."""

    objects = ContractMemberManager()
    all_objects = Manager()

    contract = ForeignKey(Contract, on_delete=CASCADE, related_name="members")
    email = EmailField(max_length=120, null=True, blank=True)
    first_name = CharField(max_length=30, null=True, blank=True)
    middle_names = CharField(
        _("middle names"),
        blank=True,
        null=True,
        max_length=280,
        help_text=_("Comma separated list of middle names"),
    )
    last_name = CharField(max_length=150, null=True, blank=True)
    role = ForeignKey(
        RoleType,
        on_delete=SET_NULL,
        related_name="contract_members",
        null=True,
        blank=True,
        db_column="role",
    )
    # has_authorized = BooleanField(null=True, blank=True)
    user = ForeignKey(User, null=True, blank=True, on_delete=SET_NULL)
    # state = StateField(null=True, blank=True, default="new")
    # state_changed_at = MonitorField(monitor="state", null=True, blank=True, default=None)
    # authorized_at = MonitorField(
    #     monitor="state", when=["authorized"], null=True, blank=True, default=None
    # )
    history = HistoricalRecords(table_name="contract_member_history")

    def natural_key(self):
        return (self.contract.number, self.email, self.role_id)

    @property
    def thread_index(self):
        site_id = self.contract.site_id or settings.SITE_ID
        return base64.b64encode(f"{site_id}:{self.contract_id}".encode()).decode()

    @property
    def thread_topic(self):
        return self.contract.number

    def __getattribute__(self, name):
        if name.startswith("fte_"):
            i = int(name.split("_")[1])
            if me := self.efforts.filter(period=i).first():
                return me.fte
            return None
        return super().__getattribute__(name)

    def clean(self):
        super().clean()
        if not (c := getattr(self, "contract", None)):
            raise ValidationError(_("Missing contract"))
        member_id = getattr(self, "id", None)
        q = c.members.filter(email=self.email)
        if member_id:
            q = q.filter(~Q(id=member_id))
        if q.exists():
            raise ValidationError(
                _("Team member with the email address %(email)s was alrady added"),
                params={"email": self.email},
            )

    def __str__(self):
        return self.full_name_with_email

    class Meta:
        unique_together = (("contract", "email", "role"),)
        db_table = "contract_member"


class ContractMemberEffort(Model):
    member = ForeignKey(ContractMember, on_delete=CASCADE, related_name="efforts")
    period = PositiveSmallIntegerField()
    fte = DecimalField(
        _("FTE"), help_text=_("Full-Time Equivalent"), max_digits=3, decimal_places=2
    )

    history = HistoricalRecords(table_name="contract_member_effort_history")

    class Meta:
        db_table = "contract_member_effort"
        unique_together = ["member", "period"]


class Allocation(Model):
    contract = ForeignKey(Contract, on_delete=CASCADE, related_name="allocations")
    period = PositiveSmallIntegerField(_("period"))
    allocation = DecimalField(_("allocation"), max_digits=15, decimal_places=2)

    history = HistoricalRecords(table_name="allocation_history")

    class Meta:
        db_table = "allocation"
        unique_together = (("contract", "period"),)


class ReportingScheduleEntryMixin:
    STATES = Choices(
        ("accepted", _("accepted")),
        ("acknowledged", _("acknowledged")),
        ("approved", _("approved")),
        ("archived", _("archived")),
        ("cancelled", _("cancelled")),
        ("draft", _("draft")),
        ("new", _("new")),
        ("submitted", _("submitted")),
        # ("withdrawn", _("withdrawn")),
    )


class ReportingScheduleEntry(ReportingScheduleEntryMixin, Model):
    # recno = models.AutoField(primary_key=True)
    contract = ForeignKey(Contract, on_delete=CASCADE, related_name="reporting_schedule")
    # number = models.CharField(unique=True, max_length=255)
    period = PositiveSmallIntegerField(_("period"))
    type = FixedCharField(
        max_length=1,
        choices=Choices(
            ("A", _("Annual")),
            ("E", _("Exchange")),
            ("F", _("Final")),
            ("I", _("Interim")),
            ("L", _("Follow up")),
        ),
        help_text=_("Reporting Type"),
    )
    due_date = DateField(blank=True, null=True)
    request_info_date = DateField(
        blank=True,
        null=True,
        help_text=_("Date that RO/applicants is first emailed for more information"),
    )
    date_first_remind = DateField(blank=True, null=True)
    state = StateField(default="new", verbose_name=_("state"))
    acknowledged_at = MonitorField(
        monitor="state", when=["acknowledged"], null=True, blank=True, default=None
    )

    # reported = models.BooleanField(blank=True, null=True)
    # reported_date = models.DateField(blank=True, null=True)
    # assessed = models.BooleanField(blank=True, null=True)
    # assessed_date = models.DateField(blank=True, null=True)
    # exported = models.BooleanField(blank=True, null=True)
    # exported_date = models.DateField(blank=True, null=True)
    # assessor = models.CharField(max_length=255, blank=True, null=True)
    # email_acknowledgement = models.CharField(max_length=255, blank=True, null=True)
    # is_confidential = models.BooleanField(default=False, blank=True, null=True)
    # is_highlighted = models.BooleanField(default=False, blank=True, null=True)
    # notes = models.TextField(blank=True, null=True)
    # notes2 = models.TextField(blank=True, null=True)
    # duration = models.IntegerField(blank=True, null=True)

    class Meta:
        db_table = "reporting_schedule_entry"
        unique_together = (("contract", "period", "type", "due_date"),)


simple_history.register(
    ReportingScheduleEntry,
    inherit=True,
    table_name="reporting_schedule_entry_history",
    bases=[ReportingScheduleEntryMixin, Model],
)


dummy_for_translations = (
    _("Browse"),
    _("Currently"),
    _("Change"),
    _("More"),
    _("Ooops!!! 500"),
    _("Read"),
    _("State"),
    _("Value"),
    _("browse"),
    _("next"),
    _("previous"),
    _("state"),
    _("value"),
)

# vim:set ft=python.django:
