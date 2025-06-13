import base64
import email
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
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import cache, cached_property, lru_cache, partial, wraps
from itertools import groupby
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pikepdf
import simple_history
from admin_ordering.models import OrderableModel
from allauth.account.models import EmailAddress
from colorfield.fields import ColorField
from dateutil.parser import parse
from dateutil.relativedelta import relativedelta
from django.apps import apps
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.sites.managers import CurrentSiteManager
from django.contrib.sites.models import Site
from django.contrib.staticfiles import finders
from django.core.exceptions import ValidationError
from django.core.files.base import File
from django.core.validators import (
    FileExtensionValidator,
    MaxValueValidator,
    MinValueValidator,
    RegexValidator,
)
from django.db import connection, transaction
from django.db.models import (
    CASCADE,
    DO_NOTHING,
    PROTECT,
    RESTRICT,
    SET_NULL,
    BooleanField,
    Case,
    CharField,
    Count,
    DateField,
    DateTimeField,
    DecimalField,
    F,
    FileField,
    FloatField,
    ForeignKey,
    IntegerField,
    Manager,
    ManyToManyField,
    Min,
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
    aggregates,
    prefetch_related_objects,
)
from django.db.models.functions import Cast, Coalesce, Lower
from django.http import HttpRequest
from django.template.loader import get_template
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import get_language, gettext
from django.utils.translation import gettext_lazy as _
from django_fsm import FSMField, FSMFieldMixin, transition
from django_fsm_log.helpers import FSMLogDescriptor
from django_fsm_log.models import StateLog
from limesurveyrc2api.exceptions import LimeSurveyError
from limesurveyrc2api.limesurvey import LimeSurvey
from model_utils import Choices
from model_utils.fields import MonitorField, StatusField
from ooopy import Transforms
from ooopy.OOoPy import OOoPy
from ooopy.Transformer import Transformer
from private_storage.fields import PrivateFileField
from pypdf import PdfMerger, PdfReader, PdfWriter
from pypdf.errors import PdfReadError
from sentry_sdk import capture_exception, capture_message
from simple_history.models import HistoricalRecords
from simple_history.utils import bulk_update_with_history
from taggit.managers import TaggableManager
from taggit.models import GenericTaggedItemBase, Tag, TagBase
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
    domain_to_macrons,
)

from .utils import send_mail, vignere

EMAIL_EX = r"([A-Za-z0-9]+[.-_+])*[A-Za-z0-9]+@[A-Za-z0-9-]+(\.[A-Z|a-z]{2,})+"
CONTRACT_PART_EXTENSIONS = [
    "html",
    "pdf",
    "fodt",
    "odt",
    "ott",
    "oth",
    "odm",
    "doc",
    "docx",
    "docm",
    "docb",
]
round_number = round


def pdf_toc(reader: PdfReader) -> dict[str, int]:

    def flat_outline(outline, level=1):
        """returns list of tuples (tile, level, page)."""
        if level < 3:  # don't go deeper than level 2
            for o in outline:
                if isinstance(o, list):
                    yield from flat_outline(o, level + 1)
                else:
                    yield (o["/Title"], level, o["/Page"])

    return {
        title: i
        for title, level, page in flat_outline(reader.outline)
        for i, p in enumerate(reader.pages)
        if p == page
    }


class CurrentSiteManager(CurrentSiteManager):
    """Select all entries if SITE_ID==0."""

    def get_queryset(self):
        if bool(settings.SITE_ID):
            return super().get_queryset()
        return super(Manager, self).get_queryset()


def __(s):
    """Temporarily disabale 'gettex'"""
    return s


def site_contact_email(site_id=None):
    if site_id == 4 or settings.SITE_ID == 4:
        return "puanga@royalsociety.org.nz"
    elif site_id in [2, 5] or settings.SITE_ID in [2, 5]:
        return "tawhia@royalsociety.org.nz"
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


class CommentMixin:

    def import_email(
        self, file, file_name=None, notify_author=True, request=None, by=None, reply_to=None
    ):
        if isinstance(file, io.BytesIO):
            msg = email.message_from_binary_file(file)
        else:
            msg = email.message_from_file(file)

        to = msg["to"]
        subject = msg["subject"]
        sender = msg["from"]
        sent_at = (
            msg["date"] and email.utils.parsedate_to_datetime(msg["date"]) or timezone.now()
        ).replace(tzinfo=None)
        if sender and (match := re.search(EMAIL_EX, sender)):
            sender = match[0].lower()
        # from_addresses = []

        by = (
            User.where(Q(email=sender) | Q(emailaddress__email=sender)).first()
            or by
            or request
            and request.user
        )

        body = msg["body"]
        if not msg.is_multipart():
            body = msg.get_payload(decode=True)
        else:
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "multipart/alternative":
                    for p in part.get_payload():
                        body = p.get_payload(decode=True)
                        if p.get_content_type() == "text/html":
                            break

        attachments = [
            File(io.BytesIO(a.as_bytes()), name=a.get_filename())
            for a in msg.walk()
            if a.get_filename()
        ]

        def message_ids(msg):
            headers = [
                "in-reply-to",
                "original-message-id",
                "x-ms-exchange-parent-message-id",
                "message-id",
            ]
            for h in headers:
                v = msg[h]
                if v:
                    yield v
            for p in msg.walk():
                for f in headers:
                    v = p[h]
                    if v:
                        yield v

        if by or body:
            token = get_unique_mail_token()
            if body:
                for encoding in ["utf-8", "iso-8859-4"]:
                    try:
                        body = body.decode(encoding)
                        break
                    except:
                        pass
            if not reply_to:
                for message_id in message_ids(msg):
                    reply_to = self.comments.model.where(token=message_id).last()
                    if reply_to:
                        break
            if isinstance(self, ChangeRequest):
                kwargs = {"change_request": self}
            elif isinstance(self, Report):
                kwargs = {"report": self}
            elif isinstance(self, Contract):
                kwargs = {"contract": self}
            else:
                kwargs = {"report": self}

            try:
                comment = self.comments.model.create(
                    submitted_by=by,
                    comment=body,
                    token=token,
                    reply_to=reply_to,
                    created_at=sent_at,
                    subject=subject,
                    **kwargs,
                    # attachment=attachments and attachments[0] or None,
                )
                comment.recipients.model.create(
                    comment=comment,
                    user=reply_to and reply_to.submitted_by or self.pi,
                    email=(
                        reply_to.submitted_by.email
                        if reply_to and reply_to.submitted_by
                        else self.pi.email
                    )
                    or by
                    and by.email,
                )

                attachments.append(
                    File(
                        io.BytesIO(msg.as_bytes()), name=file_name or f"{hash_int(comment.pk)}.eml"
                    )
                )

                # for a in attachments[1:]:
                for a in attachments:
                    ca = comment.attachments.model(comment=comment)
                    ca.attachment.save(content=a, name=a.name)
                    ca.save()

                domain = to.split("@")[1]
                recipients = [reply_to and reply_to.submitted_by or self.pi]
                if isinstance(self, Report):
                    respond_url = f"https://{domain}{reverse('report-update', kwargs=dict(pk=self.pk))}#correspondence"
                else:
                    respond_url = f"https://{domain}{reverse('contract-update', kwargs=dict(pk=self.pk))}#correspondence"
                html_message = f'<p>Comment posted by {by.full_name_with_email} to <data value="{self}">{self}</data>'
                html_message += f":</p>{body}" if body else "."
                html_message += f'<hr/>To respond to this message, please, click here: <a href="{respond_url}">REPLY</a>'
                site = getattr(self, "site", None) or Site.objects.get_current()

                send_mail(
                    from_email="reports" if isinstance(self, Report) else "contracts",
                    subject=f"Comment posted by {by.full_name_with_email} to {self}",
                    html_message=html_message,
                    cc=by and [by.full_email_address],
                    attachments=attachments or None,
                    recipients=recipients,
                    thread_index=self.thread_index,
                    thread_topic=self.thread_topic,
                    token=token,
                    request=request,
                    site=site,
                )
                return comment

            except Exception as ex:
                capture_exception(ex)
                raise

    @property
    def attached_files(self):
        if isinstance(self, ChangeRequest):
            kwargs = {"comment__change_request_id": self.pk}
        else:
            kwargs = {f"comment__{self.model_name}_id": self.pk}

        attachments = [
            (a.created_at, a.attachment)
            for a in self.comments.model.attachments.rel.related_model.objects.filter(
                **kwargs
                # comment__change_request_id=self.pk
            )
        ]
        attachments.extend(
            (a.created_at, a.attachment) for a in self.comments.filter(~Q(attachment=""))
        )
        if attachments:
            sorted(attachments, key=lambda a: a[0])
        return attachments


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
                if hasattr(self, "page_count") and not self.page_count:
                    with open(self.file.path, "rb") as f:
                        pdf_reader = PdfReader(f, strict=False)
                        self.page_count = len(pdf_reader.pages)
                        self._change_reason = f"Updated page count to {self.page_count}"
                        self.save(update_fields=["page_count"])
                return self.file
            if not self.converted_file:
                self.update_converted_file(commit=True)
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
            "TITLES": (
                [
                    f"{self.required_document}" f"{self.filename}",
                ]
                if hasattr(self, "required_document")
                else [
                    f"{_('Attachment')} - {self.__class__.__name__}",
                    self,
                    f"({self.filename})",
                ]
            ),
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

    def update_page_count(self, file=None):

        if not file:
            if self.file:
                if self.file.name.lower().endswith(".pdf"):
                    file = self.file.path
                elif self.converted_file:
                    file = self.converted_file.file.path
                else:
                    cf = self.update_converted_file()
                    return cf.page_count
            else:
                return

        if hasattr(self, "page_count"):
            if isinstance(file, str):
                with open(file, "rb") as f:
                    pdf_reader = PdfReader(f, strict=False)
                    page_count = len(pdf_reader.pages)
            else:
                pdf_reader = PdfReader(file, strict=False)
                page_count = len(pdf_reader.pages)

            if not self.page_count or pdf_reader and page_count != self.page_count:
                self.page_count = page_count
            return page_count

    def update_converted_file(self, commit=False):
        """If the attached file is not PDF convert and update the PDF version."""

        if not self.file or (
            (file_ext := Path(self.file.path).suffix)
            and file_ext.lower() == ".pdf"
            and self.converted_file
        ):
            # NB! easy-audit doens't deal well with delete within transition:
            # if (cf := self.converted_file) and cf.pk and commit:
            #     self.converted_file.delete()
            self.converted_file = None

            if hasattr(self, "page_count"):
                if self.file and self.file.name:
                    self.update_page_count(self.file.path)
                else:
                    self.page_count = 0

            if commit:
                self._change_reason = "Converted file and page count updated"
                self.save(
                    update_fields=(
                        ["converted_file", "page_count"]
                        if hasattr(self, "page_count")
                        else ["converted_file"]
                    )
                )

            return

        file_ext = file_ext.lower()
        if self.file.name and file_ext != ".pdf":
            cp = subprocess.run(
                [
                    (
                        "lowriter"
                        if file_ext
                        in [".odt", ".ott", ".oth", ".odm", ".doc", ".docx", ".docm", ".docb"]
                        else (
                            "localc"
                            if file_ext
                            in [
                                ".xls",
                                ".xlw",
                                ".xlt",
                                ".xml",
                                ".xlsx",
                                ".xlsm",
                                ".xltx",
                                ".xltm",
                                ".xlsb",
                                ".csv",
                                ".ctv",
                            ]
                            else "loffice"
                        )
                    ),
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
                of.seek(0)
                pdf_reader = PdfReader(of, strict=False)
                page_count = len(pdf_reader.pages)
                if hasattr(self, "page_count") and getattr(self, "page_count", 0) != page_count:
                    self.page_count = page_count
                cf.page_count = len(pdf_reader.pages)
                of.seek(0)
                cf.save()

            self.converted_file = cf

            if commit:
                self._change_reason = "Converted file and page count updated"
                self.save(
                    update_fields=(
                        ["converted_file", "page_count"]
                        if hasattr(self, "page_count")
                        else ["converted_file"]
                    )
                )

            return cf

    @classmethod
    def refresh_page_counts(cls, commit=True, queryset=None):
        changed_objects = []
        for obj in (queryset or getattr(cls, "all_objects", None) or cls.objects).all():
            if hasattr(obj, "page_count"):
                try:
                    page_count = obj.page_count
                    if page_count != obj.update_page_count():
                        changed_objects.append(obj)
                except Exception as e:
                    # capture_message(e)
                    print(f"Failing to update page count for {obj}: {e}")
                    pass

        if changed_objects and commit:
            cls.objects.bulk_update(changed_objects, ["page_count"])

        return len(changed_objects)


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
    return hashlib.shake_256(f"{value}".encode()).hexdigest(5)


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


class Country(Model):
    code = FixedCharField(max_length=2, primary_key=True)
    code3 = FixedCharField(max_length=3, unique=True)
    name = CharField(max_length=255, blank=True, null=True)
    num = FloatField(blank=True, null=True)
    itu = CharField(max_length=255, blank=True, null=True)
    fips = CharField(max_length=255, blank=True, null=True)
    ioc = CharField(max_length=255, blank=True, null=True)
    fifa = CharField(max_length=255, blank=True, null=True)
    ds = CharField(max_length=255, blank=True, null=True)
    wmo = CharField(max_length=255, blank=True, null=True)
    gaul = FloatField(blank=True, null=True)
    marc = CharField(max_length=255, blank=True, null=True)
    dial = CharField(max_length=255, blank=True, null=True)
    independent = CharField(max_length=255, blank=True, null=True)

    history = HistoricalRecords(table_name="country_history")

    def __str__(self):
        return f"{self.code}/{self.code3}: {self.name}"

    class Meta:
        db_table = "country"
        verbose_name_plural = _("countries")


class Address(Model):

    address = TextField(_("address"))
    postcode = CharField(_("postcode"), max_length=12, null=True, blank=True)
    region = CharField(
        _("region"), max_length=100, null=True, blank=True, help_text=_("Region, State or County")
    )
    city = CharField(_("city"), max_length=42, null=True, blank=True)
    country = ForeignKey(
        Country,
        verbose_name=_("country"),
        db_column="country",
        on_delete=PROTECT,
        null=True,
        blank=True,
        related_name="addresses",
        default="NZ",
    )

    history = HistoricalRecords(table_name="address_history")

    @lru_cache(1)
    def __str__(self):
        address = self.address
        if self.city and self.city not in address:
            address = f"{address}\n{self.city}"
        if self.postcode and self.postcode not in address:
            address = f"{address} {self.postcode}"
        if (
            self.country_id
            and self.country_id != "NZ"
            and (n := self.country.name)
            and n not in address
        ):
            address = f"{address}\n{n}"

        return address

    @lru_cache(1)
    def __html__(self):
        return "<br>".join(self.__str__().split("\n")) or ""

    class Meta:
        db_table = "address"
        verbose_name_plural = _("addresses")


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
    ("EC", _("Eligibility Criteria")),
    ("F", _("Form")),
    ("HS", _("Host Suitability")),
    ("PB", _("Proposal Budget")),
    ("PT", _("Project Timeline")),
)


class DocumentType(Model):
    # site = ForeignKey(Site, on_delete=PROTECT, default=Model.get_current_site_id)
    # objects = CurrentSiteManager()
    role = CharField(max_length=10, choices=DOCUMENT_ROLES, null=True, blank=True)
    name = CharField(_("Name"), max_length=200)
    format = CharField(
        choices=Choices(("I", _("Image")), ("S", _("Spreadsheet")), ("T", _("Text"))),
        default="T",
        max_length=1,
    )

    def __str__(self):
        if self.name:
            return f"{self.role}: {self.name}"
        return f"{self.role}: {self.get_role_display()}"

    class Meta:
        db_table = "document_type"


class RoleType(TimeStampMixin, HelperMixin, OrderableModel):
    code = FixedCharField(primary_key=True, max_length=2)
    role_code = PositiveSmallIntegerField(null=True, blank=True, help_text="SYS_ROLES.ROLECODE")
    role_type = CharField(max_length=20, blank=True, null=True, help_text="SYS_ROLES.ROLETYPE")
    role_name = CharField(max_length=255, blank=True, null=True, help_text="SYS_ROLES.ROLENAME")
    name = CharField(max_length=255, blank=True, null=True)
    description = CharField(max_length=255, blank=True, null=True)
    for_application = BooleanField(_("Available for application stage"), default=True)
    for_contracting = BooleanField(_("Available for contracting stage"), default=True)
    is_key_person = BooleanField(
        _("Is Key Person"),
        default=True,
        help_text="The role will be included in the contract key personnel list",
    )

    def __str__(self):
        return f"{self.code}: {self.name}"

    class Meta(OrderableModel.Meta):
        db_table = "role_type"
        # ordering = ["code"]


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

    def natural_key(self):
        return self.code

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

    def natural_key(self):
        return self.code

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


class PersonCareerStage(Model):
    person = ForeignKey("Person", on_delete=CASCADE)
    career_stage = ForeignKey(CareerStage, on_delete=CASCADE, verbose_name=_("career stage"))
    year_achieved = PositiveSmallIntegerField(
        _("year achieved"),
        null=True,
        blank=True,
        validators=[MinValueValidator(1900), MaxValueValidator(2100)],
        help_text=_("Year that you first attained the career stage"),
    )

    class Meta:
        db_table = "person_career_stage"


ORCID_ID_REGEX = re.compile(r"^([X\d]{4}-?){3}[X\d]{4}$")

phone_regex_validator = RegexValidator(
    regex=r"\+?[0123456789 ]{9,15}$",
    message=_(
        "Phone number must be entered in the format: '+999999999'. Up to 15 digits allowed: %(value)s."
    ),
)


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


class PersonPersonIdentifier(Model):
    person = ForeignKey("Person", on_delete=CASCADE, related_name="person_identifiers")
    code = ForeignKey(
        PersonIdentifierType,
        on_delete=DO_NOTHING,
        verbose_name=_("type"),
        help_text=_("Choose a type or enter a new identifier or reference type"),
    )
    value = CharField(_("Identifier or reference (e.g. reference/ID number)"), max_length=100)
    put_code = PositiveIntegerField(_("put-code"), null=True, blank=True, editable=False)

    class Meta:
        db_table = "person_person_identifier"

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
    # history = HistoricalRecords(table_name="qualification_history")

    def __str__(self):
        # if self.code:
        #     return f"{self.code}: {self.description}"
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
    is_active = BooleanField(default=True)

    legal_name = CharField(max_length=255, blank=True, null=True)
    alt_name = CharField(max_length=100, blank=True, null=True)
    grid = CharField(max_length=30, blank=True, null=True)
    ror = CharField(max_length=25, blank=True, null=True)
    gst = CharField(max_length=11, blank=True, null=True)
    nzbn = CharField(max_length=13, blank=True, null=True)
    nz_ris_type = CharField(max_length=4, blank=True, null=True)

    # address = TextField(blank=True, null=True)
    # city = CharField(max_length=255, blank=True, null=True)
    # country = ForeignKey(
    #     Country,
    #     db_column="country",
    #     on_delete=CASCADE,
    #     blank=True,
    #     null=True,
    #     related_name="organisations",
    # )
    address = ForeignKey(
        Address, blank=True, null=True, related_name="organisations", on_delete=RESTRICT
    )
    contact = CharField(
        _("Contact"),
        max_length=200,
        blank=True,
        null=True,
        help_text=_("Contact - an organisational role or a person name"),
    )
    contact_phone = CharField(
        _("Contact phone number"),
        validators=[phone_regex_validator],
        max_length=24,
        blank=True,
        null=True,
    )
    email = EmailField(_("Contracting contact email address"), blank=True, null=True)
    ro_email = EmailField(
        _("RO email address"), help_text=_("Research office email address"), blank=True, null=True
    )
    # ro_email = EmailField(
    #     _("Research Office email address"),
    #     blank=True,
    #     null=True,
    #     help_text="Research Office common email address",
    # )
    signatory = ForeignKey(
        "Person",
        verbose_name=_("signatory"),
        on_delete=PROTECT,
        related_name="signatory_for",
        blank=True,
        null=True,
        limit_choices_to={"affiliations__type": "EMP"},
    )
    # signatory_position = CharField(_("signatory position"), max_length=255, blank=True, null=True)
    notes = TextField(blank=True, null=True)
    website = URLField(max_length=255, blank=True, null=True)
    history = HistoricalRecords(table_name="organisation_history")

    @cached_property
    def signatory_position(self):
        return (
            (
                a := self.signatory.affiliations.filter(
                    type="EMP", org=self, end_date__isnull=True
                )
                .order_by("-start_date")
                .first()
            )
            and a.role
            or _("N/A")
        )

    @cache
    def get_ro(self):
        if self.ro_email:
            return [self.ro_email]
        return [ro.user for ro in self.research_offices.all()]

    def natural_key(self):
        return self.code

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

    @classmethod
    def search_query(cls, term, queryset=None, nominator=None, user=None):
        """Organisation search query for autocomplete and select2."""
        # def get_queryset(self):
        q = queryset or cls.objects.all()
        if nominator:
            q = q.filter(Q(research_offices__user_id=nominator))
        if user:
            q = q.filter(Q(affiliations__person__user=user, affiliations__end_date__isnull=True))
        if term:
            s = term.lower()
            s0 = s.split(" ")
            if s0[0] == "the":
                s0 = " ".join(s0[1:0]).strip() or f"the {s}"
            else:
                s0 = f"the {s}"
            q = q.filter(Q(name__istartswith=s) | Q(name__istartswith=s0))
            q = (
                q.filter(
                    Q(
                        id__in=cls.where(Q(name__istartswith=s) | Q(name__istartswith=s0))
                        .values("name")
                        .annotate(Min("id"))
                        .values("id__min")
                    )
                )
                # .order_by("name", "id")
                .values_list("id", "name")
            )
            q = q.union(
                OrgName.where(
                    Q(Q(name__istartswith=s) | Q(name__istartswith=s0)),
                    Q(
                        org_id__in=OrgName.where(Q(name__istartswith=s) | Q(name__istartswith=s0))
                        .values("name")
                        .annotate(Min("org_id"))
                        .values("org_id__min")
                    ),
                ).values_list("org_id", "name")
            )
            # q = (
            #     q.distinct()
            #     if django.db.connection.vendor == "sqlite"
            #     else q.distinct("id", "name")
            # )
        else:
            q = q.filter(
                id__in=cls.objects.all().values("name").annotate(Min("id")).values("id__min")
            ).values_list("id", "name")
        return q.order_by("name")

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
    person = ForeignKey("Person", on_delete=CASCADE, related_name="affiliations")
    org = ForeignKey(
        Organisation,
        on_delete=CASCADE,
        verbose_name=_("organisation"),
        related_name="affiliations",
    )
    type = CharField(
        _("type"),
        max_length=10,
        choices=AFFILIATION_TYPES,
        db_comment="\n".join(f"{k}: {v}" for (k, v) in AFFILIATION_TYPES),
    )
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
    email = EmailField(max_length=120, verbose_name=_("email address"), blank=True, null=True)

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


class Person(PersonMixin, Model):
    user = OneToOneField(
        User,
        on_delete=SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("user"),
        related_name="person",
    )
    code = CharField(max_length=8, unique=True, blank=True, null=True)
    email = CharField(max_length=60, blank=True, null=True)
    orcid = CharField(max_length=20, blank=True, null=True)
    title = ForeignKey(
        Title,
        null=True,
        blank=True,
        verbose_name=_("title"),
        db_column="title",
        on_delete=DO_NOTHING,
    )
    initials = CharField(max_length=15, blank=True, null=True)
    first_name = CharField(max_length=30, blank=True, null=True)
    last_name = CharField(max_length=50, blank=True, null=True)
    middle_names = CharField(
        _("middle names"),
        blank=True,
        null=True,
        max_length=280,
    )
    salutation = CharField(max_length=100, blank=True, null=True)
    other_names = CharField(max_length=200, blank=True, null=True)
    friendly_name = CharField(max_length=50, blank=True, null=True)
    label_name = CharField(max_length=120, blank=True, null=True)
    gender = PositiveSmallIntegerField(
        _("gender"),
        choices=GENDERS,
        null=True,
        blank=False,
        default=0,
        db_comment="\n".join(f"{k}: {v}" for (k, v) in GENDERS),
    )
    date_of_birth = DateField(_("date of birth"), null=True, blank=True, validators=[validate_bod])
    ethnicities = ManyToManyField(
        Ethnicity, db_table="person_ethnicity", blank=True, verbose_name=_("ethnicities")
    )
    # is_ethnicities_completed = BooleanField(default=True)
    # CharField(max_length=20, null=True, blank=True, choices=ETHNICITIES)
    education_level = PositiveSmallIntegerField(
        _("education level"),
        null=True,
        blank=True,
        choices=QUALIFICATION_LEVEL,
        db_comment="\n".join(f"{k}: {v}" for (k, v) in QUALIFICATION_LEVEL),
    )
    employment_status = PositiveSmallIntegerField(
        _("employment status"),
        null=True,
        blank=True,
        choices=EMPLOYMENT_STATUS,
        db_comment="\n".join(f"{k}: {v}" for (k, v) in EMPLOYMENT_STATUS),
    )
    # years since arrival in New Zealand
    primary_language_spoken = CharField(
        _("primary language spoken"), max_length=40, null=True, blank=True, choices=LANGUAGES
    )
    languages_spoken = ManyToManyField(
        Language, db_table="person_language", blank=True, verbose_name=_("languages spoken")
    )
    iwi_groups = ManyToManyField(
        IwiGroup, db_table="person_iwi_group", blank=True, verbose_name=_("iwi groups")
    )
    # is_iwi_groups_completed = BooleanField(default=True)
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
        CareerStage, blank=True, through="PersonCareerStage", verbose_name=_("career stages")
    )
    # is_career_stages_completed = BooleanField(default=False)
    external_ids = ManyToManyField(
        PersonIdentifierType,
        blank=True,
        through="PersonPersonIdentifier",
        verbose_name=_("external IDs"),
    )
    # affiliations = ManyToManyField(Organisation, blank=True, through="Affiliation")

    # is_external_ids_completed = BooleanField(default=False)

    activity = FixedCharField(
        max_length=2, blank=True, null=True, choices=Choices("CE", "CO", "CP", "CU", "CW")
    )
    address = ForeignKey(Address, blank=True, null=True, on_delete=RESTRICT, related_name="people")
    # source = models.ForeignKey(
    #     Source, on_delete=models.SET_NULL, blank=True, null=True, related_name="people"
    # )
    # source_code = models.CharField(max_length=3, blank=True, null=True)
    # institution = models.CharField(max_length=120, blank=True, null=True)
    # department = models.CharField(max_length=120, blank=True, null=True)
    # position = models.CharField(max_length=80, blank=True, null=True)

    # address = models.TextField(blank=True, null=True, editable=False)
    # delivery = models.TextField(blank=True, null=True, editable=False)
    # postal_address = models.TextField(blank=True, null=True, editable=False)
    # home_address = models.TextField(blank=True, null=True, editable=False)
    # city = models.CharField(max_length=100, blank=True, null=True, editable=False)
    # country_name = models.CharField(max_length=200, blank=True, null=True, editable=False)
    # country = models.ForeignKey(
    #     Country,
    #     db_column="country",
    #     on_delete=models.CASCADE,
    #     blank=True,
    #     null=True,
    #     related_name="+",
    #     editable=False,
    # )
    # postcode = models.CharField(max_length=40, blank=True, null=True, editable=False)

    # phone = models.CharField(max_length=20, blank=True, null=True, editable=False)
    # fax = models.CharField(max_length=20, blank=True, null=True, editable=False)
    # phone_pvt = models.CharField(max_length=20, blank=True, null=True, editable=False)
    # work_phone = models.CharField(max_length=120, blank=True, null=True, editable=False)
    # extension = models.CharField(max_length=5, blank=True, null=True, editable=False)
    # home_phone = models.CharField(max_length=80, blank=True, null=True, editable=False)
    # mobile_phone = models.CharField(max_length=80, blank=True, null=True, editable=False)

    # active = models.BooleanField()
    # notes = models.TextField(blank=True, null=True)
    # publish = models.BooleanField()
    # rcc_comment = models.TextField(blank=True, null=True, verbose_name="RCC comments")

    # maori_descent = models.BooleanField(null=True, blank=True)
    # year_hipd = models.IntegerField(blank=True, null=True)
    # year_hipd_since = models.IntegerField(blank=True, null=True)
    # marsden_newsletter = models.BooleanField(null=True, blank=True)
    # year_added = models.IntegerField(blank=True, null=True)
    # use_when = models.CharField(max_length=20, blank=True, null=True)
    # url = models.CharField(max_length=150, blank=True, null=True)
    # date_added = models.DateField(blank=True, null=True)
    # date_changed = models.DateField(blank=True, null=True)
    # ref_update_request = models.BooleanField(null=True, blank=True)
    # date_update_request = models.DateField(blank=True, null=True)
    # rccs = models.ManyToManyField("Rcc", through=PersonRcc, verbose_name="RCCs")
    # fors = models.ManyToManyField("FieldOfResearch", through=PersonFor, verbose_name="FORs")
    # ethnicities = models.ManyToManyField("Ethnicity", through=PersonEthnicity)
    # iwies = models.ManyToManyField(Iwi, through=PersonIwi)

    # phd_date = models.DateField(blank=True, null=True)
    # phd_years_since = models.IntegerField(blank=True, null=True)
    # phd_exemption_requested = models.BooleanField(blank=True, null=True, default=False)
    # phd_exemption_granted = models.BooleanField(blank=True, null=True, default=False)
    # phd_exemption_reason = models.TextField(blank=True, null=True)

    # residency_status = models.CharField(max_length=32, blank=True, null=True)
    # residency_years = models.IntegerField(blank=True, null=True)
    # degree_year = models.CharField(max_length=16, blank=True, null=True)

    # affiliations = models.ManyToManyField(Source, blank=True, through="Affiliation")

    history = HistoricalRecords(table_name="person_history")
    has_protection_patterns = BooleanField(default=True)
    account_approval_message_sent_at = DateTimeField(null=True, blank=True, editable=False)

    def natural_key(self):
        return self.user.username

    @property
    def employments(self):
        return self.affiliations.filter(type="EMP")

    # is_employments_completed = BooleanField(default=False)

    @property
    def educations(self):
        return self.affiliations.filter(type="EDU")

    # is_professional_bodies_completed = BooleanField(default=False)

    # is_academic_records_completed = BooleanField(default=False)
    # is_recognitions_completed = BooleanField(default=False)
    # is_professional_memberships_completed = BooleanField(default=False)
    # is_cvs_completed = BooleanField(default=False)

    @property
    def protection_patterns(self):
        return ProtectionPatternPerson.get_data(self)

    @cache
    def __str__(self):
        if u := self.user:
            value = (
                f"{u.name} ({u.username})"
                if u.name and u.username
                else f"{u.name or u.username or u.email}"
            )
            if self.code:
                return f"{self.code}: {value}"
            return value
        value = self.full_name_with_title
        if value:
            if self.code:
                return f"{self.code}: {value}"
            return value
        return self.code or self.email or self.orcid

    def save(self, *args, **kwargs):
        created = not self.pk
        super().save(*args, **kwargs)
        if created:
            PersonProtectionPattern.objects.bulk_create(
                [
                    PersonProtectionPattern(person=self, protection_pattern_id=code)
                    for code in [5, 6]
                ]
            )

    def get_absolute_url(self):
        return reverse("profile-instance", kwargs={"pk": self.pk})

    # @property
    # def is_completed(self):
    #     return (
    #         self.is_career_stages_completed
    #         and self.is_employments_completed
    #         and self.is_ethnicities_completed
    #         and self.is_professional_bodies_completed
    #         and self.is_recognitions_completed
    #         and self.is_iwi_groups_completed
    #         and self.is_external_ids_completed
    #         and self.is_cvs_completed
    #         and self.is_accepted
    #     )

    # @is_completed.setter
    # def is_completed(self, value):
    #     self.is_career_stages_completed = value
    #     self.is_professional_bodies_completed = value
    #     self.is_employments_completed = value
    #     self.is_ethnicities_completed = value
    #     self.is_recognitions_completed = value
    #     self.is_iwi_groups_completed = value
    #     self.is_external_ids_completed = value
    #     self.is_cvs_completed = value
    #     self.is_accepted = value

    class Meta:
        db_table = "person"


class PersonCode(Model):

    person = ForeignKey(Person, on_delete=CASCADE, related_name="previous_codes")
    code = CharField(max_length=8)

    class Meta:
        db_table = "person_code"


class PersonProtectionPattern(Model):
    person = ForeignKey(Person, on_delete=CASCADE, related_name="person_protection_patterns")
    protection_pattern = ForeignKey(
        ProtectionPattern,
        on_delete=CASCADE,
        related_name="person_protection_patterns",
        verbose_name=_("protection pattern"),
    )
    expires_on = DateField(_("expires on"), null=True, blank=True)

    def __str__(self):
        return f"{self.protection_pattern} of {self.person}"

    class Meta:
        db_table = "person_protection_pattern"
        unique_together = ("person", "protection_pattern")


class ProtectionPatternPerson(Model):
    code = PositiveSmallIntegerField(_("code"), primary_key=True)
    description = CharField(_("description"), max_length=80)
    pattern = CharField(_("pattern"), max_length=80)
    comment = TextField(_("comment"), null=True, blank=True)
    person = ForeignKey(Person, null=True, on_delete=DO_NOTHING, verbose_name=_("person"))
    expires_on = DateField(_("expires on"), null=True, blank=True)

    @classmethod
    # for people only demographic, identifiable and professional protections make sense
    def get_data(cls, person):
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
                ppp.person_id,
                ppp.created_at,
                ppp.updated_at
            FROM protection_pattern AS pp
            LEFT JOIN person_protection_pattern AS ppp
                ON ppp.protection_pattern_id=pp.code AND ppp.person_id=%s
            WHERE pp.code IN (5, 6, 7, 9)
            ORDER BY description_"""
            + get_language(),
            [person.id],
        )

        prefetch_related_objects(q, "person")
        return q

    class Meta:
        managed = False


class AcademicRecord(Model):
    person = ForeignKey(Person, related_name="academic_records", on_delete=CASCADE)
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
    person = ForeignKey(Person, related_name="recognitions", on_delete=CASCADE)
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
    created_at = DateTimeField(auto_now_add=True, null=True)
    objects = CurrentSiteManager()
    all_objects = Manager()

    file = PrivateFileField(upload_to="converted/%Y/%m/%d")
    page_count = PositiveSmallIntegerField(_("number of pages"), null=True, blank=True)

    def natural_key(self):
        return self.file.name

    @property
    def file_size(self):
        return os.path.getsize(self.file.path)

    def __str__(self):
        return self.file.name


APPLICATION_STATES = Choices(
    (None, None),
    ("new", _("New")),
    ("draft", _("Draft")),
    ("tac_accepted", _("TAC accepted")),
    ("in_review", _("In referee review")),
    ("submitted", _("Submitted")),
    ("cancelled", _("Cancelled")),
    ("withdrawn", _("Withdrawn")),
    ("approved", _("Approved")),
    ("accepted", _("Accepted")),
    ("archived", _("Archived")),
    ("funded", _("Funded")),
)


class FundManager(Manager):
    def get_by_natural_key(self, code, *args, **kwargs):
        return self.get(code=code)


class Fund(Model):
    code = FixedCharField(max_length=2, primary_key=True, db_column="code")
    code3 = FixedCharField(max_length=3, null=True, blank=True)
    name = CharField(_("name"), max_length=200, null=True, blank=True)
    description = TextField(_("description"), max_length=10000, null=True, blank=True)
    cost_centre = PositiveSmallIntegerField(_("Cost Centre"), null=True, blank=True)
    catalyst_cost_centre = PositiveSmallIntegerField(
        _("Catalyst Cost Centre"), null=True, blank=True
    )
    site = ForeignKey(Site, on_delete=PROTECT, default=Model.get_current_site_id)
    # history = HistoricalRecords(table_name="fund_history")
    email = EmailField(_("Contact email address"), blank=True, null=True)
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
        upload_to="letters_of_support",
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


def default_application_number(application, exclude_numbers=None, nomination=None):
    code = application.round.scheme.code
    if (
        n := nomination
        or (application and application.pk and Nomination.where(application=application).last())
    ) and n.org:
        org_code = n.org.get_code()
    else:
        org_code = application.org.get_code()
    year = application.round.opens_on.strftime("%y")
    yy = application.round.opens_on.strftime("%y")
    prefix1 = f"{code}-{org_code}-{year}"
    prefix2 = f"{code}-{org_code}-{yy}"
    last_number = None
    if (
        latest_application := Application.all_objects.filter(
            # round=application.round,
            Q(number__istartswith=prefix1) | Q(number__istartswith=prefix2),
            number__isnull=False,
        )
        .order_by("-number")
        .values("number")
        .first()
    ):
        last_number = latest_application.get("number")
    if last_number and last_number.endswith("-E"):
        last_number = last_number.removesuffix("-E")
    application_number = int(last_number.split("-")[-1]) + 1 if last_number else 1
    while True:
        number = f"{code}-{org_code}-{year}-{application_number:03}"
        if not exclude_numbers or number not in exclude_numbers:
            return number
        application_number += 1


class ApplicationFor(Model):
    application = ForeignKey("Application", on_delete=CASCADE, related_name="application_fors")
    code = ForeignKey(FieldOfResearch, on_delete=CASCADE, db_column="code", verbose_name="FoR")
    share = PositiveSmallIntegerField(null=True, blank=True, default=None)

    def natural_key(self):
        return (self.application.number, self.code)

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

    def natural_key(self):
        return (self.application.number, self.code)

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

    def natural_key(self):
        return self.name

    class Meta:
        verbose_name = _("Keyword")
        verbose_name_plural = _("Keywords")
        db_table = "keyword"


class ResearchPriority(HelperMixin, TagBase):

    def natural_key(self):
        return self.name

    class Meta:
        verbose_name = _("Research Priority")
        verbose_name_plural = _("Research Priorities")
        db_table = "research_priority"


class ResearchPriorityItem(GenericTaggedItemBase):

    tag = ForeignKey(
        ResearchPriority,
        on_delete=CASCADE,
        related_name="items",
    )

    class Meta:
        verbose_name = _("item with research priorities")
        verbose_name_plural = _("items with research priorities")
        db_table = "research_priority_item"


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

    def natural_key(self):
        return (self.application.number, self.keywords.name)

    class Meta:
        db_table = "application_keyword"


class VMTOAModel(Model):

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
    vm_rationale = TextField(_("Rationale"), null=True, blank=True)

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

    class Meta:
        abstract = True


def get_unique_invitation_token():
    while True:
        token = secrets.token_urlsafe(8)
        if not Invitation.objects.filter(token=token).exists():
            return token


class CommentModel(Model):

    @property
    def object_pk(self):
        return self.object_id

    reply_to = ForeignKey("self", on_delete=CASCADE, related_name="replies", null=True, blank=True)
    token = CharField(max_length=42, default=get_unique_invitation_token, unique=True)
    subject = CharField(max_length=1000, null=True, blank=True)
    comment = TextField(_("comment"), max_length=1000, null=True, blank=True)
    attachment = PrivateFileField(
        _("attachment"),
        upload_subfolder=lambda instance: [
            instance.object.model_name,
            hash_int(instance.object_pk),
            "comments",
        ],
        null=True,
        blank=True,
    )
    submitted_by = ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=SET_NULL,
        # related_name="%(class)ss",
        verbose_name=_("submitted by"),
    )
    alert_date = CharField(
        max_length=200,
        null=True,
        blank=True,
    )

    @property
    def target(self):
        return self.object

    def import_reply(self, file, file_name=None, notify_author=True, request=None, by=None):
        return self.object.import_email(
            file,
            file_name=file_name,
            notify_author=notify_author,
            request=request,
            by=by,
            reply_to=self,
        )

    def __str__(self):
        return f"Submitted by {self.submitted_by} at {self.created_at}"

    class Meta:
        verbose_name = _("comment")
        verbose_name_plural = _("comments")
        ordering = ["-created_at"]
        abstract = True


class Application(ApplicationMixin, PersonMixin, PdfFileMixin, Model):
    # objects = RoundSiteManager()
    site = ForeignKey(Site, on_delete=PROTECT, default=Model.get_current_site_id)
    objects = CurrentSiteManager()
    all_objects = Manager()
    tags = TaggableManager(blank=True)

    is_preliminary = BooleanField(_("is preliminary"), null=True, blank=True, default=False)
    preliminary = ForeignKey(
        "self",
        on_delete=CASCADE,
        null=True,
        blank=True,
        help_text=_("Expression of Interest or preliminary application"),
    )
    number = CharField(_("number"), max_length=24, null=True, blank=True, unique=True)
    submitted_by = ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=SET_NULL,
        verbose_name=_("submitted by"),
        related_name="applications",
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
    proposed_start_date = DateField(blank=True, null=True, verbose_name=_("Proposed start date"))
    requested_amount = DecimalField(
        max_digits=9,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Requested amount"),
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
    address = ForeignKey(
        Address, blank=True, null=True, on_delete=RESTRICT, related_name="applications"
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
        upload_to="applications",
        upload_subfolder=lambda instance: [hash_int(instance.round_id)],
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
        upload_to="ids",
        upload_subfolder=lambda instance: [hash_int(instance.submitted_by_id)],
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

    state = StateField(default="new", verbose_name=_("application state"))
    state_changed_at = MonitorField(monitor="state", null=True, default=None, blank=True)
    is_tac_accepted = BooleanField(default=False, verbose_name=_("the T&Cs were accepted"))
    tac_accepted_at = MonitorField(
        monitor="state",
        when=["tac_accepted"],
        verbose_name=_("Terms and Conditions accepted at"),
        null=True,
        default=None,
        blank=True,
    )
    budget = PrivateFileField(
        blank=True,
        null=True,
        verbose_name=_("completed application budget spreadsheet"),
        help_text=_("Please upload completed application budget spreadsheet"),
        upload_to="budgets",
        upload_subfolder=lambda instance: [hash_int(instance.round_id)],
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
    priorities = TaggableManager(
        blank=True,
        verbose_name=_("Priorities"),
        help_text=_("Research priorities"),
        through=ResearchPriorityItem,
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
    vm_rationale = TextField(_("Rationale"), null=True, blank=True)

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
    panel = ForeignKey("Panel", null=True, blank=True, on_delete=PROTECT)
    awarded_amount = DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)

    agent_declaration_accepted_by = ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=SET_NULL,
        related_name="+",
    )
    agent_declaration_accepted_at = DateTimeField(null=True, blank=True)
    applicant_declaration_accepted_by = ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=SET_NULL,
        related_name="+",
    )
    # at the time of submission:
    # applicant_declaration_accepted_at = DateTimeField(null=True, blank=True)

    @property
    def is_wip(self):
        return not self.state or self.state in ["new", "draft"]

    @cached_property
    def ci(self):
        return (
            (ci := self.members.filter(role="CI").last()) and ci.person.user or self.submitted_by
        )

    @cached_property
    def pi(self):
        return (pi := self.members.filter(role="PI").last()) and pi.user or self.submitted_by

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
            or self.members.all()
            .filter(Q(user=user) | Q(email__lower=user.email.lower()))
            .exists()
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
            or (self.referees.filter(Q(user=user) | Q(email__lower=user.email.lower())).exists())
            or (
                self.round.panellists.filter(
                    Q(user=user) | Q(email__lower=user.email.lower())
                ).exists()
            )
            or (self.org.research_offices.filter(user=user).exists())
            or self.members.all()
            .filter(Q(email__lower__in=user.emailaddress_set.values_list("email__lower")))
            .exists()
        )

    def get_score_entries(self, user=None, panellist=None):
        if not panellist:
            panellist = Panellist.get(user=user, round=self.round)
        return self.round.criteria.filter(
            Q(scores__evaluation__panellist=panellist)
            | Q(scores__evaluation__panellist__isnull=True)
        ).prefetch_related("scores")

    def save(self, *args, **kwargs):

        if self.application_title is None:
            self.application_title = "" if self.site_id in [2, 4, 5] else self.round.title
        if not self.number:
            self.number = default_application_number(self)
            if self.is_preliminary:
                self.number = f"{self.number}-E"
        super().save(*args, **kwargs)
        if (pi := self.submitted_by) and not self.members.filter(user=pi).exists():
            self.members.model.get_or_create(
                application=self,
                user=pi,
                email=self.email or pi.email,
                defaults=dict(
                    first_name=self.first_name or pi.first_name,
                    middle_names=self.middle_names or pi.middle_names,
                    last_name=self.last_name or pi.last_name,
                    state="authorized",
                    authorized_at=self.updated_at,
                    role_description="The submitter of the application",
                    role_id="PI",
                ),
            )

    def create_contract(self, *args, **kwargs):
        return Contract.create_from_application(application=self, *args, **kwargs)

    @cache
    def can_only_update_referees(self, user):
        return bool(
            self.pk
            and self.state in ["submitted", "in_review"]
            and not (
                user.is_superuser
                or user.is_site_staff
                or (
                    self.site_id in [2, 4, 5]
                    and self.org
                    and (
                        self.org.research_offices.filter(user=user).exists()
                        or Nomination.where(application=self, nominator=user).exists()
                    )
                    and self.state in ["draft", "submitted"]
                )
            )
        )

    def invite_referees(self, request, by=None, referees=None, *args, **kwargs):
        """Send invitations to all referee."""
        return Referee.invite_referees(
            request, application=self, by=by, referees=referees, *args, **kwargs
        )

    @fsm_log
    @transition(
        field=state,
        source=["draft", "new", "tac_accepted"],
        target="draft",
        custom=dict(verbose="Save Draft", button_name="Save Draft", admin=False),
    )
    def save_draft(self, *args, **kwargs):
        pass

    @fsm_log
    @transition(
        field=state,
        source=["draft", "new", "tac_accepted", "in_review", "submitted"],
        target="archived",
        custom=dict(verbose="Archive", button_name="Archive"),
    )
    def archive(self, *args, **kwargs):
        pass

    @fsm_log
    @transition(
        field=state,
        source=["draft", "new", "tac_accepted"],
        target="draft",
        custom=dict(verbose="Accept TAC", button_name="Accept TAC"),
    )
    def accept_tac(self, *args, **kwargs):
        self.is_tac_accepted = True

    def is_completed(self, skip_testimonials=False, *args, **kwargs):
        """Verifies application completion"""
        request = kwargs.get("request")
        round = self.round
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
            else:
                raise Exception(
                    _(
                        "The principal application must accept the Terms and Conditions to submit an application"
                    )
                )

        if (
            self.round.research_summary_required
            and not self.file
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

        if round.required_submitted_testimonials:

            if not skip_testimonials:
                if self.referees.filter(
                    Q(testified_at__isnull=True)
                    | Q(user__isnull=True)
                    | ~Q(testimonial__state="submitted"),
                    ~Q(state__in=["submitted", "opted_out", "testified"]),
                ).exists():
                    raise ValidationError(
                        _(
                            "Not all nominated referees have responded which prevents your submission. "
                            "Please either contact your referees, or replace them with one that will respond."
                        ),
                        "referees",
                    )

                min_referees = (
                    (round.required_referees or 1)
                    if round.required_submitted_testimonials
                    else round.required_referees
                )
                if min_referees and self.referees.filter(state="testified").count() < min_referees:
                    if min_referees == 1:
                        raise ValidationError(
                            _(
                                "You need to procure reviews of your application from at least one referee."
                            ),
                            "referees",
                        )
                    else:
                        raise ValidationError(
                            _(
                                "You need to procure reviews of your application from at least %d referees."
                            )
                            % min_referees,
                            "referees",
                        )
        else:
            if (
                self.round.required_referees
                and self.referees.filter(~Q(state__in=["bounced", "opted_out"])).count()
                < self.round.required_referees
            ):
                raise ValidationError(
                    (_("You need to nominate at least %d referee(s)."))
                    % self.round.required_referees,
                    "referees",
                )

        if self.members.filter(Q(authorized_at__isnull=True) | Q(user__isnull=True)).exists():
            raise Exception(
                _(
                    "Not all team members have given their consent to be part of the team "
                    " which prevents your submission. "
                    "Please either contact your team's members, or modify the team membership"
                )
            )

    # def can_be_funded(self):
    #     return (self.site_id != 4 and self.state == "approved") or self.state == "accepted"

    @fsm_log
    @transition(
        field=state,
        source=["tac_accepted", "submitted", "approved", "accepted", "in_review"],
        target="in_review",
        conditions=[
            lambda self: self.site_id not in [2, 5] or self.state in ["accepted", "in_review"]
        ],
        custom=dict(verbose="Submit To Referees", button_name="To Referees"),
    )
    def send_out_to_referees(self, exclude_sender=False, *args, **kwargs):
        try:
            request = kwargs.get("request")
            self.is_completed(skip_testimonials=(self.site_id in [2, 5]), *args, **kwargs)
            return self.invite_referees(
                request=request,
                dispatch_invitations=(
                    self.site_id not in [2, 5]
                    or (
                        self.site_id in [2, 5]
                        and self.round.closes_at
                        and self.round.closes_at <= timezone.now()
                    )
                ),
                exclude_sender=exclude_sender,
            )
        except Exception as ex:
            if request:
                messages.error(request, f"{ex}")
            return 0

    @fsm_log
    @transition(
        field=state,
        source=["new", "draft", "tac_accepted", "submitted"],
        target="submitted",
        conditions=[lambda self: self.site_id in [2, 5] or self.state != "submitted"],
        custom=dict(verbose="Submit", button_name="Submit"),
    )
    def submit(self, *args, **kwargs):
        self.is_completed(skip_testimonials=(self.site_id in [2, 5]), *args, **kwargs)
        request = kwargs.get("request")
        round = self.round

        nomination = Nomination.where(application=self).last()
        nominator = nomination and nomination.nominator
        if (
            nominator
            and nominator.research_offices.filter(
                Q(Q(org=self.org_id) | Q(org=nomination.org_id))
                if self.org_id and nomination.org_id
                else Q(org=(self.org_id or nomination.org_id))
            ).exists()
        ):
            # url = request.build_absolute_uri(
            #     reverse("application-detail", kwargs={"number": self.number})
            # )
            # url = domain_to_macrons(url)
            url = self.get_full_detail_url(request=request)
            link_name = domain_to_macrons(url)
            if self.site_id in [2, 5]:
                html_message = (
                    "<p>Kia ora %(nominator)s</p>"
                    '<p>The nominee has submitted an application <a href="%(url)s">%(number)s: '
                    "%(title)s</a> and all the solicited referee reports were submitted.</p>"
                    "<p>Please review and approve the submitted application.</p>"
                )
            else:
                html_message = (
                    "<p>Kia ora %(nominator)s</p>"
                    '<p>The nominee has submitted an application <a href="%(url)s">%(number)s: '
                    "%(title)s</a></p>"
                    "<p>Please review and approve the submitted application.</p>"
                )
            send_mail(
                __("Application '%s' Submitted") % self,
                html_message=html_message
                % {
                    "nominator": nominator,
                    "url": url,
                    "link_name": link_name,
                    "number": self.number,
                    "title": self.application_title or round.title,
                },
                recipients=[nominator.full_email_address],
                # cc=[
                #     ro.user.full_email_address
                #     for ro in ResearchOffice.where(org=self.org)
                #     if ro.user != nominator
                # ],
                fail_silently=False,
                request=request,
                reply_to=settings.DEFAULT_FROM_EMAIL,
                thread_index=self.thread_index,
                thread_topic=self.thread_topic,
            )
        elif round.notify_nominator and nominator:
            url = request.build_absolute_uri(reverse("application", args=[str(self.id)]))
            link_name = domain_to_macrons(url)
            url = self.get_full_detail_url(request=request)
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
                    "link_name": link_name,
                    "number": self.number,
                    "title": self.application_title or round.title,
                },
                recipients=[nominator.full_email_address],
                fail_silently=False,
                request=request,
                reply_to=settings.DEFAULT_FROM_EMAIL,
                thread_index=self.thread_index,
                thread_topic=self.thread_topic,
            )

    @fsm_log
    @transition(
        field=state,
        source=["submitted"],
        target="approved",
        custom=dict(verbose="Approve", button_name="Approve"),
    )
    def approve(self, request=None, by=None, description=None, *args, **kwargs):
        resolution = kwargs.get("reason") or kwargs.get("resolution") or description
        if resolution and isinstance(description, str):
            resolution = resolution.strip()
        if not by and request:
            by = request.user
        if agent_declaration_accepted := kwargs.pop("agent_declaration_accepted", None):
            self.agent_declaration_accepted_by = by
            self.agent_declaration_accepted_at = timezone.now()
        # approved by the R.O.
        recipients = [self.submitted_by, *self.members.all()]
        url = self.get_full_detail_url(request=request)
        if ResearchOffice.where(user=by, org=self.org).exists():
            if not resolution:
                resolution = f'The Research Office approved has approved the application "{self}"'
            subject = f'The Research Office approved has approved your application "{self}"'
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
            recipients=[r.full_email_address for r in recipients],
            fail_silently=False,
            request=request,
            reply_to=settings.DEFAULT_FROM_EMAIL,
            thread_index=self.thread_index,
            thread_topic=self.thread_topic,
        )
        if request:
            messages.success(
                request,
                "Successfully sent notification to %s"
                % ", ".join(u.full_name_with_email for u in recipients),
            )

    @fsm_log
    @transition(
        field=state,
        source=["approved", "in_review"],
        target="accepted",
        custom=dict(verbose="Accept", button_name="Accept"),
    )
    def accept(self, request=None, by=None, description=None, *args, **kwargs):
        resolution = kwargs.get("reason") or kwargs.get("resolution") or description
        if resolution and isinstance(description, str):
            resolution = resolution.strip()
        if not by and request:
            by = request.user
        # approved by the R.O.
        recipients = [self.submitted_by, *self.members.all()]
        if (nomination := Nomination.where(application=self).last()) and (
            nominator := nomination and nomination.nominator
        ):
            recipients.append(nominator)
        url = request.build_absolute_uri(
            reverse("application-detail", kwargs={"number": self.number})
        )
        # link_name = domain_to_macrons(url)
        if not resolution:
            resolution = f'The application "{self}" was accepted by {by.full_email_address}.'
        # subject = f'Application "{self}" was ACCEPTED'
        # if not getattr(self, "_change_reason", None):
        #     self._change_reason = resolution

        # params = {
        #     "user_display": ", ".join(r.full_name for r in recipients),
        #     "number": self.number,
        #     "user": by and by.full_name_with_email,
        #     "title": self.title or self.round.title,
        #     "url": url,
        #     "link_name": link_name,
        #     "resolution": resolution,
        # }
        # send_mail(
        #     subject,
        #     (
        #         "Kia ora %(user_display)s\n\n"
        #         'The application "%(number)s: %(title)s" was approved: %(url)s by %(user)s.\n\n'
        #         "Resolution:\n"
        #         "===========\n\n%(resolution)s\n\n"
        #     )
        #     % params,
        #     html_message=(
        #         "<p>Kia ora %(user_display)s</p>"
        #         '<p>Your application <a href="%(url)s">%(number)s: %(title)s</a> was approved.</p>'
        #         "<h3>Resolution</h3>\n"
        #         "<pre>%(resolution)s</pre>\n\n"
        #     )
        #     % params,
        #     recipients=[r.full_email_address for r in recipients],
        #     fail_silently=False,
        #     request=request,
        #     reply_to=by and by.full_email_address or settings.DEFAULT_FROM_EMAIL,
        #     thread_index=self.thread_index,
        #     thread_topic=self.thread_topic,
        # )
        # messages.success(
        #     request,
        #     "Successfully sent notification to %s"
        #     % ", ".join(u.full_name_with_email for u in recipients),
        # )

    def can_be_funded(self):
        return (
            (self.site_id != 4 and self.state == "approved")
            or self.state == "accepted"
            or (self.site_id in [2, 5] and self.state == "in_review")
        )

    @fsm_log
    @transition(
        field=state,
        source=["approved", "accepted", "in_review"],
        target="funded",
        conditions=[can_be_funded],
        custom=dict(verbose="Mark application funded", button_name="Mark Funded"),
    )
    def fund(self, request=None, by=None, description=None, *args, **kwargs):
        if (
            awarded_amount := kwargs.get("awarded_amount")
            or self.round.awarded_amount
        ):
            self.awarded_amount = awarded_amount
        return Contract.create_from_application(application=self, *args, **kwargs)

    @fsm_log
    @transition(
        field=state,
        source=["submitted", "cancelled", "approved", "accepted", "in_review"],
        target="draft",
        custom=dict(verbose="Request resubmission", button_name="Request resubmission"),
    )
    def request_resubmission(self, request=None, by=None, description=None, *args, **kwargs):
        (previous_state,) = self.__class__.where(pk=self.pk).values_list("state").first()
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
        elif previous_state == "cancelled":
            if not resolution:
                resolution = (
                    "Your application cancellation was reverted. "
                    f'{by.full_email_address} requested reviewing and resubmission of your application "{self}".'
                )
            subject = f'The application "{self}" requires your attention'
        else:
            if not resolution:
                resolution = f'{by.full_email_address} requested reviewing and resubmission of your application "{self}".'
            subject = f'The application "{self}" requires your attention'
        if not getattr(self, "_change_reason", None):
            self._change_reason = resolution

        recipients = [self.submitted_by, *self.members.all()]
        url = request.build_absolute_uri(reverse("application-update", kwargs={"pk": self.id}))
        link_name = domain_to_macrons(url)
        params = {
            "user_display": ", ".join(r.full_name for r in recipients),
            "number": self.number,
            "user": by and by.full_name_with_email,
            "title": self.application_title or self.round.title,
            "url": url,
            "link_name": link_name,
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
            recipients=[r.full_email_address for r in recipients],
            fail_silently=False,
            request=request,
            reply_to=settings.DEFAULT_FROM_EMAIL,
            thread_index=self.thread_index,
            thread_topic=self.thread_topic,
        )
        messages.success(
            request,
            "Successfully sent notification to review applicant to %s"
            % ", ".join(u.full_name_with_email for u in recipients),
        )

    @fsm_log
    @transition(
        field=state,
        source=["approved", "accepted", "in_review"],
        target="submitted",
        conditions=[lambda self: self.site_id in [2, 5]],
        custom=dict(
            verbose="Request reassessment and release the application back to the R.O. "
            "for further assessment and editing",
            button_name="Request reassessment",
        ),
    )
    def request_reassesment(self, request=None, by=None, description=None, *args, **kwargs):
        (previous_state,) = self.__class__.where(pk=self.pk).values_list("state").first()
        resolution = kwargs.get("reason") or kwargs.get("resolution") or description
        if resolution and isinstance(description, str):
            resolution = resolution.strip()
        if ResearchOffice.where(user=by, org=self.org).exists():
            if not resolution:
                resolution = (
                    "RSTA has requested reassessment and "
                    f'resubmission of the application "{self}"'
                )
            subject = (
                "RSTA has requested reassessment and " f'resubmission of the application "{self}"'
            )
        elif previous_state == "cancelled":
            if not resolution:
                resolution = (
                    "Your application cancellation was reverted. "
                    f'{by.full_email_address} requested reassessment and resubmission of the application "{self}".'
                )
            subject = f'The application "{self}" requires your attention'
        else:
            if not resolution:
                resolution = f'{by.full_email_address} requested reassessment and resubmission of your application "{self}".'
            subject = f'The application "{self}" requires your attention'
        if not getattr(self, "_change_reason", None):
            self._change_reason = resolution

        if (n := Nomination.where(application=self).last()) and n.nominator.is_active:
            recipients = [n.nominator]
        elif self.org.ro_email:
            recipients = [self.org.ro_email]
        else:
            recipients = [ro.user for ro in self.org.research_offices.all()]
        url = request.build_absolute_uri(
            reverse("application-detail", kwargs={"number": self.number})
        )
        link_name = domain_to_macrons(url)
        params = {
            "user_display": ", ".join(
                r if isinstance(r, str) else r.full_name for r in recipients
            ),
            "number": self.number,
            "user": by and by.full_name_with_email,
            "title": self.application_title or self.round.title,
            "url": url,
            "link_name": link_name,
            "resolution": resolution or "Requested for reviewing and re-drafting.",
        }
        send_mail(
            subject,
            __(
                "Kia ora %(user_display)s\n\n"
                "Please reassess and amend the application %(number)s: %(title)s here %(url)s.\n\n"
                "Resolution:\n"
                "===========\n\n%(resolution)s\n\n"
            )
            % params,
            html_message=__(
                "<p>Kia ora %(user_display)s</p>"
                '<p>Please reassess and amend the application <a href="%(url)s">%(number)s: %(title)s</a></p>'
                "<h3>Resolution</h3>\n"
                "<pre>%(resolution)s</pre>\n\n"
            )
            % params,
            recipients=[r if isinstance(r, str) else r.full_email_address for r in recipients],
            fail_silently=False,
            request=request,
            reply_to=by.email,
            thread_index=self.thread_index,
            thread_topic=self.thread_topic,
        )
        messages.success(
            request,
            "Successfully sent notification to review applicant to %s"
            % ", ".join(u if isinstance(u, str) else u.full_name_with_email for u in recipients),
        )

    @fsm_log
    @transition(
        field=state,
        source=["submitted", "draft", "new"],
        target="cancelled",
        custom=dict(verbose="Cancel", button_name="Cancel"),
    )
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
        link_name = domain_to_macrons(url)
        params = {
            "user_display": ", ".join(r.full_name for r in recipients),
            "number": self.number,
            "user": by and by.full_name_with_email,
            "title": self.title or self.round.title,
            "url": url,
            "link_name": link_name,
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
            recipients=[r.full_email_address for r in recipients],
            fail_silently=False,
            request=request,
            reply_to=settings.DEFAULT_FROM_EMAIL,
            thread_index=self.thread_index,
            thread_topic=self.thread_topic,
        )
        messages.success(
            request,
            "Successfully sent notification to review applicant to %s"
            % ", ".join(u.full_name_with_email for u in recipients),
        )

    @fsm_log
    @transition(
        field=state,
        source=["approved"],
        target="cancelled",
        custom=dict(verbose="Invalidate", button_name="Invalidate"),
    )
    def invalidate(self, request=None, by=None, description=None, *args, **kwargs):
        resolution = kwargs.get("reason") or kwargs.get("resolution") or description
        if resolution and isinstance(description, str):
            resolution = resolution.strip()
        if not resolution:
            resolution = f'{by.full_email_address} invalidated your application "{self}".'
        subject = f'Application "{self}" was CANCELLED'
        if not getattr(self, "_change_reason", None):
            self._change_reason = resolution

        recipients = [self.submitted_by, *self.members.all()]
        if (nomination := Nomination.where(application=self).last()) and (
            nominator := nomination and nomination.nominator
        ):
            recipients.append(nominator)
        url = request.build_absolute_uri(reverse("application", kwargs={"pk": self.id}))
        link_name = domain_to_macrons(url)
        params = {
            "user_display": ", ".join(r.full_name for r in recipients),
            "number": self.number,
            "user": by and by.full_name_with_email,
            "title": self.title or self.round.title,
            "url": url,
            "link_name": link_name,
            "resolution": resolution or "Requested for reviewing and re-drafting.",
        }
        # send_mail(
        #     subject,
        #     __(
        #         "Kia ora %(user_display)s\n\n"
        #         'Your application "%(number)s: %(title)s" was cancelled: %(url)s by %(user)s.\n\n'
        #         "Resolution:\n"
        #         "===========\n\n%(resolution)s\n\n"
        #     )
        #     % params,
        #     html_message=__(
        #         "<p>Kia ora %(user_display)s</p>"
        #         '<p>Your application <a href="%(url)s">%(number)s: %(title)s</a> was cancelled by %(user)s.</p>'
        #         "<h3>Resolution</h3>\n"
        #         "<pre>%(resolution)s</pre>\n\n"
        #     )
        #     % params,
        #     recipients=[r.full_email_address for r in recipients],
        #     fail_silently=False,
        #     request=request,
        #     reply_to=by and by.full_email_address or settings.DEFAULT_FROM_EMAIL,
        #     thread_index=self.thread_index,
        #     thread_topic=self.thread_topic,
        # )
        messages.success(
            request,
            "Successfully sent notification to review applicant to %s"
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
        return self.state in ["submitted", "approved", "accepted", "in_review", "cancelled"]

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
        cls,
        user,
        state=None,
        round=None,
        select_related=True,
        include_inactive=False,
        request=None,
        queryset=None,
    ):
        q = queryset or cls.objects.all()
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

        if not round and not (
            (user.is_staff or user.is_superuser or user.is_site_staff) and include_inactive
        ):
            q = q.filter(round=F("round__scheme__current_round"))

        if user.is_staff or user.is_superuser or user.is_site_staff:
            return q

        f = (
            Q(submitted_by=user)
            | Q(members__user=user, members__state="authorized")
            | Q(referees__user=user)
            | Q(nomination__nominator=user)
            | Q(nomination__user=user)
            | Q(
                Q(org__research_offices__user=user),
                Q(
                    Q(nomination__org=F("org"))
                    | Q(nomination__nominator__research_offices__org=F("org"))
                ),
            )
        )
        if Panellist.where(user=user, round__scheme__current_round=F("round")).exists():
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
    def user_application_count(cls, user, state=None, round=None, request=None):
        return cls.user_applications(
            user=user, state=state, round=round, select_related=False, request=request
        ).count()

    @classmethod
    def user_application_counts(cls, user, state=None, round=None, request=None):
        return (
            cls.where(
                pk__in=cls.user_applications(
                    user=user, state=state, round=round, select_related=False, request=request
                ).values("pk")
            )
            .values_list("state")
            .annotate(total=Count("state"))
            .order_by()
        )

    @classmethod
    def user_draft_applications(cls, user, request=None):
        return cls.user_applications(user, ["draft", "new"], request=request)

    def get_testimonials(self, has_testified=None, user=None):
        sql = (
            "SELECT DISTINCT tm.* FROM referee AS r "
            "JOIN application AS a "
            "  ON a.id = r.application_id "
            "LEFT JOIN testimonial AS tm ON r.id = tm.referee_id "
            "WHERE (r.application_id=%s OR a.id=%s) AND a.site_id=%s "
        )
        if has_testified:
            sql += " AND r.state='testified'"
        if user:
            sql += f" AND r.user_id={user.pk}"
        sql += " ORDER BY tm.id"
        if self.round.required_referees:
            sql += f" LIMIT {self.round.required_referees}"

        return Testimonial.objects.raw(sql, [self.id, self.id, self.current_site_id])

    def to_pdf(
        self,
        request=None,
        user=None,
        add_headers=None,
        skip_excluded=False,
        cache=False,
        for_panellists=False,
    ):
        """Create PDF file for export and return PdfMerger"""

        r = self.round
        site_id = self.site_id

        if not user and request:
            user = request.user

        is_referee = user and self.referees.filter(user=user).exists()
        is_panellist = (
            user
            and self.conflict_of_interests.filter(
                panellist__user=user, has_conflict=False, has_conflict__isnull=False
            ).exists()
        )

        attachments = []
        cvs = []
        if not for_panellists and request:
            for_panellists = request.GET.get("for_panellists", False)
        include_header_page = not (site_id in [2, 5] and for_panellists)
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
                    include_header_page and cv.title_page,
                )
            )

        def add_testimonials(attachments, user=None):
            for t in self.get_testimonials(has_testified=True, user=user):
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

        if user.is_superuser or user.is_staff or (site_id != 4 and is_panellist) or for_panellists:
            for n in Nomination.where(application=self, nominator__isnull=False):
                if n.file:
                    attachments.append(
                        (
                            _("Nomination Submitted By %s") % n.nominator.full_name,
                            settings.PRIVATE_STORAGE_ROOT + "/" + str(n.pdf_file),
                            include_header_page and n.title_page,
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
                                include_header_page and nominator_cv.title_page,
                            )
                        )

        if site_id not in [2, 4, 5] and not is_referee and not self.is_applicant(user):
            if (
                user.is_superuser
                or self.is_applicant(user)
                or user.is_site_staff
                or is_panellist
                or for_panellists
            ):
                add_testimonials(attachments)
            else:
                add_testimonials(attachments, user=user)

        if r.letter_of_support_required and self.letter_of_support and self.letter_of_support.file:
            attachments.append(
                (
                    _("Letter of Support"),
                    settings.PRIVATE_STORAGE_ROOT + "/" + str(self.letter_of_support.pdf_file),
                    include_header_page and self.letter_of_support.title_page,
                )
            )

        for d in self.documents.order_by("required_document__ordering"):
            if (
                skip_excluded
                and d.required_document.exclude
                or is_referee
                and not d.required_document.referees_can_access
                or (is_panellist or for_panellists)
                and not d.required_document.panellists_can_access
            ):
                continue
            attachments.append(
                (
                    f"{d.required_document}",
                    settings.PRIVATE_STORAGE_ROOT + "/" + str(d.pdf_file),
                    include_header_page and d.title_page,
                )
            )

        if site_id in [2, 4, 5] and not (
            (nomination := Nomination.where(application=self).last())
            and nomination.nominator == user
        ):
            if (
                user.is_superuser
                or self.is_applicant(user)
                or user.is_site_staff
                or is_panellist
                or for_panellists
            ):
                add_testimonials(attachments)
            else:
                add_testimonials(attachments, user=user)

        ssl._create_default_https_context = ssl._create_unverified_context

        # merger = PdfMerger(strict=False)
        merger = PdfWriter()
        merger.add_metadata(
            {
                "/Title": (
                    f"{self}"
                    if site_id in [2, 4, 5]
                    else f"{self.number}: {self.application_title or r.title}"
                )
            }
        )
        merger.add_metadata({"/Author": self.lead_with_email})
        merger.add_metadata({"/Subject": r.title})
        merger.add_metadata({"/Number": self.number})
        # merger.add_metadata({"/Keywords": r.title})

        objects = []
        site = self.site or Site.objects.get_current()
        domain = site.domain

        logo_url = logo_1_url = logo_2_url = None
        if site_id == 2:
            if logo_path := finders.find(f"images/{domain}/alt_logo_small.png"):
                logo_url = f"file://{logo_path}"

        elif site_id in [2, 4, 5]:
            if logo_path := finders.find("images/MBIE_logo.jpg"):
                logo_1_url = f"file://{logo_path}"

            if logo_path := finders.find("images/RS_logo.png"):
                logo_2_url = f"file://{logo_path}"

        elif site_id == 7:
            if logo_path := finders.find("images/pmspace-logo_small.jpg"):
                logo_url = f"file://{logo_path}"

        if (
            r.research_summary_required
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
            if site_id in [2, 5] and for_panellists:
                url = f"{url}?for_panellists=1"
            if request:
                summary_url = request.build_absolute_uri(url)
            else:
                summary_url = urljoin(f"https://{domain}", url)
            html = HTML(summary_url)
        else:

            template = get_template("application-export.html")
            context = {
                "application": self,
                "objects": objects,
                "user": user,
                "site": site,
                "domain": domain,
                "site_id": site_id,
                "SITE_ID": site_id,
                "logo": logo_url,
                "logo_1": logo_1_url,
                "logo_2": logo_2_url,
                "for_panellists": for_panellists,
            }
            if for_panellists and (user.is_superuser or user.is_site_staff):
                if site_id in [2, 5]:
                    referees = self.referees.order_by("testified_at")
                    if r.required_referees:
                        referees = referees[: r.required_referees]
                    context["referees"] = referees
                else:
                    context["referees"] = self.referees.all()

            html = HTML(string=template.render(context))

        pdf_object = html.write_pdf(presentational_hints=True)
        # converting pdf bytes to stream which is required for pdf merger.
        pdf_stream = io.BytesIO(pdf_object)
        merger.append(
            pdf_stream,
            outline_item=(self.application_title or r.title),
            import_outline=True,
        )
        for title, a, *rest in attachments:
            # merger.append(PdfReader(a, strict=False), outline_item=title, import_outline=True)
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
                            "site_id": site_id,
                            "SITE_ID": site_id,
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
                    # outline_item=(self.application_title or r.title),
                    import_outline=True,
                )

            # merger.append(a, outline_item=title, import_outline=True)
            try:
                try:
                    reader = PdfReader(a, strict=False)
                except PdfReadError as ex:
                    if "'%PDF-' expected" in ex.args[0]:
                        pdf = pikepdf.Pdf.open(a)
                        mended = os.path.join(tempfile.mkdtemp(), os.path.basename(a))
                        pdf.save(mended, normalize_content=True)
                        reader = PdfReader(mended, strict=False)
                    else:
                        raise
                if reader.is_encrypted:
                    pdf = pikepdf.Pdf.open(a)
                    decrypted = os.path.join(tempfile.mkdtemp(), os.path.basename(a))
                    pdf.save(decrypted, normalize_content=True)
                    reader = PdfReader(decrypted, strict=False)
                    # merger.append(decrypted, outline_item=title, import_outline=import_outline)
                    # merger.append(PdfReader(a, strict=False), outline_item=title, import_outline=True)

                # test if book marks can be imported
                try:
                    reader.outline
                    import_outline = True
                except PdfReadError as ex:
                    if ex.args[0].startswith("Unexpected destination ") or ex.args[0].startswith(
                        "Multiple definitions in dictionary at "
                    ):
                        import_outline = False
                    else:
                        raise

                merger.append(reader, outline_item=title, import_outline=import_outline)
            except PdfReadError:
                capture_message(f"Failed to merge file {a}")
                raise

        if add_headers or site_id == 4:
            template = get_template("headers.html")
            html = HTML(
                string=template.render({"page_count": len(merger.pages), "application": self})
            )
            header_file = PdfReader(
                io.BytesIO(html.write_pdf(presentational_hints=True)), strict=False
            )
            for dp, hp in zip(merger.pages, header_file.pages):
                dp.merge_page(hp)

        if cache and for_panellists:
            pass

        return merger

    def clean(self):
        super().clean()
        if self.is_preliminary and self.preliminary_id:
            raise ValidationError(
                _("A preliminary application cannot have a preliminary application.")
            )

    def natural_key(self):
        return self.number

    @lru_cache(1)
    def user_documents_dict(self, user=None):
        if self.submitted_by_id == user.pk or self.members.filter(user=user).exists():
            return self.documents_dict

        documents = self.documents.filter(
            Q(document_type__role__in=["CV", "HS", "B", "A", "AF"])
            | Q(required_document__document_type__role__in=["CV", "HS", "B", "A", "AF"])
        )
        if self.referees.filter(user=user).exists():
            documents = documents.filter(required_document__referees_can_access=True)
        elif self.round.panellists.filter(user=user).exists():
            documents = documents.filter(required_document__panellists_can_access=True)

        documents = {
            d.document_type.role or d.required_document.document_type.role: d.pdf_file
            for d in documents
        }
        if "HS" not in documents and (
            n := Nomination.where(application=self, file__isnull=False).last()
        ):
            documents["HS"] = n.pdf_file
        return documents

    @cached_property
    def vm_rationale_html(self):
        if not self.vm_rationale:
            return ""
        if "\r\n" in self.vm_rationale:
            lines = self.vm_rationale.split("\r\n\r\n")
        elif "\r\r" in self.vm_rationale:
            lines = self.vm_rationale.split("\r\r")
        else:
            lines = self.vm_rationale.split("\n\n")
        return "\r\r".join(f"<p>{l}</p>" for l in lines if l.strip())

    @cached_property
    def documents_dict(self):
        documents = {
            d.document_type.role or d.required_document.document_type.role: d.pdf_file
            for d in self.documents.filter(
                Q(document_type__role__in=["CV", "HS", "B", "A"])
                | Q(required_document__document_type__role__in=["CV", "HS", "B", "A"])
            )
        }
        if "HS" not in documents and (
            n := Nomination.where(application=self, file__isnull=False).last()
        ):
            documents["HS"] = n.pdf_file
        return documents

    class Meta:
        db_table = "application"


# class ApplicationExportLog(Model):
#     application = ForeignKey(Application, on_delete=CASCADE, related_name="export_log")
#     user = ForeignKey(User, null=True, blank=True, on_delete=SET_NULL, related_name="application_export_log")
#     application = ForeignKey("Application", on_delete=CASCADE)

#     class Meta:
#         db_table = "application_export_log"


class ApplicationNumber(Model):
    """Historical or alternative application numbers."""

    application = ForeignKey(Application, on_delete=CASCADE, related_name="numbers")
    number = CharField(
        _("number"), max_length=24, null=True, blank=True, editable=False, unique=True
    )
    is_active = BooleanField(default=False)
    history = HistoricalRecords(table_name="application_number_history")

    def natural_key(self):
        return (self.application.number, self.number)

    class Meta:
        db_table = "application_number"


class EthicsStatement(PdfFileMixin, Model):
    application = OneToOneField(Application, on_delete=CASCADE, related_name="ethics_statement")
    file = PrivateFileField(
        verbose_name=_("ethics statement"),
        help_text=_("Please upload human or animal ethics statement."),
        upload_to="statements",
        upload_subfolder=lambda instance: [hash_int(instance.application_id)],
        blank=True,
        null=True,
    )
    not_relevant = BooleanField(default=False, verbose_name=_("Not Applicable"))
    comment = TextField(_("Comment"), max_length=1000, null=True, blank=True)

    def natural_key(self):
        return (self.application.number, self.file.name)

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


class Member(PersonMixin, MemberMixin, PdfFileMixin, Model):
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
    )
    last_name = CharField(max_length=150, null=True, blank=True)
    role_description = CharField(
        _("legacy role"), max_length=200, null=True, blank=True, editable=False
    )
    role = ForeignKey(
        RoleType,
        on_delete=PROTECT,
        related_name="application_personnel",
        null=True,
        blank=True,
        db_column="role",
    )
    # has_authorized = BooleanField(null=True, blank=True)
    user = ForeignKey(User, null=True, blank=True, on_delete=SET_NULL, related_name="members")
    state = StateField(null=True, blank=True, default="new")
    state_changed_at = MonitorField(monitor="state", null=True, default=None, blank=True)
    authorized_at = MonitorField(
        monitor="state", when=["authorized"], null=True, default=None, blank=True
    )
    org = ForeignKey(
        Organisation, verbose_name=_("organisation"), on_delete=SET_NULL, null=True, blank=True
    )
    country = ForeignKey(
        Country,
        on_delete=SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("country"),
        db_column="country",
        related_name="members",
    )
    file = PrivateFileField(
        verbose_name=_("Host support letter"),
        help_text=_("Host support letter from your organisation"),
        upload_to="members",
        upload_subfolder=lambda instance: [hash_int(instance.application_id)],
        blank=True,
        null=True,
        max_length=200,
    )
    converted_file = ForeignKey(
        ConvertedFile, null=True, blank=True, on_delete=SET_NULL, verbose_name=_("converted file")
    )

    def natural_key(self):
        return (self.application.number, self.email)

    @property
    def thread_index(self):
        if self.application_id and (n := Nomination.where(application=self.application_id).last()):
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
        if application.pk:
            member_id = getattr(self, "id", None)
            q = application.members.filter(email__lower=self.email.lower())
            if member_id:
                q = q.filter(~Q(id=member_id))
            if q.exists():
                raise ValidationError(
                    _("Team member with the email address %(email)s was already added"),
                    params={"email": self.email},
                )

    @fsm_log
    @transition(field=state, source=["new", "sent", "bounced"], target="accepted")
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
                recipients=[recipient_email],
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
                recipients=[self.application.submitted_by.email],
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
            "  JOIN application AS a ON a.id = m.application_id "
            "  JOIN scheme AS s ON s.current_round_id = a.round_id "
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
        # help_text=_("Comma separated list of middle names"),
    )
    last_name = CharField(_("last name"), max_length=150, null=True, blank=True)
    # has_testifed = BooleanField(null=True, blank=True)
    user = ForeignKey(User, null=True, blank=True, on_delete=SET_NULL)
    org = ForeignKey(
        Organisation, verbose_name=_("organisation"), on_delete=SET_NULL, null=True, blank=True
    )
    state = StateField(_("referee state"), null=True, blank=True, default="new")
    state_changed_at = MonitorField(monitor="state", null=True, default=None, blank=True)
    testified_at = MonitorField(
        monitor="state", when=["testified"], null=True, default=None, blank=True
    )
    survey_token_id = PositiveIntegerField(null=True, blank=True, default=None)
    survey_token = CharField(max_length=100, null=True, blank=True, default=None)
    survey_invitation_sent_at = DateTimeField(null=True, blank=True, default=None)
    survey_completed_at = DateTimeField(null=True, blank=True, default=None)

    def save(self, *args, **kwargs):
        if not self.org:
            if u := (
                self.user
                or (ea := EmailAddress.objects.filter(email=self.email).last())
                and ea.user
            ):
                # if not self.user:
                #     self.org = u
                #     if "update_fields" in kwargs:
                #         kwargs["update_fields"].append("user")
                if (p := Person.where(user=u).first()) and (
                    af := p.affiliations.filter(type="EMP", end_date__isnull=True)
                    .order_by("-start_date")
                    .first()
                ):
                    self.org = af.org
                    if "update_fields" in kwargs:
                        kwargs["update_fields"].append("org")
        super().save(*args, **kwargs)

    def make_survey_token(self):
        return base64.urlsafe_b64encode(
            hashlib.shake_256(
                f"{(int(time.time()) if settings.DEBUG else self.pk)}".encode()
            ).digest(21)
        ).decode()

    def natural_key(self):
        return (self.application.number, self.email)

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
            q = application.referees.filter(email__lower=self.email.lower())
            if referee_id:
                q = q.filter(~Q(id=referee_id))
            if q.exists():
                raise ValidationError(
                    _("Referee with the email address %(email)s was already added"),
                    params={"email": self.email},
                )

    @classmethod
    def set_organisation(cls, request=None, by=None, queryset=None):
        if not by and request:
            by = request.by
        if not queryset:
            queryset = cls.where(
                org__isnull=True, application__round__scheme__current_round=F("application__round")
            )
        else:
            queryset = queryset.filter(org__isnull=True)
        updated_referees = []
        for r in queryset:
            u = r.user
            if not u:
                ea = EmailAddress.objects.filter(email=r.email.lower()).last()
                if ea:
                    u = ea.user
            if u:
                p = Person.where(user=u).last()
                emp = (
                    Affiliation.where(
                        type="EMP", person=p, end_date__isnull=True, org__isnull=False
                    )
                    .order_by("-start_date")
                    .first()
                )
                if emp:
                    r.org = emp.org
                    updated_referees.append(r)
            if not r.org:
                domain = r.email.lower().split("@")[1]
                org = Organisation.where(
                    Q(email__isnull=False, email__icontains=domain)
                    | Q(website__isnull=False, website__icontains=domain)
                    | Q(ro_email__isnull=False, ro_email__icontains=domain)
                ).first()
                if org:
                    r.org = org
                    updated_referees.append(r)
            if r.org:
                r._change_reason = f"assigned organisation {r.org} to the referee record"

        if updated_referees:
            bulk_update_with_history(
                updated_referees,
                Referee,
                ["org"],
                default_user=by,
                default_change_reason="assigned organisation to the referee record",
            )

            if request:
                messages.info(
                    request,
                    f"Assigned organisation to {len(updated_referees)} referee(s): "
                    f"{', '.join(f'{r.email}: {r.org.name}' for r in updated_referees)}",
                )
            return len(updated_referees)

    @classmethod
    def invite_referees(
        cls,
        request,
        application=None,
        by=None,
        referees=None,
        dispatch_invitations=True,
        exclude_sender=False,
    ):
        """Send invitations to all referee."""
        # members that don't have invitations
        count = 0
        # referees = list(models.Referee.where(application=application, invitation__isnull=True))
        # referees = list(models.Referee.where(invitation__isnull=True))
        # referees = list(models.Referee.where(~Q(invitation__email=F("email"))))
        if not referees:
            referees = list(
                cls.where(
                    ~Q(state__in=["testified", "accepted", "opted_out"]),
                    ~Q(invitation__email__lower=Lower("email")),
                    application=application,
                ).prefetch_related("application", "application__submitted_by")
            )

        for r in referees:
            Invitation.get_or_create_referee_invitation(
                r, by=r.application.submitted_by or by or request and request.user
            )

        # send 'yet unsent' invitations:
        invitations = (
            Invitation.where(
                Q(sent_at__isnull=True),
                ~Q(state__in=["accepted", "expired", "bounced", "revoked"]),
                application=application,
                type="R",
            )
            if application
            else Invitation.where(
                ~Q(state__in=["accepted", "expired", "bounced", "revoked"]),
                referee__in=Subquery(referees.values("id")),
            )
        ).prefetch_related("referee", "referee__user")
        if settings.SITE_ID in [1, 2, 7]:
            invitations = invitations.filter(~Q(application__file=""))
        elif settings.SITE_ID == 4:
            invitations = invitations.filter(
                application__documents__document_type__role="AF"
            ).distinct()

        if dispatch_invitations:
            for i in invitations:
                i.send(request, by=by or request and request.user, exclude_sender=exclude_sender)
                i.save()
                if i.referee:
                    i.referee.send()
                    i.referee.save()
                count += 1
            return count
        return invitations.count()

    @fsm_log
    @transition(field=state, source=["*"], target="accepted")
    def accept(self, *args, **kwargs):
        pass

    @cached_property
    def survey_api(self):
        return self.application.round.survey_api

    def activate_tokens(self, api=None):
        return self.application.round.activate_tokens(api=api)

    def add_to_survey(self, api=None):
        # Inviation to participate in the survey:
        if survey_id := self.application.round.survey_id:
            u = self.user
            if not u and (
                ea := EmailAddress.objects.filter(email__lower=self.email.lower()).first()
            ):
                u = ea.user
            first_name = self.first_name or u and u.first_name or ""
            last_name = self.last_name or u and u.last_name or ""

            if not api:
                api = self.survey_api
            has_participant_table = None
            if not self.survey_token or not self.survey_token_id:
                participant = {"email": self.email.lower()}
                # api.query(method="list_participants",params={"sSessionKey": api.session_key, "iSurveyID": survey_id, "aConditions":{"email": "nad2000+r1@gmail.com"}})
                for _ in range(2):  # 2 attempts
                    resp = api.query(
                        method="list_participants",
                        params={
                            "sSessionKey": api.session_key,
                            "iSurveyID": survey_id,
                            "aConditions": {"email": self.email.lower()},
                        },
                    )
                    if (
                        not has_participant_table
                        and isinstance(resp, dict)
                        and resp.get("status") == "Error: No survey participants table"
                    ):
                        self.activate_tokens(api=api)
                        has_participant_table = True
                        continue
                    break
                if resp and isinstance(resp, list):
                    tid = resp[0]["tid"]
                    token = resp[0]["token"]
                    self.survey_token_id = tid
                    self.survey_token = token
                    return

                if first_name:
                    participant["firstname"] = self.first_name
                if last_name:
                    participant["lastname"] = self.last_name
                token = self.survey_token or self.make_survey_token()
                participant["token"] = token

                has_participant_table = None
                for _ in range(2):  # 2 attempts
                    resp = api.token.add_participants(
                        survey_id, [participant], create_token_key=False
                    )
                    if (
                        not has_participant_table
                        and isinstance(resp, dict)
                        and resp.get("status") == "Error: No survey participants table"
                    ):
                        self.activate_tokens(api=api)
                        has_participant_table = True
                        continue
                    break

                if not isinstance(resp, list):
                    limesurvey_status = resp.get("status")
                    raise Exception(
                        _("Failed to add the referee: %s. Please contact a portal administration.")
                        % limesurvey_status
                    )
                for r in resp:
                    if (
                        "errors" in r
                        and "token" in r["errors"]
                        and " has already been taken." in r["errors"]["token"]
                    ):
                        r = api.token.get_participant_properties(survey_id, None, {"token": token})
                    if r.get("email") == self.email.lower():
                        self.survey_token_id = r.get("tid")
                        self.survey_token = r.get("token", token)
                        properties = api.token.get_participant_properties(
                            survey_id, self.survey_token_id
                        )
                        if (
                            int(properties.get("tid")) != int(self.survey_token_id)
                            or properties.get("token") != self.survey_token
                        ):
                            raise Exception(
                                f"Failed to sync with LimeSurvey of {self}", resp, properties
                            )

    def invite_to_survey(self, api=None, request=None):
        if survey_id := self.application.round.survey_id:
            if not api:
                api = self.survey_api
            has_participant_table = None

            if not self.survey_token:
                self.survey_token = self.make_survey_token()
                self._change_reason = f"Fixed and updated token"
                self.save(update_fields=["survey_token"])

            if not self.survey_token_id:
                try:
                    for _ in range(2):  # 2 attempts
                        resp = api.token.get_participant_properties(
                            survey_id, None, {"token": self.survey_token}
                        )
                        if (
                            not has_participant_table
                            and isinstance(resp, dict)
                            and resp.get("status") == "Error: No survey participants table"
                        ):
                            self.activate_tokens(api=api)
                            has_participant_table = True
                            continue
                        break
                    self.survey_token_id = resp.get("tid")
                    self.save(update_fields=["survey_token_id", "updated_at"])
                except LimeSurveyError:
                    self.add_to_survey(api=api)
                    self.save(update_fields=["survey_token_id", "survey_token", "updated_at"])

            if self.survey_token_id:
                for _ in range(2):  # 2 attempts
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
                    if (
                        not has_participant_table
                        and isinstance(resp, dict)
                        and resp.get("status") == "Error: No survey participants table"
                    ):
                        self.activate_tokens(api=api)
                        has_participant_table = True
                        continue
                    break
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
                                f"Failed to invite survey participant - referee {self}: {status}",
                                level="error",
                            )
                            if request:
                                messages.error(
                                    request,
                                    f"Failed to invite survey participant - referee {self}: {status}",
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
    def testify(self, request=None, by=None, description=True, commit=True, *args, **kwargs):
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
    def opt_out(self, user=None, request=None, *args, **kwargs):
        if not user:
            if request:
                user = request.user
            else:
                user = self.user
        # self.has_testifed = False
        a = self.application
        detail_url = a.get_full_detail_url(request)
        update_url = a.get_full_update_url(request)
        send_mail(
            # __("A Referee opted out of Testimonial"),
            # __("Your Referee %s has opted out of Testimonial") % t.referee,
            "A Referee opted out of Testimonial",
            html_message=(
                f"<p>The referee ({self.full_name}) your entered for you application for "
                f'<a href="{detail_url}">{a.number}</a> has declined to provide a testimonial.</p>'
                f'<p>Please login in to the Portal <a href="{update_url}">{a.number}</a> '
                "and enter a new referee.</p>"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipients=[a.submitted_by.email if a.submitted_by else a.email],
            fail_silently=False,
            request=request,
            reply_to=settings.DEFAULT_FROM_EMAIL,
        )
        if request:
            messages.info(
                request,
                _(
                    "You opted out of providing an application "
                    "supporting referee report/testimonial."
                ),
            )

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
            "  JOIN application AS a ON a.id = r.application_id "
            "  JOIN scheme AS s ON s.current_round_id = a.round_id "
            "  JOIN round ON round.id = a.round_id "
            "WHERE (r.user_id=%s OR ae.user_id=%s) AND r.state NOT IN ('testified', 'opted_out')"
            "  AND (round.testimonial_submission_closes_at IS NULL OR round.testimonial_submission_closes_at > %s)",
            [user.id, user.id, timezone.now()],
        )

    @cached_property
    def guidelines(self):
        return self.application.round.get_referee_guidelines()

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
        # help_text=_("Comma separated list of middle names"),
    )
    last_name = CharField(max_length=150, null=True, blank=True)
    # person = models.ForeignKey(Person, blank=True, null=True, on_delete=models.CASCADE, related_name="+")
    user = ForeignKey(User, null=True, blank=True, on_delete=SET_NULL, related_name="panellists")
    state_changed_at = MonitorField(monitor="state", null=True, default=None, blank=True)

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

    def natural_key(self):
        return (self.application.number, self.panellist.email)

    def __str__(self):
        # return f"{self.role}: {self.person}"
        return str(self.user or self.email)

    @property
    def mail_log_error(self):
        if ml := MailLog.where(invitation__panellist=self, error__isnull=False).last():
            return ml.error

    @cached_property
    def guidelines(self):
        return self.round.get_panellist_guidelines()

    # TODO: refactor and move to a common mixin
    def get_or_create_invitation(self, by=None):
        u = self.user or User.objects.filter(email__lower=self.email.lower()).first()
        if not u and (ea := EmailAddress.objects.filter(email__lower=self.email.lower()).first()):
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
                email=self.email.lower(),
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


INVITATION_TYPES = Choices(
    ("A", _("apply")),
    ("J", _("join")),
    ("R", _("testify")),
    ("T", _("authorize")),
    ("P", _("panellist")),
)

INVITATION_STATES = Choices(
    ("accepted", _("accepted")),
    ("autoreplied", _("auto-replied")),
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
        # help_text=_("Comma separated list of middle names"),
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
    state_changed_at = MonitorField(monitor="state", null=True, default=None, blank=True)
    submitted_at = MonitorField(
        monitor="state", when=["submitted"], null=True, default=None, blank=True
    )
    sent_at = MonitorField(monitor="state", when=["sent"], null=True, default=None, blank=True)
    accepted_at = MonitorField(
        monitor="state", when=["accepted"], null=True, default=None, blank=True
    )
    read_at = MonitorField(monitor="state", when=["read"], null=True, default=None, blank=True)
    expired_at = MonitorField(
        monitor="state", when=["expired"], null=True, default=None, blank=True
    )
    bounced_at = MonitorField(
        monitor="state", when=["bounced"], null=True, default=None, blank=True
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
            Q(email__lower=user.email.lower())
            | Q(nomination__user=user)
            | Q(member__user=user)
            | Q(referee__user=user)
            | Q(panellist__user=user)
            | Q(email__lower__in=user.emailaddress_set.values_list("email__lower"))
        ).distinct()

    @classmethod
    def update_round(cls, dry_run=False):
        objs = (
            cls.all_objects.filter(round__isnull=True)
            .annotate(
                round_value=Coalesce(
                    "application__round",
                    "nomination__round",
                    "member__application__round",
                    "referee__application__round",
                    "panellist__round",
                )
            )
            .filter(round_value__isnull=False)
        )  # .values("id", "round", "round_value")

        if dry_run:
            return objs.count()

        for o in objs:
            o.round_id = o.round_value

        return cls.all_objects.bulk_update(objs, ["round"])

    @classmethod
    def get_or_create_referee_invitation(cls, referee, by=None):
        u = referee.user or User.objects.filter(email__lower=referee.email.lower()).first()
        if not u and (
            ea := EmailAddress.objects.filter(email__lower=referee.email.lower()).first()
        ):
            u = ea.user
        if not referee.user and u:
            referee.user = u
            if not referee.first_name:
                referee.first_name = u and u.first_name or ""
            if not referee.last_name:
                referee.last_name = u and u.last_name or ""
            if not referee.middle_names:
                referee.middle_names = u and u.middle_names or ""
            referee.save(update_fields=["user", "first_name", "middle_names", "last_name"])
        first_name = referee.first_name or u and u.first_name or ""
        last_name = referee.last_name or u and u.last_name or ""
        middle_names = referee.middle_names or u and u.middle_names or ""
        site = (referee.application and referee.application.site) or Site.objects.get_current()

        if (
            site.pk in [4, 5]
            and referee.application.round.survey_id
            and not (referee.survey_token_id or referee.survey_token)
        ):
            referee.add_to_survey()

        if hasattr(referee, "invitation"):
            i = referee.invitation
            if referee.email != i.email:
                i.revoke(by=by)
                i.save()
            else:
                referee.satus = None
                return (i, False)

        i, created = cls.get_or_create(
            type=INVITATION_TYPES.R,
            referee=referee,
            email=referee.email.lower(),
            defaults=dict(
                inviter=by,
                application=referee.application,
                round=referee.application.round,
                first_name=first_name,
                middle_names=middle_names,
                last_name=last_name,
                site=site,
            ),
        )
        referee.invitation = i
        referee.save()
        return (i, created)

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

        # If the invitation has been sent:
        if self.state == "sent" or StateLog.objects.for_(self).filter(state="sent").exists():
            subject = "The invitation sent from %(site_name)s portal was revoked" % {
                "site_name": site_name
            }
            html_body = (
                "<p>Tēnā koe,</p>"
                "<p>The invitation previously sent from %(site_name)s portal was revoked.</p>"
            ) % {"site_name": site_name}

            send_mail(
                subject,
                html_message=html_body,
                recipients=[self.email],
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
        source=["draft", "sent", "submitted", "bounced", "autoreplied", "read"],
        target="sent",
    )
    def send(self, request=None, by=None, exclude_sender=False, *args, **kwargs):
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
            url = urljoin(f"https://{site.domain}", url)
        link_name = domain_to_macrons(url)
        self.url = url

        application = self.application
        if self.type == INVITATION_TYPES.T:
            if not self.member:
                return
            if not application:
                self.application = application = self.member.application
            if not application:
                return
            contact_email = (
                application and application.round.contact_email or site_contact_email(site_id)
            )
            subject = __("You are invited to be part of a %(site_name)s application") % {
                "site_name": site_name
            }
            inviter = (
                application
                and application.submitted_by
                and application.submitted_by.full_name
                or by.full_name
            )
            body = __(
                "Tēnā koe,\n\n"
                "You have been invited to join %(inviter)s's team for their %(site_name)s application. \n\n"
                "Before you click on the portal link we strongly advise you "
                "to read about the application process: %(guidelines)s.\n\n"
                "To review this invitation, please follow the link: %(url)s\n\n"
                "Ngā mihi"
            ) % dict(
                inviter=inviter,
                url=url,
                site_name=site_name,
                guidelines=application.round.get_applicant_guidelines(),
            )
            html_body = __(
                "<p>Tēnā koe,</p><p>You have been invited to join %(inviter)s's team for their "
                "%(site_name)s application.</p>"
                "<p>Before you click on the portal link we strongly advise you "
                'to read about the <a href="%(guidelines)s">application process</a>.</p>'
                "<p>To review this invitation, please follow the link: <a href='%(url)s'>%(link_name)s</a></p>"
            ) % dict(
                inviter=inviter,
                url=url,
                link_name=link_name,
                site_name=site_name,
                guidelines=application.round.get_applicant_guidelines(),
            )
        elif self.type == INVITATION_TYPES.R:
            referee = self.referee
            if not referee:
                return
            application = referee.application
            if not self.application:
                self.application = application
            inviter = (
                application
                and self.application.submitted_by
                and self.application.submitted_by.full_name
                or by.full_name
            )
            contact_email = application.round.contact_email or site_contact_email(site_id)
            subject = __("You are invited as a referee for a %(site_name)s application") % {
                "site_name": site_name
            }
            survey_link_name = None
            if survey_url := (
                referee.user
                and referee.application.round.survey_id
                and referee.survey_token_id
                and reverse("survey-referee", kwargs=dict(referee_id=self.referee_id))
            ):
                if request:
                    survey_url = request.build_absolute_uri(survey_url)
                else:
                    survey_url = urljoin(f"https://{site.domain}", survey_url)
                survey_url = f"{survey_url}?token={self.token}"
                survey_link_name = domain_to_macrons(survey_url)

            application_url = reverse(
                "application-detail", kwargs={"number": referee.application.number}
            )
            if request:
                application_url = request.build_absolute_uri(application_url)
            else:
                application_url = urljoin(f"https://{site.domain}", application_url)
            application_link_name = domain_to_macrons(application_url)

            body = (
                (
                    "Tēnā koe,\n\n"
                    "You have been invited to be a referee for %(inviter)s's application to "
                    'the "%(application)s". \n\n'
                    "We strongly advise clicking on the Referee Guidelines before clicking  "
                    "on the portal link below: %(guidelines)s\n\n"
                    "Please fill out the referee report/survey at %(survey_url)s "
                    "after reviewing the application at %(application_url)s.\n\n"
                    "If you have any further questions, please contact: %(contact_email)s\n\n"
                    "Ngā mihi nui"
                )
                if survey_url and site_id not in [2, 5]
                else (
                    "Tēnā koe,\n\n"
                    "You have been invited to be a referee for %(inviter)s's application to "
                    'the "%(application)s". \n\n'
                    "We strongly advise clicking on the Referee Guidelines before clicking  "
                    "on the portal link below: %(guidelines)s\n\n"
                    "To review this invitation, please follow the link: %(url)s\n\n"
                    "If you have any further questions, please contact: %(contact_email)s\n\n"
                    "Ngā mihi nui"
                )
            ) % dict(
                inviter=inviter,
                main_applicant=self.referee.application.submitted_by.full_name,
                url=url,
                survey_url=survey_url,
                survey_link_name=survey_link_name,
                application_url=application_url,
                application_link_name=application_link_name,
                site_name=site_name,
                application=self.referee.application,
                guidelines=self.referee.guidelines,
                contact_email=contact_email,
            )
            html_body = (
                (
                    "<p>Tēnā koe,</p><p>You have been invited by %(inviter)s to be a referee "
                    "for %(main_applicant)s's application to the "
                    '"%(application)s" application.</p>'
                    "<p>We strongly advise clicking on the Referee Guidelines <strong>before</strong> clicking  "
                    "on the portal link below.</p>"
                    "<p><a href='%(guidelines)s'>Referee Guidelines</a></p>"
                    "<p>Please fill out the <strong>referee report/survey</strong> at \n"
                    "<a href='%(survey_url)s'>%(survey_link_name)s</a> "
                    'after reviewing the application at <a href="%(application_url)s">%(application_link_name)s</a>.</p>\n'
                    "<p>If you have any further questions, please contact "
                    "<a href='%(contact_email)s'>%(contact_email)s</a></p>"
                )
                if survey_url and site_id not in [2, 5]
                else (
                    "<p>Tēnā koe,</p><p>You have been invited by %(inviter)s to be a referee "
                    "for %(main_applicant)s's application to the "
                    '"%(application)s" application.</p>'
                    "<p>We strongly advise clicking on the Referee Guidelines <strong>before</strong> clicking  "
                    "on the portal link below.</p>"
                    "<p><a href='%(guidelines)s'>Referee Guidelines</a></p>"
                    "<p><strong>To review this invitation, you are required to follow the portal link</strong>: "
                    "<a href='%(url)s'>%(link_name)s</a> after you have read about the process.</p>"
                    "<p>If you have any further questions, please contact "
                    "<a href='%(contact_email)s'>%(contact_email)s</a></p>"
                )
            ) % dict(
                inviter=inviter,
                main_applicant=self.referee.application.submitted_by.full_name,
                url=url,
                link_name=link_name,
                survey_url=survey_url,
                survey_link_name=survey_link_name,
                application_url=application_url,
                application_link_name=application_link_name,
                site_name=site_name,
                application=self.referee.application,
                guidelines=self.referee.guidelines,
                contact_email=contact_email,
            )
        elif self.type == INVITATION_TYPES.A:
            subject = "You have been nominated for %s" % self.nomination.round
            inviter = (
                self.nomination
                and self.nomination.nominator
                and self.nomination.nominator.full_name
                or by.full_name
            )
            body = (
                "Tēnā koe,\n\n"
                "Congratulations on being nominated for the %(round)s by %(inviter)s.\n\n"
                "Before you click on the portal link we strongly advise you "
                "to read about the application process: %(guidelines)s.\n\n"
                "To accept the nomination, please follow the portal link %(url)s\n\n\n"
                "Ngā mihi nui"
            ) % dict(
                round=self.nomination.round,
                inviter=inviter,
                guidelines=self.nomination.round.get_applicant_guidelines(),
                url=url,
            )
            html_body = (
                "<p>Tēnā koe,</p>"
                "<p>Congratulations on being nominated for the %(round)s by %(inviter)s.</p>"
                "<p>Before you click on the portal link we strongly advise you "
                'to read about the <a href="%(guidelines)s">application process</a>.</p>'
                "<p>To accept the nomination, please follow the portal link: "
                "<a href='%(url)s'>%(link_name)s</a><br></p></br>"
            ) % dict(
                round=self.nomination.round,
                inviter=inviter,
                guidelines=self.nomination.round.get_applicant_guidelines(),
                url=url,
                link_name=link_name,
            )
        elif self.type == INVITATION_TYPES.P:
            subject = __("You are invited to be a Panellist for the %(site_name)s") % {
                "site_name": site_name
            }
            body = (
                "Tēnā koe\n\n"
                "You are invited to be a panellist for the %(site_name)s.\n\n"
                "We strongly advise clicking on the Panellist Guidelines before clicking  "
                "on the portal link below: %(guidelines)s\n\n"
                "To review this invitation, please follow the link: %(url)s \n\n"
                "Ngā mihi"
            ) % {
                "url": url,
                "site_name": site_name,
                "guidelines": self.panellist.guidelines,
            }
            html_body = (
                "Tēnā koe,<br><br>You are invited to be a panellist for the %(site_name)s.<br><br>"
                "<p>We strongly advise clicking on the Panellist Guidelines <strong>before</strong> clicking  "
                "on the portal link below.</p>"
                "<p><a href='%(guidelines)s'>Panellist Guidelines</a></p>"
                "<p>To review this invitation, please follow the link: <a href='%(url)s'>%(link_name)s</a></p>"
            ) % {
                "url": url,
                "link_name": link_name,
                "site_name": site.name,
                "guidelines": self.panellist.guidelines,
            }
        else:
            subject = __("You have been given access to the %(site_name)s portal") % {
                "site_name": site_name
            }
            body = (
                "Tēnā koe,\n\n You have been given access to the %(site_name)s portal.\n\n"
                "To confirm this access, please follow the link: %(url)s \n\n"
                "Ngā mihi"
            ) % {"site_name": site_name, "url": url}
            html_body = (
                "Tēnā koe,<br><br>You have been given access to the %(site_name)s portal.<br><br>"
                "To confirm this access, please follow the link: <a href='%(url)s'>%(link_name)s</a><br>"
            ) % {"url": url, "link_name": link_name, "site_name": site_name}

        resp = send_mail(
            subject,
            body,
            html_message=html_body,
            recipients=[self.email],
            fail_silently=False,
            request=request,
            reply_to=by.email if by else settings.DEFAULT_FROM_EMAIL,
            invitation=self,
            cc=(
                None
                if exclude_sender
                else (
                    self.nomination
                    and [self.nomination.nominator.email]
                    or by
                    and [by.email]
                    or None
                )
            ),
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
            if (n := self.nomination) and (n.state != "accepted" or not n.user):
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
                    p.save(update_fields=["state", "user"])
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
                url = urljoin(f"https://{Site.objects.get_current().domain}", url)
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
                recipients=[self.inviter.email],
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
            "  LEFT JOIN scheme AS s ON s.current_round_id = i.round_id "
            "  LEFT JOIN round AS r ON r.id = i.round_id "
            "WHERE ae.user_id=%s AND i.state NOT IN ('accepted', 'expired', 'revoked') AND i.site_id=%s "
            """  AND (i."type" != 'R' OR r.testimonial_submission_closes_at IS NULL or r.testimonial_submission_closes_at > %s)""",
            [user.id, site_id, timezone.now()],
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
        upload_to="testimonials",
        upload_subfolder=lambda instance: [hash_int(instance.referee_id)],
        blank=True,
        null=True,
        max_length=200,
    )
    converted_file = ForeignKey(
        ConvertedFile, null=True, blank=True, on_delete=SET_NULL, verbose_name=_("converted file")
    )
    cv = ForeignKey(
        "CurriculumVitae",
        editable=True,
        null=True,
        blank=True,
        on_delete=RESTRICT,
        verbose_name=_("curriculum vitae"),
    )
    state = StateField(_("testimonial state"), default="new")
    state_changed_at = MonitorField(monitor="state", null=True, default=None, blank=True)

    @cached_property
    def application(self):
        return self.referee.application

    @cached_property
    def round(self):
        return self.application.round

    @fsm_log
    @transition(field=state, source=["new", "draft"], target="draft", custom=dict(admin=False))
    def save_draft(self, request=None, by=None, *args, **kwargs):
        pass

    @fsm_log
    @transition(field=state, source=["new", "draft"], target="submitted")
    def submit(self, request=None, by=None, commit=True, *args, **kwargs):
        # self.referee.has_testifed = True
        # self.referee.state = "testified"
        # self.referee.testified_at = datetime.now()
        if not by and request:
            by = request.user
        if self.referee.state != "testified":
            self.referee.testify(request=request, by=by, *args, **kwargs)
            if description := kwargs.get("description"):
                self.referee._change_reason = description
            if commit:
                self.referee.save()
        if self.site_id in [2, 5]:
            pass

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
            if self.site_id in [2, 4, 5]:
                return _("Referee report by {0} for {1}").format(
                    self.referee, self.referee.application
                )
            return _("Testimonial By Referee {0} For Application {1}").format(
                self.referee, self.referee.application
            )
        return self.file.name if self.file else gettext("N/A")

    def title_page(self):

        if self.site_id in [2, 5]:
            tp = {
                "TITLES": [_("Referee Report")],
                # _("Submitted At"): self.updated_at or self.created_at,
                # "file_name": self.filename,
            }
            tp[_("Referee")] = self.referee.full_name
            if org := self.referee.org:
                tp[_("Organisation")] = f"{org.code}: {org.name}"
                if org.address and org.address.country:
                    tp[_("Country")] = org.address.country.name

            return tp
        return super().title_page()

    class Meta:
        db_table = "testimonial"


simple_history.register(
    Testimonial, inherit=True, table_name="testimonial_history", bases=[TestimonialMixin, Model]
)

FILE_TYPE = Choices("CV")


# class PrivateFile(Model):

#     person = ForeignKey(Person, null=True, blank=True, on_delete=CASCADE)
#     owner = ForeignKey(User, on_delete=CASCADE)
#     type = CharField(max_length=100, choices=FILE_TYPE)
#     title = CharField("title", max_length=200, null=True, blank=True)
#     # file = PrivateFileField(upload_subfolder=lambda instance: f"cv-{instance.owner.id}")
#     file = PrivateFileField()

#     class Meta:
#         db_table = "private_file"


class CurriculumVitae(PdfFileMixin, PersonMixin, Model):
    person = ForeignKey(
        Person, on_delete=SET_NULL, verbose_name=_("person"), blank=True, null=True
    )
    owner = ForeignKey(User, on_delete=SET_NULL, verbose_name=_("owner"), blank=True, null=True)
    title = CharField(
        _("Title or name"),
        max_length=200,
        null=True,
        blank=True,
        help_text=_("A title or name you can assign to the upload CV file"),
    )
    file = PrivateFileField(
        upload_to="cv",
        upload_subfolder=lambda instance: [hash_int(instance.person_id or instance.owner_id)],
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

    def natural_key(self):
        return self.file.name

    @classmethod
    def last_user_cv(cls, user):
        return cls.where(Q(owner=user) | Q(person__user=user)).order_by("-id").first()

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


class Currency(Model):
    """ISO 4217 Currency Codes - https://datahub.io/core/currency-codes"""

    code = FixedCharField(
        max_length=3,
        primary_key=True,
        db_column="code",
        help_text="3 digit alphabetic code for the currency",
    )
    currency = CharField(max_length=100, help_text="Country or region name")
    numeric_code = PositiveSmallIntegerField(null=True, blank=True)
    minor_unit = PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        db_table = "currency"
        db_table_comment = "ISO 4217 Currency Codes - https://datahub.io/core/currency-codes"


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

    def natural_key(self):
        return self.code

    def save(self, *args, **kwargs):
        # if self.fund and self.fund.site and self.site != self.fund.site:
        #     self.site = self.fund.site
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
    if r.opens_on:
        return f"rounds/{r.scheme.code}-{r.opens_on.year}/{filename}"
    title = (r.title or r.scheme.title).lower().replace(" ", "-")
    if len(title) > 50:
        title = hashlib.shake_256(title.encode()).hexdigest(9)
    return f"rounds/{title}/{filename}"


class Round(TimeStampMixin, HelperMixin, OrderableModel):
    site = ForeignKey(Site, on_delete=PROTECT, default=Model.get_current_site_id)
    objects = CurrentSiteManager()
    all_objects = Manager()

    title = CharField(_("title"), max_length=100, null=True, blank=True)
    scheme = ForeignKey(Scheme, on_delete=CASCADE, related_name="rounds", verbose_name=_("scheme"))
    background = ColorField(
        null=True, blank=True, help_text="Colour used for text headers and back-grounds"
    )
    foreground = ColorField(
        null=True, blank=True, help_text="Colour used for text headers and fore-grounds"
    )

    opens_on = DateField(_("opens on"), null=True, blank=True)
    closes_at = DateTimeField(_("closes at"), null=True, blank=True)
    priorities = TaggableManager(
        blank=True,
        verbose_name=_("Available priorities"),
        help_text=_("Available research priorities"),
        through=ResearchPriorityItem,
    )
    testimonial_submission_closes_at = DateTimeField(
        null=True, blank=True, verbose_name="Testimonial submission closes at"
    )
    has_three_parties = BooleanField(_("has three party contracts"), default=False)
    is_partial_profile_allowed = BooleanField(
        help_text=_(
            "Partial profile allowed, applicant is not required "
            "to provide a complete user profile"
        ),
        default=False,
    )

    guidelines = URLField(
        _("round guidelines"),
        max_length=400,
        null=True,
        blank=True,
        help_text=_("Round guidelines link URL"),
    )
    applicant_guidelines = URLField(
        _("applicant guidelines"),
        max_length=400,
        null=True,
        blank=True,
        # help_text=_("Applicant guidelines link URL"),
        help_text=_("Applicant guidelines link URL"),
    )
    referee_guidelines = URLField(
        _("referee guidelines"),
        max_length=400,
        null=True,
        blank=True,
        help_text=_("Referee guidelines link URL"),
    )
    panellist_guidelines = URLField(
        _("panellist guidelines"),
        max_length=400,
        null=True,
        blank=True,
        help_text=_("Panellist guidelines link URL"),
    )
    contact_email = EmailField(_("round contact email address"), blank=True, null=True)
    limesurvey_server_url = URLField(
        _("LimeSurvey URL"),
        max_length=400,
        null=True,
        blank=True,
        help_text=_("LimeSurvey Server URL"),
    )
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
    nomination_form_required = BooleanField(_("Nomination form required"), default=True)
    testimonials_required = BooleanField(
        _("testimonials required"),
        default=True,
        help_text="required testimonials/referee reports",
    )

    has_referees = BooleanField(_("can invite referees"), default=True)
    required_referees = PositiveSmallIntegerField(
        _("Required number of referees"),
        null=True,
        blank=True,
        default=0,
        choices=Choices(0, 1, 2, 3, 4),
        help_text="Minimum of referees the application needs to nominate",
    )
    required_submitted_testimonials = BooleanField(
        _("required submitted testimonials"),
        default=True,
        help_text="required submitted testimonials or survey before submitting the applications",
    )

    is_flexible_number_of_referees = BooleanField(_("Flexible number of referees"), default=False)
    duration = PositiveSmallIntegerField(
        _("Duration"), help_text=_("Default contract duration"), null=True, blank=True
    )
    awarded_amount = DecimalField(
        max_digits=9,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Awarded amount / Fellowship total budgets",
    )
    referee_cv_required = BooleanField(_("Referee CV required"), default=True)
    survey_id = PositiveIntegerField(
        help_text=_("Referee LimeSurvey Survey ID"), null=True, blank=True
    )

    letter_of_support_required = BooleanField(default=False)
    research_experience_in_years_required = BooleanField(default=False)

    direct_application_allowed = BooleanField(default=True)
    can_nominate = BooleanField(default=True)
    notify_nominator = BooleanField(
        default=False,
        verbose_name=_("Notify nominator/principal/mentor"),
    )

    tac = TextField(
        _("T&C"), max_length=100000, null=True, blank=True, help_text=_("Terms and Conditions")
    )
    contract_background = TextField(
        _("contract background"),
        null=True,
        blank=True,
        help_text="Contract background information (point '<b>A</b>' in the contract background)",
    )
    agent_declaration = TextField(
        null=True,
        blank=True,
    )
    applicant_declaration = TextField(
        null=True,
        blank=True,
        help_text=_("Duly authorised agent (i.e. the research office) declaration."),
    )

    has_online_scoring = BooleanField(default=True)
    score_sheet_template = FileField(
        null=True,
        blank=True,
        upload_to=round_template_path,
        verbose_name=_("Score Sheet Template"),
        validators=[FileExtensionValidator(allowed_extensions=["xls", "xlsx"])],
    )
    can_specify_panel = BooleanField(default=False)
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
    schedule2 = PrivateFileField(
        verbose_name="Schedule 2",
        help_text="Standard terms and conditions (preferably converted into PDF with OpenOffice or LibreOffice)",
        null=True,
        blank=True,
        upload_to="rounds",
        upload_subfolder=lambda instance: [
            hash_int(instance.pk),
            "parts",
        ],
        validators=[FileExtensionValidator(allowed_extensions=CONTRACT_PART_EXTENSIONS)],
    )
    appendix_a = PrivateFileField(
        verbose_name="Appendix A",
        help_text="Declaration regarding compliance with the Society's code "
        "of professional standards and ethics (preferably converted into PDF with OpenOffice or LibreOffice)",
        null=True,
        blank=True,
        upload_to="rounds",
        upload_subfolder=lambda instance: [
            hash_int(instance.pk),
            "parts",
        ],
        validators=[FileExtensionValidator(allowed_extensions=CONTRACT_PART_EXTENSIONS)],
    )
    appendix_b = PrivateFileField(
        verbose_name="Appendix B",
        help_text="Eligibility Criteria (MUST HAVE EXACTLY 1 PAGE! "
        "SHOULD BE converted into PDF with OpenOffice or LibreOffice)",
        null=True,
        blank=True,
        upload_to="rounds",
        upload_subfolder=lambda instance: [
            hash_int(instance.pk),
            "parts",
        ],
        validators=[FileExtensionValidator(allowed_extensions=["pdf"])],
    )

    @property
    def code(self):
        if self.opens_on:
            yy = f"{self.opens_on.year:02d}"
        elif self.closes_at:
            yy = f"{self.closes_at.year:02d}"
        else:
            yy = f"{timezone.now().year:02d}"
        return f"{self.scheme.code}{yy}"

    @property
    def previous_round(self):
        return self._meta.model.where(scheme=self.scheme).order_by("-id").first()

    @property
    def has_categories(self):
        return (
            self.has_fors
            or self.has_seos
            or self.has_toas
            or self.has_vmts
            or self.has_keywords
            or self.can_specify_panel
            or self.research_experience_in_years_required
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
    report_template = FileField(
        null=True,
        blank=True,
        upload_to=round_template_path,
        verbose_name=_("Report Template"),
        help_text=_("Research report template"),
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

    funding_amount = PositiveIntegerField(null=True, blank=True)
    funding_currency = ForeignKey(
        Currency, on_delete=SET_NULL, null=True, blank=True, db_column="currency", default="NZD"
    )

    def natural_key(self):
        return (self.scheme.code, self.opens_on)

    @cache
    def get_guidelines(self):
        if not self.guidelines and (
            pr := Round.where(Q(guidelines__isnull=False) | ~Q(guidelines=""), scheme=self.scheme)
            .order_by("-id")
            .first()
        ):
            return pr.guidelines
        return self.guidelines

    @cache
    def get_applicant_guidelines(self):
        if self.applicant_guidelines:
            return self.applicant_guidelines
        if (
            pr := Round.where(
                Q(applicant_guidelines__isnull=False) | ~Q(applicant_guidelines=""),
                scheme=self.scheme,
            )
            .order_by("-id")
            .first()
        ) and pr.applicant_guidelines:
            return pr.applicant_guidelines
        if gl := self.get_guidelines():
            if gl.endswith("/"):
                return f"{gl}information-for-applicants/"
            return f"{gl}/information-for-applicants/"

    @cache
    def get_referee_guidelines(self):
        if self.referee_guidelines:
            return self.referee_guidelines
        if (
            pr := Round.where(
                Q(referee_guidelines__isnull=False) | ~Q(referee_guidelines=""),
                scheme=self.scheme,
            )
            .order_by("-id")
            .first()
        ) and pr.referee_guidelines:
            return pr.referee_guidelines
        if gl := self.get_guidelines():
            if gl.endswith("/"):
                return f"{gl}information-for-referees/"
            return f"{gl}/information-for-referees/"

    @cache
    def get_panellist_guidelines(self):
        if self.panellist_guidelines:
            return self.panellist_guidelines
        if (
            pr := Round.where(
                Q(panellist_guidelines__isnull=False) | ~Q(panellist_guidelines=""),
                scheme=self.scheme,
            )
            .order_by("-id")
            .first()
        ) and pr.panellist_guidelines:
            return pr.panellist_guidelines
        if gl := self.get_guidelines():
            if gl.endswith("/"):
                return f"{gl}information-for-panellists/"
            return f"{gl}/information-for-panellists/"

    @property
    def is_active(self):
        return self.scheme.current_round == self

    def clean(self):
        if (
            self.opens_on
            and self.closes_at
            and datetime.combine(self.opens_on, datetime.min.time()).timestamp()
            > self.closes_at.timestamp()
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

        scheme = self.scheme or last_round.scheme
        if last_round:

            for f in [f.name for f in self._meta.fields]:
                if (
                    f in ["title", "opens_on", "closes_at", "id", "title_en", "title_mi"]
                    or getattr(self, f, None) is not None
                ):
                    continue
                v = getattr(last_round, f)
                setattr(self, f, v)
                # if v is not None and getattr(self, f) is None:

            if not self.scheme or self.scheme != last_round.scheme:
                if not self.opens_on and last_round.opens_on:
                    self.opens_on = last_round.opens_on + relativedelta(years=1)

                if not self.closes_at and last_round.closes_at:
                    self.closes_at = last_round.closes_at + relativedelta(years=1)
            else:
                self.opens_on = last_round.opens_on
                self.closes_at = last_round.closes_at

        if not self.opens_on:
            self.opens_on = timezone.now()

        if not self.title_en:
            title = scheme.title_en
            if self.opens_on:
                title = f"{title} {self.opens_on.year}"
            else:
                title = f"{title} {timezone.now().year}"
            self.title_en = title

        if self.title_en == scheme.title_en and self.opens_on:
            self.title_en = f"{self.title_en} {self.opens_on.year}"

        if not self.title_mi:
            title = scheme.title_mi
            if self.opens_on:
                title = f"{title} {self.opens_on.year}"
            else:
                title = f"{title} {timezone.now().year}"
            self.title_mi = title

        if self.title_mi == scheme.title_mi and self.opens_on:
            self.title_mi = f"{self.title_mi} {self.opens_on.year}"

        if self.site_id in [2, 4, 5]:
            for f in [
                "applicant_cv_required",
                "direct_application_allowed",
                "ethics_statement_required",
                "letter_of_support_required",
            ]:
                setattr(self, f, False)

        return self

    def clone(self, scheme=None, copy=False, *args, **kwargs):
        if copy:
            nr = Round.get(self.pk)
            nr.pk = None
            if scheme:
                nr.scheme = scheme
        else:
            nr = Round(scheme=scheme or self.scheme)
            nr.init_from_last_round(last_round=self)

        if not nr.title or copy:
            nr.title = self.scheme.title
        if nr.title == self.scheme.title and nr.opens_on:
            nr.title = f"{nr.title} {nr.opens_on.year}"

        with transaction.atomic():
            nr.save()
            # nr.tags.add(*self.tags.all())
            nr.priorities.add(*self.priorities.all())

            # NB! Keep the order
            for m in [
                self.application_form_templates,
                self.contract_clauses,
                self.curriculum_vitae_templates,
                self.required_documents,
                self.required_contract_documents,
                self.templates,
                self.performance_flags,
            ]:
                objs = [o for o in m.all()]
                for o in objs:
                    o.pk = None
                    o.round = nr

                if isinstance(m, RequiredContractDocument):
                    for o in objs:
                        rd = nr.required_documents.filter(
                            document_type=o.application_required_document.document_type,
                            role=o.application_required_document.role,
                            format=o.application_required_document.format,
                            title=o.application_required_document.title,
                        ).last()
                        if rd:
                            o.application_required_document = rd

                m.field.model.objects.bulk_create(objs)

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
                "nomination_form_required",
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

            if "closes_at" not in kwargs and last_round.closes_at:
                self.closes_at = kwargs["closes_at"] = last_round.closes_at + relativedelta(
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

            if self.site_id in [2, 4, 5] or settings.SITE_ID in [2, 4, 5]:
                for f in [
                    "applicant_cv_required",
                    "direct_application_allowed",
                    "ethics_statement_required",
                    "letter_of_support_required",
                ]:
                    setattr(self, f, False)

    def __str__(self):
        return self.title or self.scheme.title

    def get_absolute_url(self):
        return f"{reverse('applications')}?round={self.id}"

    def user_nominations(self, user):
        return Nomination.where(
            Q(user=user)
            | Q(
                Q(email__in=user.emailaddress_set.values_list("email__lower"))
                | Q(org__research_offices__user=user)
            ),
            state__in=["submitted", "accepted"],
            round=self,
        )

    def user_has_nomination(self, user):
        """User has a nomination to apply for the round."""

        return self.user_nominations(user).exists()

    @cached_property
    def deadline_seconds(self):
        if closes_at := self.closes_at:
            now = datetime.now(tz=closes_at.tzinfo)
            if closes_at >= now:
                ts = closes_at - now
                return ts.total_seconds()

    @cached_property
    def deadline_days(self):
        if ds := self.deadline_seconds:
            return round(ds / 86400)

    @cached_property
    def deadline_hours(self):
        if ds := self.deadline_seconds:
            return round(ds / 3600)

    @cached_property
    def deadline_minutes(self):
        if ds := self.deadline_seconds:
            return round(ds / 60)

    @cached_property
    def is_open(self):
        return self.opens_on <= date.today() and (
            self.closes_at is None or self.closes_at >= datetime.now(tz=self.closes_at.tzinfo)
        )

    @cached_property
    def has_closed(self):
        return self.closes_at and self.closes_at < datetime.now(tz=self.closes_at.tzinfo)

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
                SELECT a.id, count(r.id) AS referee_count,
                    sum(CASE WHEN r.state='testified'
                    -- OR has_testified
                    THEN 1 ELSE 0 END) AS submitted_reference_count
                FROM application AS a
                    LEFT JOIN referee AS r ON r.application_id=a.id
                WHERE a.round_id=%s AND a.site_id=%s
                GROUP BY a.id
            ), member_summary AS (
                SELECT a.id, count(m.id) AS member_count,
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
                LEFT JOIN person AS p ON p.user_id = u.id
                LEFT JOIN scheme ON scheme.current_round_id = a.round_id
            WHERE a.round_id=%s AND a.site_id=%s
            ORDER BY a.number
            """,
            [self.id, site_id, self.id, site_id, self.id, site_id],
        )

    @classmethod
    def current_rounds(cls):
        return cls.where(id=F("scheme__current_round__id"))

    @cached_property
    def survey_server_url(self):
        if self.limesurvey_server_url:
            return self.limesurvey_server_url
        if settings.DEBUG and "LIMESURVEY_SERVER_URL" in dir(settings):
            return settings.LIMESURVEY_SERVER_URL
        else:
            site = self.site or Site.objects.get_current()
            return f"https://{site.domain}/limesurvey"

    @cached_property
    def survey_api_url(self):
        if settings.DEBUG and "LIMESURVEY_API_URL" in dir(settings):
            return settings.LIMESURVEY_API_URL
        elif server_url := self.survey_server_url:
            return f"{server_url}/admin/remotecontrol"
        else:
            site = self.site or Site.objects.get_current()
            return f"https://{site.domain}/limesurvey/admin/remotecontrol"

    @cached_property
    def survey_api(self):
        if api_url := self.survey_api_url:
            api = LimeSurvey(url=api_url, username=settings.LIMESURVEY_API_USERNAME)
            api.open(password=settings.LIMESURVEY_API_PASSWORD)
            return api

    def activate_tokens(self, api=None):
        if not api:
            api = self.survey_api
            return api.query(
                method="activate_tokens",
                params={
                    "sSessionKey": api.session_key,
                    "iSurveyID": self.survey_id,
                },
            )

    def sync_referee_surveys(self, request=None, by=None, referees=None):
        if not self.survey_id:
            return 0
        try:
            q = Referee.where(application__round=self)  # , survey_token__isnull=False)
            if referees:
                q = q.filter(pk__in=referees.values_list("pk"))
            fixed_referees = []
            api = self.survey_api
            q = q.filter(
                Q(survey_token_id__isnull=True) | Q(survey_token__isnull=True) | Q(survey_token="")
            )
            has_participant_table = None
            for r in q:
                if not r.survey_token:
                    r.survey_token = r.make_survey_token()
                try:
                    for _ in range(2):  # 2 attempts
                        resp = api.token.get_participant_properties(
                            self.survey_id, None, {"token": r.survey_token}
                        )
                        if (
                            not has_participant_table
                            and isinstance(resp, dict)
                            and resp.get("status") == "Error: No survey participants table"
                        ):
                            self.activate_tokens(api=api)
                            has_participant_table = True
                            continue
                        r.survey_token_id = resp.get("tid")
                        break
                except LimeSurveyError:
                    for _ in range(2):  # 2 attempts
                        resp = r.add_to_survey(api=api)
                        if (
                            not has_participant_table
                            and isinstance(resp, dict)
                            and resp.get("status") == "Error: No survey participants table"
                        ):
                            self.activate_tokens(api=api)
                            has_participant_table = True
                            continue
                        break
                fixed_referees.append(r)
            if fixed_referees:
                bulk_update_with_history(
                    fixed_referees,
                    Referee,
                    [
                        "survey_token_id",
                        "survey_token",
                        "updated_at",
                    ],
                    default_user=request and request.user,
                    default_change_reason="Fixed the Lime Survey Token",
                )

            # q = q.filter(Q(user=request.user) | Q(email=request.user.email))
            resp = api.query(
                method="list_participants",
                params={
                    "sSessionKey": api.session_key,
                    "iSurveyID": self.survey_id,
                    # "bUnused": True,
                    "aAttributes": ["email", "token", "completed", "token", "sent", "emailstatus"],
                    "aConditions": {
                        "token": ["IN", *(r.survey_token for r in q)],
                        "completed": ["<>", "N"],
                    },
                },
            )
            if isinstance(resp, dict) and resp.get("status") == "No survey participants found.":
                # return 0
                resp = []
            participants = {
                p["token"]: {
                    "completed_at": (
                        timezone.make_aware(parse(p["completed"]))
                        if p.get("completed")
                        and not (p["completed"] == "N" or p["completed"].startswith("1980-01-01"))
                        else None
                    ),
                    **p,
                }
                for p in resp
            }
            updated_referees = []
            updated_testimonials = []
            for r in q:
                token = r.survey_token or r.make_survey_token()
                p = participants.get(r.survey_token)
                if p and not r.survey_token:
                    r.survey_token = token
                    r.survey_token_id = p.get("tid")
                    r._change_reason = f"Updated token and token ID"
                    r.save(update_fields=["survey_token", "survey_token_id"])
                if not p or not p["completed_at"]:
                    continue

                if (
                    r.state == "testified"
                    and p["tid"] == r.survey_token_id
                    and p["completed_at"] == r.survey_completed_at
                    and not Testimonial.where(~Q(state="submitted"), referee=r).exists()
                ):
                    continue

                r.survey_completed_at = p["completed_at"]
                if not r.survey_token_id or r.survey_token_id != p["tid"]:
                    r.survey_token_id = p["tid"]
                r.survey_completed_at = p["completed_at"]
                r._change_reason = f"Synced with LimeSurvey. Referee report was completed at {r.survey_completed_at}"
                if request:
                    r._history_user = request.user
                if not self.testimonials_required and r.state != "testified":
                    r.testify(request, by=request.user, description=r._change_reason, commit=False)
                    if not r.testified_at or r.testified_at < r.survey_completed_at:
                        r.testified_at = r.survey_completed_at
                updated_referees.append(r)

            if updated_referees:
                with transaction.atomic():

                    if not self.testimonials_required:
                        updated_testimonials = []
                        testimonials = Testimonial.where(
                            ~Q(state="submitted"), referee__in=[r.pk for r in updated_referees]
                        )
                        if testimonials.count() > 0:
                            for t in testimonials:
                                description = f"Synced with LimeSurvey"
                                t.submit(by=r.user, description=description, commit=False)
                                t._change_reason = description
                                updated_testimonials.append(t)
                            bulk_update_with_history(
                                updated_testimonials,
                                Testimonial,
                                ["state", "state_changed_at", "updated_at"],
                                default_user=request and request.user,
                                default_change_reason="Synced with LimeSurvey",
                            )
                        bulk_update_with_history(
                            updated_referees,
                            Referee,
                            [
                                "state",
                                "survey_completed_at",
                                "survey_token_id",
                                "testified_at",
                                "state_changed_at",
                                "updated_at",
                            ],
                            default_user=request and request.user,
                            default_change_reason="Synced with LimeSurvey",
                        )

            # Re-sync testimonials with the referees:
            updated_testimonials = []
            description = "Synced with LimeSurvey"
            for r in Referee.where(
                (
                    Q(
                        ~Q(testimonial__state="submitted") | Q(state_changed_at__isnull=True),
                        testimonial__file__isnull=False,
                    )
                    if self.testimonials_required
                    else Q(
                        Q(testimonial__isnull=True)
                        | ~Q(testimonial__state="submitted")
                        | Q(state_changed_at__isnull=True),
                    )
                ),
                state="testified",
                application__round=self,
            ):
                t, _ = Testimonial.get_or_create(referee=r)
                if t.state != "submitted":
                    t.submit(
                        by=r.user or request.user,
                        description=description,
                        commit=False,
                        request=request,
                    )
                    t._change_reason = description
                    if not t.state_changed_at:
                        t.state_changed_at = max(
                            filter(
                                lambda d: d,
                                [r.survey_completed_at, r.testified_at, r.state_changed_at],
                            )
                        )
                    updated_testimonials.append(t)
            bulk_update_with_history(
                updated_testimonials,
                Testimonial,
                ["state", "state_changed_at", "updated_at"],
                default_user=request and request.user,
                default_change_reason="Synced with LimeSurvey",
            )

        except Exception as ex:
            messages.error(request, f"{ex}")
            raise
        else:
            count = len(updated_referees) or len(updated_testimonials)
            if request:
                if count:
                    messages.info(
                        request,
                        f"Synced {count} referee(s): {', '.join(r.email for r in updated_referees)}",
                    )
            return count

    class Meta(OrderableModel.Meta):
        db_table = "round"


class PerformanceFlag(TimeStampMixin, HelperMixin, OrderableModel):
    round = ForeignKey(Round, on_delete=CASCADE, related_name="performance_flags")
    name = CharField(max_length=400)
    value_choices = CharField(
        max_length=400,
        null=True,
        blank=True,
        help_text="given in the format: 'VALUE1:DESCRIPTION1;VALUE2:DESCRIPTION2;...', otherwise it is 'YES' or 'NO'",
    )
    is_optional = BooleanField(default=True)

    def save(self, *args, **kwargs):
        created = not self or not self.pk
        super().save(*args, **kwargs)
        if created:
            assessed_permances = [
                AssessedPerformance(
                    report=r,
                    flag=self,
                    value="N" if not self.is_optional and not self.value_choices else None,
                )
                for r in Report.where(
                    ~Q(state__in=["assessed", "archived"]),
                    ~Q(performance__flag__in=[self]),
                    contract__application__round_id=self.round_id,
                )
            ]
            if assessed_permances:
                AssessedPerformance.bulk_create(assessed_permances)

    class Meta(OrderableModel.Meta):
        db_table = "performance_flag"


class RequiredDocument(TimeStampMixin, HelperMixin, OrderableModel):
    round = ForeignKey(Round, on_delete=CASCADE, related_name="required_documents")
    # TODO: should be removed at some stage
    document_type = ForeignKey(
        DocumentType, on_delete=CASCADE, related_name="required_documents", null=True, blank=True
    )
    role = CharField(max_length=10, choices=DOCUMENT_ROLES, null=True, blank=True)
    # name = CharField(_("Name"), max_length=200, blank=True, default="")
    format = CharField(
        choices=Choices(
            ("I", _("Image")), ("S", _("Spreadsheet")), ("T", _("Text")), ("-", _("N/A"))
        ),
        default="-",
        max_length=1,
    )
    # TODO: should be removed at some stage or renamend to 'name'
    title = CharField(_("Title"), max_length=200, null=True, blank=True)
    is_optional = BooleanField(default=False)
    referees_can_access = BooleanField(default=True)
    panellists_can_access = BooleanField(default=True)
    exclude = BooleanField(default=False, help_text=_("Exclude from the final export"))
    min_pages = PositiveSmallIntegerField(null=True, blank=True)
    max_pages = PositiveSmallIntegerField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.role:
            self.role = self.document_type.role
        if not self.format:
            self.format = self.document_type.format
        super().save(*args, **kwargs)

    def __str__(self):
        dt = self.document_type.name
        title = self.title or dt
        if title == dt:
            return title
        return f"{dt}: {title}"

    class Meta(OrderableModel.Meta):
        db_table = "required_document"


class RoundContractClause(TimeStampMixin, HelperMixin, OrderableModel):
    round = ForeignKey(Round, on_delete=CASCADE, related_name="contract_clauses")
    type = FixedCharField(
        _("Type"), max_length=1, choices=Choices(("A", _("Addition")), ("V", _("Variation")))
    )
    clause = CharField(_("Clause Number"), max_length=100)
    term = TextField(_("Term"), max_length=2000)

    def __str__(self):
        return f"{self.get_type_display()}: {self.clause}"

    class Meta(OrderableModel.Meta):
        db_table = "round_contract_clause"


class RoundDocumentTemplate(Model):
    round = ForeignKey(Round, on_delete=CASCADE, related_name="templates")
    document_type = ForeignKey(
        DocumentType, on_delete=SET_NULL, null=True, blank=True, related_name="templates"
    )
    required_document = ForeignKey(
        RequiredDocument,
        on_delete=SET_NULL,
        null=True,
        blank=True,
        related_name="templates",
        help_text="NB! Save the round with the required documents "
        "before assigning the themplates to the required documents!",
    )
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
    # TODO: remove at some stage
    document_type = ForeignKey(
        DocumentType, related_name="application_documents", on_delete=CASCADE
    )
    required_document = ForeignKey(
        RequiredDocument, on_delete=DO_NOTHING, related_name="documents"
    )
    page_count = PositiveSmallIntegerField(null=True, blank=True)
    file = PrivateFileField(
        blank=True,
        null=True,
        upload_to="applications",
        upload_subfolder=lambda instance: [
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
                    "gif",
                    "jpeg",
                    "jpg",
                    "odm",
                    "odt",
                    "oth",
                    "ott",
                    "pdf",
                    "png",
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

    def natural_key(self):
        return (self.application.number, self.file.name)

    def save(self, *args, **kwargs):
        if not self.file.name:
            return
        if not self.document_type_id:
            self.document_type = self.required_document.document_type
        super().save(*args, **kwargs)

    def __str__(self):
        if self.document_type_id:
            return f"{self.document_type}: {os.path.basename(self.file.name)}"
        elif self.required_document and self.file:
            return f"{self.required_document}: {os.path.basename(self.file.name)}"
        elif self.file:
            return os.path.basename(self.file.name)
        elif self.required_document:
            return f"{self.required_document}"
        return "N/A"

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

    def natural_key(self):
        return (self.application.number, self.panellist.email)

    def calc_evaluation_score(self):
        return sum(
            s.value * s.criterion.scale if s.criterion.scale else s.value
            for s in Score.where(evaluation=self)
        )

    @property
    def thread_index(self):
        if self.application_id and (n := Nomination.where(application=self.application_id).last()):
            idx = n.id
        else:
            idx = self.application_id
        site_id = self.application and self.application.site_id or settings.SITE_ID
        return base64.b64encode(f"{site_id}:{idx}".encode()).decode()

    @property
    def thread_topic(self):
        return self.application and self.application.number

    @fsm_log
    @transition(field=state, source=["draft", "new"], target="draft", custom=dict(admin=False))
    def save_draft(self, *args, **kwargs):
        self.total_score = self.calc_evaluation_score()

    @fsm_log
    @transition(field=state, source=["new", "draft", "submitted"], target="submitted")
    def submit(self, *args, **kwargs):
        self.total_score = self.calc_evaluation_score()
        if not self.comment:
            raise ValidationError(_("The review is not completed. Missing an overall comment."))

    @fsm_log
    @transition(
        field=state,
        source=["submitted"],
        target="draft",
        custom=dict(verbose="Request resubmission", button_name="Request resubmission"),
    )
    def request_resubmission(self, request=None, by=None, *args, **kwargs):
        if request:
            url = request.build_absolute_uri(reverse("evaluation-update", {"pk", self.pk}))
            subject = __("Please re-evaluate the application and resubmit your scores")
            body = __("Please re-evaluate the application and resubmit your scores: %s") % url

            send_mail(
                subject,
                body,
                recipients=[self.panellist.email or self.panellist.user.email],
                fail_silently=False,
                request=request,
                reply_to=(
                    request.user.email if request and request.user else settings.DEFAULT_FROM_EMAIL
                ),
                thread_index=self.thread_index,
                thread_topic=self.thread_topic,
            )

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

    def natural_key(self):
        return (self.evaluation.application.number, self.evaluation.panellist.email)

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
    ordering = PositiveIntegerField(_("ordering"), null=True, blank=True)
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
                r.ordering,
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
            /*LEFT */JOIN round AS r ON r.id = s.current_round_id AND r.site_id = %s
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
            ORDER BY r.ordering, 3;""",
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
    ("withdrawn", _("withdrawn")),
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
        # help_text=_("Comma separated list of middle names"),
    )
    last_name = CharField(_("last name"), max_length=150)
    position = CharField(
        max_length=80,
        blank=True,
        null=True,
        verbose_name=_("position"),
        help_text="position or role or the nominee, e.g., student, postdoc, etc.",
    )
    org = ForeignKey(
        Organisation,
        null=True,
        blank=True,
        on_delete=CASCADE,
        verbose_name=_("organisation"),
        help_text=_("Organisation of the nominee"),
    )
    nominator = ForeignKey(User, on_delete=CASCADE, related_name="nominations")
    contact_phone = CharField(
        _("Contact phone number"),
        validators=[phone_regex_validator],
        max_length=24,
        blank=True,
        null=True,
    )
    summary = TextField(blank=True, null=True)
    file = PrivateFileField(
        null=True,
        blank=True,
        upload_to="nominations",
        upload_subfolder=lambda instance: [hash_int(instance.nominator_id)],
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
        on_delete=RESTRICT,
        verbose_name=_("Curriculum Vitae"),
    )

    state = StateField(_("state"), null=True, blank=True, default="new")

    def natural_key(self):
        return (self.round.code, self.email)

    def clean(self, *args, **kwargs):
        super().clean(*args, **kwargs)
        user = self.nominator
        if (
            user
            and not user.is_superuser
            and (
                self.email == user.email
                or EmailAddress.objects.filter(email__lower=self.email.lower(), user=user)
            )
        ):
            raise ValidationError(_("You cannot nominate yourself for this round."))

    def get_nominator_orgs(self, nominator=None):
        """List of organisations that nominator can nominate on behalf of"""
        if not nominator:
            nominator = self.nominator
        site_id = self.site_id

        if site_id in [2, 4, 5] and nominator.research_offices.count():
            return Organisation.where(research_offices__user=nominator).order_by("-pk")
        q = (
            Organisation.where(
                affiliations__person__user=nominator, affiliations__end_date__isnull=True
            )
            .distinct()
            .order_by("affiliations__start_date")
        )
        if q.count():
            return q
        return Organisation.objects.none()

    @cached_property
    def nominated_by_ro(self):
        return ResearchOffice.where(
            user=self.nominator_id,
            org=(self.org_id or (self.application and self.application.org_id)),
        ).exists()

    @fsm_log
    @transition(field=state, source=["new", "draft"], target="draft", custom=dict(admin=False))
    def save_draft(self, *args, **kwargs):
        pass

    @fsm_log
    @transition(field=state, source=["*"], target="withdrawn")
    def withdraw(self, *args, **kwargs):
        pass

    def send_invitation(self, *args, **kwargs):
        i, created = Invitation.get_or_create(
            type=INVITATION_TYPES.A,
            nomination=self,
            email=self.email,
            defaults=dict(
                first_name=self.first_name,
                round=self.round,
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
    def user_nominations(
        cls,
        user,
        state=None,
        round=None,
        select_related=True,
        include_inactive=False,
        request=None,
        queryset=None,
        exclude_states=None,
    ):
        q = queryset or cls.objects.all()
        # q = cls.where(round__site=Site.objects.get_current())
        if not user and request:
            user = request.user

        if select_related:
            prefetch_related_objects(q, "round")

        if not (user.is_superuser or user.is_staff or user.is_site_staff):
            # if not state or (state == "submitted" or "submitted" in state):
            q = q.filter(
                Q(nominator=user)
                | Q(org__research_offices__user=user)
                | Q(nominator__research_offices__org__research_offices__user=user)
                | Q(
                    Q(Q(user=user) | Q(email=user.email)),
                    state="submitted",
                )
            ).distinct()
        if not include_inactive:
            q = q.filter(round__scheme__current_round=F("round"))

        if state:
            if isinstance(state, (list, tuple)):
                q = q.filter(state__in=state)
            else:
                q = q.filter(state=state)
        if exclude_states:
            q = q.filter(~Q(state__in=exclude_states))

        return q

    @classmethod
    def user_nomination_count(cls, user, state=None, round=None, request=None):
        return cls.user_nominations(
            user=user, state=state, round=round, select_related=False, request=request
        ).count()

    @classmethod
    def user_nomination_counts(
        cls, user, state=None, round=None, request=None, exclude_states=None
    ):
        return (
            cls.where(
                pk__in=cls.user_nominations(
                    user=user,
                    state=state,
                    round=round,
                    select_related=False,
                    request=request,
                    exclude_states=exclude_states,
                ).values("pk")
            )
            .values_list("state")
            .annotate(total=Count("state"))
            .order_by()
        )

    @classmethod
    def __user_nomination_count(cls, user, state=None):
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
            sql += " n.state IN ('new', 'draft', 'submitted', 'accepted') OR n.state IS NULL"
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
        upload_to="ids",
        upload_subfolder=lambda instance: [hash_int(instance.user_id)],
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

    def natural_key(self):
        return (self.application.number, self.user.username)

    @property
    def thread_index(self):
        if self.application_id and (n := Nomination.where(application=self.application_id).last()):
            idx = n.id
        else:
            idx = self.application_id
        site_id = self.application and self.application.site_id or settings.SITE_ID
        return base64.b64encode(f"{site_id}:{idx}".encode()).decode()

    @property
    def thread_topic(self):
        return self.application and self.application.number

    @fsm_log
    @transition(field=state, source="new", target="draft", custom=dict(admin=False))
    def save_draft(self, *args, **kwargs):
        pass

    @fsm_log
    @transition(
        field=state, source=["new", "draft", "needs-resubmission", "sent", "read"], target="sent"
    )
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
            recipients=list(
                User.where(
                    ~Q(email=""),
                    staff_of_sites__id=settings.SITE_ID,
                    is_staff=True,
                    email__isnull=False,
                )
                .distinct()
                .values_list("name", "email__lower")
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
            recipients=[self.user.email],
            fail_silently=False,
            request=request,
            reply_to=(
                request.user.email if request and request.user else settings.DEFAULT_FROM_EMAIL
            ),
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
    subject = CharField(max_length=1000)
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
        upload_to="score-sheets",
        upload_subfolder=lambda instance: [
            (
                instance.round.title.lower().replace(" ", "-")
                if instance.round.title
                else hash_int(instance.round_id)
            ),
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


def invite_referees(
    site_id=None, request=None, rounds=None, by=None, applications=None, after_round_closes=None
):
    """
    Invite referees to review the accepted applications
    after the round closes.
    """
    if site_id:
        settings.SITE_ID = site_id
    else:
        site_id = int(settings.SITE_ID)
    if not applications and rounds:
        applications = Application.where(round__in=rounds.values_list("pk"))
    if not applications:
        applications = Application.where(round__scheme__current_round=F("round"))
    if site_id in [2, 5]:
        applications = applications.filter(state__in=["accepted", "in_review"])
    elif site_id in [1, 4, 7]:
        applications = applications.filter(
            Q(~Q(file="") | ~Q(documents__document_type__role="AF"))
        )

    if after_round_closes:
        applications = applications.filter(round__closes_at__lte=timezone.now())
    if rounds:
        applications = applications.filter(round__in=rounds.values_list("pk"))
    count = 0
    for a in applications.distinct():
        state = a.state
        if not by:
            ah = a.history.filter(state="submitted").order_by("-history_id").first()
            by = ah and ah.history_user or by
        if site_id in [2, 5] and a.state != "in_review":
            count += a.send_out_to_referees(by=by, request=request, exclude_sender=True)
        else:
            count += a.invite_referees(by=by, request=request, exclude_sender=True)
        if a.state != state:
            a.save()
    return count


def clean_converted_file_cache(dry_run=False):
    root_dir = Path(settings.PRIVATE_STORAGE_ROOT) / "converted"
    cf_count = 0
    for cf in ConvertedFile.all_objects.filter(
        created_at__lt=timezone.now() - timedelta(days=-90)
    ):
        has_file = Path(cf.file.path).is_file()
        if has_file:
            size = os.path.getsize(cf.file.path)
            print(f"*** Deleted expired file: '{cf.file.name}' ({size} bytes)")
        else:
            print(f"*** Deleted expired file: '{cf.file.name}' (0 bytes)")
        if not dry_run:
            if has_file:
                cf.file.delete()
            cf.delete()
            # os.remove(cf.file.path)
        cf_count += 1

    for cf in ConvertedFile.all_objects.all():
        if not Path(cf.file.path).is_file():
            print(f"*** Deleted file record with missing file: '{cf.file.name}'")
            if not dry_run:
                cf.delete()
            cf_count += 1

    for root, dirs, files in os.walk(root_dir):
        rel_dir = os.path.relpath(root, root_dir)
        for rel_name in files:
            filename = os.path.join(rel_dir, rel_name)
            if not ConvertedFile.all_objects.filter(file=filename).exists():
                full_filename = os.path.join(root_dir, filename)
                size = os.path.getsize(full_filename)
                if not dry_run:
                    os.remove(full_filename)
                print(f"*** Deleted orphaned file: '{filename}' ({size} bytes)")
                cf_count += 1
    if cf_count:
        print(f"*** Deleted {cf_count} files")


def refresh_page_counts(dry_run=False):
    for m in apps.get_models():
        if (
            issubclass(m, PdfFileMixin)
            and not issubclass(m, simple_history.models.HistoricalChanges)
            and any(f.name == "page_count" for f in m._meta.fields)
        ):
            count = m.refresh_page_counts(commit=not dry_run)
            print(f"*** Refreshed {count} page counts for {m._meta.verbose_name_plural}")


def clean_private_fils(dry_run=False):
    root_dir = settings.PRIVATE_STORAGE_ROOT
    total = 0
    file_fields = sorted(
        [f for m in apps.get_models() for f in m._meta.fields if isinstance(f, PrivateFileField)],
        key=lambda f: f.upload_to.split("/")[0],
    )
    file_fields = {
        dir_name: list(file_fields)
        for (dir_name, file_fields) in groupby(
            file_fields, lambda f: f"{f.upload_to.split('/')[0]}/"
        )
    }

    for root, dirs, files in os.walk(root_dir):
        rel_dir = os.path.relpath(root, root_dir)
        for rel_name in files:
            filename = os.path.join(rel_dir, rel_name)
            for f in file_fields.get(f"{rel_dir.split('/')[0]}/", []):
                if (
                    getattr(f.model, "all_objects", f.model.objects)
                    .filter(**{f.name: filename})
                    .exists()
                ):
                    break
            else:
                full_filename = os.path.join(root_dir, filename)
                size = os.path.getsize(full_filename)
                if not dry_run:
                    os.remove(full_filename)
                print(f"*** Deleted orphaned file: '{filename}' ({size} bytes)")
                total += size

            # if (
            #     (rel_dir.startswith("cv/") and not CurriculumVitae.where(file=filename).exists())
            #     or (
            #         rel_dir.startswith("converted/")
            #         and not ConvertedFile.where(file=filename).exists()
            #     )
            #     or (
            #         rel_dir.startswith("ids/")
            #         and not IdentityVerification.where(file=filename).exists()
            #         and not Application.where(photo_identity=filename).exists()
            #     )
            #     or (
            #         rel_dir.startswith("score-sheets/")
            #         and not ScoreSheet.where(file=filename).exists()
            #     )
            #     or (
            #         rel_dir.startswith("nominations/")
            #         and not Nomination.where(file=filename).exists()
            #     )
            #     or (
            #         rel_dir.startswith("applications/")
            #         and not Application.where(file=filename).exists()
            #         and not ApplicationDocument.where(file=filename).exists()
            #     )
            #     or (
            #         rel_dir.startswith("letters_of_support/")
            #         and not LetterOfSupport.where(file=filename).exists()
            #     )
            #     or (
            #         rel_dir.startswith("testimonials/")
            #         and not Testimonial.where(file=filename).exists()
            #     )
            #     or (
            #         rel_dir.startswith("score-sheets/")
            #         and not ScoreSheet.where(file=filename).exists()
            #     )
            #     or (
            #         rel_dir.startswith("statements/")
            #         and not EthicsStatement.where(file=filename).exists()
            #     )
            #     or (
            #         rel_dir.startswith("budget/")
            #         and not Application.where(budget=filename).exists()
            #     )
            #     or (
            #         rel_dir.startswith("contracts/")
            #         and not (
            #             ContractComment.where(attachment=filename).exists()
            #             or ContractCommentAttachment.where(attachment=filename).exists()
            #             or ContractDocument.where(file=filename).exists()
            #         )
            #     )
            # ):
            #     full_filename = os.path.join(root_dir, filename)
            #     size = os.path.getsize(full_filename)
            #     if dry_run:
            #         os.remove(full_filename)
            #     print(f"*** Deleted orphaned file: '{filename}' ({size} bytes)")
            #     total += size

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

    def __str__(self):
        return f"{self.org}: {self.user}"

    class Meta:
        db_table = "research_office"


class EducationLevel(Model):
    code = PositiveSmallIntegerField(_("code"), primary_key=True)
    name = CharField(_("Name"), max_length=100)

    class Meta:
        db_table = "education_level"


PANEL_STATES = Choices(
    ("new", _("new")),
    ("draft", _("draft")),
    ("preliminary", _("preliminary")),
    ("active", _("active")),
    ("archived", _("archived")),
)


class PanelManager(Manager):
    def get_by_natural_key(self, code, fund, state, *args, **kwargs):
        return self.filter(code=code, fund=fund, state=state, **kwargs).last()


class PanelMixin:
    STATES = PANEL_STATES


class Panel(PanelMixin, Model):
    state = StateField(default="new")
    code = CharField(_("code"), max_length=3, blank=True, null=True)
    description = CharField(_("description"), max_length=255, blank=True, null=True)
    fund = ForeignKey("Fund", on_delete=SET_NULL, blank=True, null=True)
    # panellists = models.ManyToManyField(Person, through=Panellist, related_name="panels")

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


class PanelDecision(Model):
    site = ForeignKey(Site, on_delete=PROTECT, default=Model.get_current_site_id)
    objects = CurrentSiteManager()
    all_objects = Manager()

    number = CharField(
        max_length=24,
        primary_key=True,
        help_text="Application/proposal number",
        db_column="number",
    )
    grade = PositiveSmallIntegerField("Grade%", blank=True, null=True)
    decision = FixedCharField(
        max_length=1,
        choices=Choices(
            ("Y", _("Yes, funded")),
            ("N", _("Not funded")),
            ("R", _("Reserve")),
            ("I", _("Ineligible")),
        ),
    )
    panel = CharField(_("panel"), max_length=3, blank=True, null=True)
    rank = PositiveSmallIntegerField(blank=True, null=True)

    def natural_key(self):
        return (self.number,)

    def __str__(self):
        return f"{self.number} ({self.grade}/{self.rank}): {self.decision}"

    class Meta:
        db_table = "panel_decision"


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
    contract = ForeignKey("Contract", on_delete=CASCADE)
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


class ContractComment(CommentModel):

    @property
    def object(self):
        return self.contract

    @property
    def object_pk(self):
        return self.contract_id

    contract = ForeignKey("Contract", on_delete=CASCADE, related_name="comments")
    # reply_to = ForeignKey("self", on_delete=CASCADE, related_name="replies", null=True, blank=True)
    # token = CharField(max_length=42, default=get_unique_invitation_token, unique=True)
    # comment = TextField(_("comment"), max_length=1000, null=True, blank=True)
    # attachment = PrivateFileField(
    #     _("attachment"),
    #     upload_to="contracts",
    #     upload_subfolder=lambda instance: [
    #         # "contracts",
    #         # hash_int(instance.application_id),
    #         hash_int(instance.contract_id),
    #         "comments",
    #     ],
    #     null=True,
    #     blank=True,
    # )
    # submitted_by = ForeignKey(
    #     User,
    #     null=True,
    #     blank=True,
    #     on_delete=SET_NULL,
    #     verbose_name=_("submitted by"),
    #     related_name="contract_comments",
    # )

    # def __str__(self):
    #     return f"Submitted by {self.submitted_by} at {self.created_at}"

    # @property
    # def target(self):
    #     return self.contract

    class Meta(CommentModel.Meta):
        db_table = "contract_comment"
        default_related_name = "contract_comments"


class ContractCommentRecipient(Model):

    comment = ForeignKey(ContractComment, on_delete=CASCADE, related_name="recipients")
    user = ForeignKey(User, on_delete=SET_NULL, null=True, blank=True, related_name="+")
    email = EmailField(max_length=200)
    is_cced = BooleanField(default=False)

    class Meta:
        db_table = "contract_comment_recipient"
        verbose_name = _("recipient")


class ContractCommentAttachment(Model):
    comment = ForeignKey(ContractComment, on_delete=CASCADE, related_name="attachments")
    attachment = PrivateFileField(
        _("attachment"),
        upload_to="contracts",
        upload_subfolder=lambda instance: [
            # hash_int(instance.application_id),
            hash_int(instance.comment.contract_id),
            "comments",
            hash_int(instance.comment_id),
            "attachments",
        ],
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "contract_comment_attachment"
        verbose_name = _("attachment")


class ContractEthicsStatement(PdfFileMixin, Model):
    contract = OneToOneField("Contract", on_delete=CASCADE, related_name="ethics_statement")
    file = PrivateFileField(
        verbose_name=_("ethics statement"),
        help_text=_("Please upload human or animal ethics statement."),
        upload_to="contracts",
        upload_subfolder=lambda instance: ["ethics_statement", hash_int(instance.comment_id)],
        blank=True,
        null=True,
    )
    not_relevant = BooleanField(default=False, verbose_name=_("Not Applicable"))
    comment = TextField(_("Comment"), max_length=1000, null=True, blank=True)

    def natural_key(self):
        return (self.contract.number, self.file.name)

    class Meta:
        db_table = "contract_ethics_statement"


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
        ("accepted", _("Accepted")),
        ("approved", _("Approved")),
        ("archived", _("Archived")),
        ("cancelled", _("Cancelled")),
        ("draft", _("WIP")),
        ("new", _("new")),
        ("preliminary", _("Preliminary")),
        ("submitted", _("Submitted")),
        ("released", _("Released")),
        ("current", _("Current ")),
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


class Contract(ContractMixin, PersonMixin, PdfFileMixin, CommentMixin, VMTOAModel):
    site = ForeignKey(Site, on_delete=PROTECT, default=Model.get_current_site_id)
    panel = ForeignKey(Panel, on_delete=SET_NULL, null=True, blank=True)
    objects = ContractManager()
    all_objects = Manager()
    tags = TaggableManager(blank=True)

    number = CharField(_("number"), max_length=40, unique=True)
    host_number = CharField(_("host_number"), max_length=100, null=True, blank=True)
    refcode = CharField(null=True, blank=True, max_length=40, help_text=_("IE-Contracts REFCODE"))
    year = CharField(max_length=4, blank=True, null=True)
    org = ForeignKey(
        Organisation, on_delete=CASCADE, related_name="contracts", null=True, blank=True
    )
    # proposal = models.ForeignKey(Proposal, on_delete=models.CASCADE, blank=True, null=True)
    application = ForeignKey(
        Application, on_delete=CASCADE, blank=True, null=True, related_name="contracts"
    )
    awarded_amount = DecimalField(max_digits=9, decimal_places=2, null=True, blank=True)
    address = ForeignKey(
        Address, blank=True, null=True, related_name="contracts", on_delete=RESTRICT
    )
    submitted_by = ForeignKey(
        User, null=True, blank=True, on_delete=SET_NULL, verbose_name=_("submitted by")
    )
    project_title = CharField(
        max_length=200, null=True, blank=True, verbose_name=_("project title")
    )
    state = StateField(default="new", verbose_name=_("state"))
    state_changed_at = MonitorField(monitor="state", null=True, default=None, blank=True)

    start_date = DateField(blank=True, null=True)
    end_date = DateField(blank=True, null=True)
    duration = PositiveIntegerField(blank=True, null=True)

    notes = TextField(blank=True, null=True)
    abstract = TextField(blank=True, null=True)
    completed_on = DateField(blank=True, null=True)

    requires_approval = BooleanField(
        _("ethical and regulatory approval is required"),
        default=False,
        # null=True, blank=True,
        help_text=_("Does your research require ethical and regulatory approval?"),
    )
    requires_approval_comment = TextField(null=True, blank=True)
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
    involves_children = BooleanField(
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
    priorities = TaggableManager(
        blank=True,
        verbose_name=_("Priorities"),
        help_text=_("Research priorities"),
        through=ResearchPriorityItem,
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
    host_contact_email = EmailField(
        _("host contact email address"), max_length=120, null=True, blank=True
    )
    contact = CharField(
        _("Contact"),
        max_length=200,
        blank=True,
        null=True,
        help_text=_("Contact - an organisational role or a person name"),
    )
    contact_phone = CharField(
        _("Contact phone number"),
        validators=[phone_regex_validator],
        max_length=24,
        blank=True,
        null=True,
    )
    cover = PrivateFileField(
        verbose_name="Cover page",
        null=True,
        blank=True,
        upload_to="contracts",
        upload_subfolder=lambda instance: [
            hash_int(instance.pk),
            "parts",
        ],
        validators=[FileExtensionValidator(allowed_extensions=CONTRACT_PART_EXTENSIONS)],
    )
    preamble = PrivateFileField(
        verbose_name="Preamble",
        null=True,
        blank=True,
        upload_to="contracts",
        upload_subfolder=lambda instance: [
            hash_int(instance.pk),
            "parts",
        ],
        validators=[FileExtensionValidator(allowed_extensions=CONTRACT_PART_EXTENSIONS)],
    )
    schedule1 = PrivateFileField(
        verbose_name="Schedule 1",
        null=True,
        blank=True,
        upload_to="contracts",
        upload_subfolder=lambda instance: [
            hash_int(instance.pk),
            "parts",
        ],
        validators=[FileExtensionValidator(allowed_extensions=CONTRACT_PART_EXTENSIONS)],
    )
    schedule2 = PrivateFileField(
        verbose_name="Schedule 2",
        null=True,
        blank=True,
        upload_to="contracts",
        upload_subfolder=lambda instance: [
            hash_int(instance.pk),
            "parts",
        ],
        validators=[FileExtensionValidator(allowed_extensions=CONTRACT_PART_EXTENSIONS)],
    )
    file = PrivateFileField(
        verbose_name="Contract File",
        null=True,
        blank=True,
        upload_to="contracts",
        upload_subfolder=lambda instance: [
            hash_int(instance.pk),
        ],
        validators=[FileExtensionValidator(allowed_extensions=["pdf"])],
    )
    is_variation = BooleanField(
        help_text="Is this a variation of another contract?", default=False
    )
    source = ForeignKey(
        "self", on_delete=SET_NULL, null=True, blank=True, related_name="derivatives"
    )

    # "ie-contracts"
    ## total_amount = IntegerField(null=True, blank=True)
    ## actual_amount = IntegerField(null=True, blank=True)
    ## currency = IntegerField(null=True, blank=True)

    def __str__(self):
        # return f"{self.number}: {self.project_title or self.application.application_title or self.application.round.title}"
        return f"{self.number}: {self.pi or self.project_title or self.application.application_title or self.application.round.title}"

    @classmethod
    def user_object_counts(
        cls, user, state=None, round=None, request=None, queryset=None, *args, **kwargs
    ):
        return (
            cls.user_objects(
                user=user, state=state, round=round, select_related=False, request=request
            )
            .values_list("state")
            .annotate(total=Count("pk", distinct=True))
            .order_by()
        )

    @classmethod
    def user_objects(
        cls,
        user,
        state=None,
        round=None,
        select_related=True,
        request=None,
        queryset=None,
        *args,
        **kwargs,
    ):
        q = queryset or cls.objects.all()

        if select_related:
            prefetch_related_objects(q, "application__round")

        if state:
            if isinstance(state, (list, tuple)):
                q = q.filter(state__in=state)
            else:
                q = q.filter(state=state)
        else:
            q = q.filter(~Q(state="archived"))

        if user.is_staff or user.is_superuser or user.is_site_staff:
            return q

        f = (
            Q(submitted_by=user)
            | Q(application__submitted_by=user)
            | Q(members__user=user)
            | Q(org__research_offices__user=user)
        )
        q = q.filter(f)
        q = q.distinct()

        return q

    @classmethod
    def create_from_application(
        cls,
        application=application,
        awarded_amount=None,
        duration=None,
        start_date=None,
        end_date=None,
        *args,
        **kwargs,
    ):

        a = application
        if not awarded_amount:
            awarded_amount = a.round.awarded_amount
        if awarded_amount:
            a.awarded_amount = awarded_amount
            a.save(update_fields=["awarded_amount"])
        elif not awarded_amount and a.awarded_amount:
            awarded_amount = a.awarded_amount
        r = a.round
        number = cls.new_number(application=a)
        if not duration:
            duration = r.duration or 3
        address = a.address or a.org.address
        if not address or "DUMMY" in address.address and a.postal_address:
            city_country = Address.where(Q(city=a.city) | Q(postcode=a.postcode)).last()
            country = city_country and city_country.country
            address, _ = Address.get_or_create(
                address=a.postal_address, city=a.city, postcode=a.postcode, country=country
            )
        elif address and any(
            not getattr(a, n, None)
            and getattr(address, n, None)
            or getattr(a, n, None) != getattr(address, n, None)
            for n in ["city", "postcode"]
        ):
            address.pk = None
            for n in ["city", "postcode"]:
                if getattr(a, n, None):
                    setattr(address, n, getattr(a, n, None))
            if any(getattr(address, n, None) for n in ["city", "postcode"]):
                lines = [l for l in (a.address or address.address).splitlines() if l.strip()][-1]
                if lines:
                    last_line = lines[-1]
                    parts = [p for p in last_line.split() if p and p.isalpha()]
                    country = Country.where(Q(name__in=parts) | Q(name=last_line)).last()
                    if country and not address.country:
                        address.country = country
                    if len(parts) > 1 and parts[-1].isdecimal():
                        address.postcode = parts[-1]
                        address.city = " ".join(parts[:-1])
            if not address.country:
                address.country = Country.where(code="NZ").last()
            address.save()
        elif not address.country:
            address.pk = None
            address.country = Country.where(code="NZ").last()
            address.save()

        org = a.org
        if not start_date:
            if a.proposed_start_date:
                start_date = a.proposed_start_date
            elif a.site_id in [2, 5]:
                start_date = timezone.now().date().replace(day=1, month=3)
            else:
                start_date = timezone.now().date().replace(day=1) + relativedelta(months=1)
        params = dict(
            application=a,
            year=a.created_at.year,
            org=org,
            project_title=a.application_title or a.round.title,
            duration=duration,
            start_date=start_date,
            end_date=end_date
            or duration
            and (start_date + relativedelta(years=duration, days=-1)),
            number=number,
            fund=a.round.scheme.fund,
            address=address,
            state="draft",
            abstract=a.summary,
        )
        if awarded_amount:
            params["awarded_amount"] = awarded_amount
        if host_contact_email := (
            (
                hce_contract := cls.where(
                    ~Q(host_contact_email__isnull=True),
                    ~Q(host_contact_email=""),
                    application__round__scheme=a.round.scheme,
                    org=org,
                ).last()
            )
            and hce_contract.host_contact_email
            or org
            and (org.email or org.ro_email)
        ):
            params["host_contact_email"] = host_contact_email
        if contact := (
            (
                contact_contract := cls.where(
                    ~Q(contact__isnull=True),
                    ~Q(contact=""),
                    application__round__scheme=a.round.scheme,
                    org=org,
                ).last()
            )
            and contact_contract.contact
            or org
            and org.contact
        ):
            params["contact"] = contact
        if contact_phone := (
            (
                contact_phone_contract := cls.where(
                    ~Q(contact_phone__isnull=True),
                    ~Q(contact_phone=""),
                    application__round__scheme=a.round.scheme,
                    org=org,
                ).last()
                # or cls.where(
                #     ~Q(contact_phone__isnull=True),
                #     ~Q(contact_phone=""),
                #     org=org,
                # ).last()
            )
            and contact_phone_contract.contact_phone
            or org
            and org.contact_phone
        ):
            params["contact_phone"] = contact_phone

        if r.has_vmts:
            params.update(
                dict(
                    vm_ecs=a.vm_ecs,
                    vm_ens=a.vm_ens,
                    vm_hsw=a.vm_hsw,
                    vm_ink=a.vm_ink,
                )
            )
        if r.has_toas:
            params.update(
                dict(
                    toa_applied=a.toa_applied,
                    toa_basic=a.toa_basic,
                    toa_strategic=a.toa_strategic,
                    toa_experimental=a.toa_experimental,
                )
            )

        with transaction.atomic():
            c = cls.create(**params)
            c.fors.add(*a.fors.all())
            c.seos.add(*a.seos.all())
            c.keywords.add(*a.keywords.all())
            documents = []
            for crd in r.required_contract_documents.order_by("ordering"):
                # Handling Eligibility Criteria:
                if crd.role == "EC":
                    if r.appendix_b:
                        documents.append(
                            c.documents.model(
                                contract=c,
                                page_count=1,
                                document_type=crd.document_type,
                                required_document=crd,
                                file=r.appendix_b,
                                state="released",
                            )
                        )
                    else:
                        documents.append(
                            c.documents.model(
                                contract=c,
                                page_count=1,
                                document_type=crd.document_type,
                                required_document=crd,
                                # file=r.appendix_b,
                            )
                        )
                    continue

                if crd.application_required_document:
                    d = (
                        a.documents.filter(
                            required_document=crd.application_required_document
                        ).last()
                        or a.documents.filter(
                            document_type=crd.application_required_document.document_type
                            or crd.document_type
                        ).last()
                    )
                else:
                    d = (
                        a.documents.filter(document_type=crd.document_type).last()
                        or a.documents.filter(required_document__role=crd.role).last()
                    )

                if d and d.file:
                    documents.append(
                        c.documents.model(
                            contract=c,
                            page_count=d.page_count or d.update_page_count(),
                            document_type=crd.document_type
                            or d.document_type
                            or d.required_document.document_type,
                            required_document=crd,
                            file=d.file,
                            converted_file=d.converted_file,
                            state="draft",
                        )
                    )

            # for d in a.documents.all():
            #     rd = (
            #         r.required_contract_documents.filter(
            #             application_required_document=d.required_document
            #         ).last()
            #         or r.required_contract_documents.filter(
            #             document_type=d.document_type or d.required_document.document_type
            #         ).last()
            #         or RequiredContractDocument.create(
            #             round=r,
            #             document_type=d.document_type or d.required_document.document_type,
            #             role=d.required_document.role or d.required_document.document_type.role,
            #             format=d.required_document.format
            #             or d.required_document.document_type.format,
            #             title=d.required_document.title or d.required_document.document_type.name,
            #             is_optional=d.required_document.is_optional,
            #             application_required_document=d.required_document,
            #         )
            #     )

            #     documents.append(
            #         c.documents.model(
            #             contract=c,
            #             page_count=d.page_count,
            #             document_type=rd
            #             and rd.document_type
            #             or d.document_type
            #             or d.required_document.document_type,
            #             required_document=rd,
            #             file=d.file,
            #         )
            #     )

            # TODO: handle the legacy
            if a.file and not a.documents.filter(document_type__role="AF").exists():
                rd = RequiredContractDocument.where(
                    Q(role="AF") | Q(document_type__role="AF")
                ).last()
                documents.append(
                    c.documents.model(
                        contract=c,
                        document_type=rd
                        and rd.document_type
                        or DocumentType.where(role="AF").last(),
                        required_document=rd,
                        file=a.file,
                        converted_file=a.converted_file,
                        state="draft",
                    )
                )
            if a.budget and not a.documents.filter(document_type__role="B").exists():
                rd = RequiredContractDocument.where(
                    Q(role="B") | Q(document_type__role="B")
                ).last()
                documents.append(
                    c.documents.model(
                        contract=c,
                        document_type=rd
                        and rd.document_type
                        or DocumentType.where(role="B").last(),
                        required_document=rd,
                        file=a.budget,
                    )
                )

            for d in documents:
                if not d.page_count:
                    d.update_page_count()

            if documents:
                c.documents.model.bulk_create(documents)

            members = []
            for m in a.members.filter(authorized_at__isnull=False):
                u = m.user
                members.append(
                    ContractMember(
                        contract=c,
                        email=m.email and m.email.strip() or m.get_org_email(org=a.org),
                        first_name=m.first_name or u and u.first_name,
                        middle_names=m.middle_names or u and u.middle_names,
                        last_name=m.last_name or u and u.last_name,
                        role=m.role,
                        user=u,
                        address=u and u.person and u.person.address,
                    )
                )
            if not a.members.filter(role="PI").exists():
                u = a.submitted_by
                members.append(
                    ContractMember(
                        contract=c,
                        email=u.email,
                        first_name=a.first_name,
                        middle_names=a.middle_names,
                        last_name=a.last_name,
                        role_id="PI",
                        user=u,
                        address=a.address or u.person.address,
                    )
                )
            if members:
                c.members.model.bulk_create(members)

            efforts = []
            for m in c.members.all():
                efforts.extend(
                    ContractMemberEffort(
                        member=m,
                        period=e.period,
                        fte=e.fte or (0.8 if m.role_id == "PI" else None),
                    )
                    for e in MemberEffort.where(member__user=m.user, member__application=a)
                )

            if efforts:
                MemberEffort.bulk_create(efforts)

            if c.duration:
                ReportingScheduleEntry.bulk_create(
                    [
                        ReportingScheduleEntry(
                            contract=c,
                            period=p,
                            type="A" if p != c.duration else "F",
                            due_date=(c.start_date + relativedelta(years=p)).replace(day=1)
                            + relativedelta(days=-1),
                            date_first_remind=(c.start_date + relativedelta(years=p)).replace(
                                day=1
                            )
                            + relativedelta(days=-1, months=-1),
                        )
                        for p in range(1, c.duration + 1)
                    ]
                )

                allocation = (awarded_amount / c.duration) if awarded_amount else 0.0
                allocations = [round_number(allocation, 0)] * c.duration
                if awarded_amount:
                    allocations[-1] = awarded_amount - sum(allocations[:-1])

                Allocation.bulk_create(
                    [
                        Allocation(
                            contract=c,
                            period=p,
                            allocation=allocations[p - 1],
                            purpose=(
                                "To contribute towards the Key Contact Person's salary, "
                                "Organisational overheads and Research related expenses."
                                if a.site_id in [2, 5]
                                else None
                            ),
                        )
                        for p in range(1, duration + 1)
                    ]
                )

            return c

    @cached_property
    def default_schedule2(self):
        r = self.application and self.application.round
        if r and r.schedule2:
            return r.schedule2

        r = (
            Round.where(~Q(schedule2=""), scheme__current_round=F("pk"), schedule2__isnull=False)
            .order_by("-pk")
            .last()
        )
        if r and r.schedule2:
            return r.schedule2

        r = (
            Round.where(
                # scheme__current_round=F("pk"),
                ~Q(schedule2=""),
                schedule2__isnull=False,
            )
            .order_by("-pk")
            .last()
        )
        if r and r.schedule2:
            return r.schedule2

        r = (
            Round.all_objects.filter(
                ~Q(schedule2=""), scheme__current_round=F("pk"), schedule2__isnull=False
            )
            .order_by("-pk")
            .last()
        )
        if r and r.schedule2:
            return r.schedule2

        r = (
            Round.all_objects.filter(
                # scheme__current_round=F("pk"),
                ~Q(schedule2=""),
                schedule2__isnull=False,
            )
            .order_by("-pk")
            .last()
        )
        if r and r.schedule2:
            return r.schedule2

    @cached_property
    def appendix_a(self):
        r = self.application.round
        if r.appendix_a:
            return r.appendix_a

        r = (
            Round.where(~Q(appendix_a=""), scheme__current_round=F("pk"), appendix_a__isnull=False)
            .order_by("-pk")
            .last()
        )
        if r and r.appendix_a:
            return r.appendix_a

        r = (
            Round.where(
                # scheme__current_round=F("pk"),
                ~Q(appendix_a=""),
                appendix_a__isnull=False,
            )
            .order_by("-pk")
            .last()
        )
        if r and r.appendix_a:
            return r.appendix_a

        r = (
            Round.all_objects.filter(
                ~Q(appendix_a=""), scheme__current_round=F("pk"), appendix_a__isnull=False
            )
            .order_by("-pk")
            .last()
        )
        if r and r.appendix_a:
            return r.appendix_a

        r = (
            Round.all_objects.filter(
                # scheme__current_round=F("pk"),
                ~Q(appendix_a=""),
                appendix_a__isnull=False,
            )
            .order_by("-pk")
            .last()
        )
        if r and r.appendix_a:
            return r.appendix_a

    @cached_property
    def appendix_b(self):
        if ec := self.documents.filter(
            ~Q(file__isnull=True), ~Q(file=""), required_document__role="EC"
        ).first():
            return ec.file
        r = self.application.round
        if r.appendix_b:
            return r.appendix_b
        r = (
            Round.where(~Q(appendix_b=""), scheme__current_round=F("pk"), appendix_b__isnull=False)
            .order_by("-pk")
            .last()
        )
        if r and r.appendix_b:
            return r.appendix_b
        r = (
            Round.where(
                # scheme__current_round=F("pk"),
                ~Q(appendix_b=""),
                appendix_b__isnull=False,
            )
            .order_by("-pk")
            .last()
        )
        if r and r.appendix_b:
            return r.appendix_b
        r = (
            Round.all_objects.filter(
                ~Q(appendix_b=""), scheme__current_round=F("pk"), appendix_b__isnull=False
            )
            .order_by("-pk")
            .last()
        )
        if r and r.appendix_b:
            return r.appendix_b
        r = (
            Round.all_objects.filter(
                # scheme__current_round=F("pk"),
                ~Q(appendix_b=""),
                appendix_b__isnull=False,
            )
            .order_by("-pk")
            .last()
        )
        if r and r.appendix_b:
            return r.appendix_b

    @cached_property
    def application_link_name(self):
        r = self.application.round
        if r.schedule2:
            return r.schedule2

        r = (
            Round.where(scheme__current_round=F("pk"), schedule2__isnull=False)
            .order_by("-pk")
            .last()
        )
        if r and r.schedule2:
            return r.schedule2

        r = (
            Round.where(
                # scheme__current_round=F("pk"),
                schedule2__isnull=False
            )
            .order_by("-pk")
            .last()
        )
        if r and r.schedule2:
            return r.schedule2

        r = (
            Round.all_objects.filter(scheme__current_round=F("pk"), schedule2__isnull=False)
            .order_by("-pk")
            .last()
        )
        if r and r.schedule2:
            return r.schedule2

        r = (
            Round.all_objects.filter(
                # scheme__current_round=F("pk"),
                schedule2__isnull=False
            )
            .order_by("-pk")
            .last()
        )
        if r and r.schedule2:
            return r.schedule2

    @cached_property
    def ci(self):
        return (ci := self.members.filter(role="CI").last()) and ci.user or self.application.ci

    @cached_property
    def pi(self):
        return (
            (pi := self.members.filter(role="PI").last())
            and pi.user
            or self.submitted_by
            or self.application.pi
        )

    @property
    def host_emails(self):
        if self.host_contact_email:
            return [self.host_contact_email]
        if self.org and self.org.email:
            return [self.org.email]
        if self.org and (commisars := (self.org.research_offices.all())) and commisars.count():
            return commisars
        return []

    def save(self, *args, **kwargs):
        if (
            not self.pk
            and self.application
            and (not self.number or self.__class__.all_objects.filter(number=self.number).exists())
        ):
            self.number = self.__class__.new_number(self.application)
        super().save(*args, **kwargs)

    def natural_key(self):
        return (self.number,)

    @property
    def total_allocation(self):
        return self.allocations.aggregate(Sum("allocation", default=0)).get(
            "allocation__sum", Decimal("0.00")
        )

    @property
    def reporting_schedule_by_years(self):

        start_year = self.start_date and self.start_date.year or timezone.now().year
        return [
            (y, list(entries))
            for y, entries in groupby(
                self.reporting_schedule.order_by("period", "due_date").all(),
                lambda r: start_year + r.period - 1,
            )
        ]

    @property
    def allocations_by_years(self):

        start_year = self.start_date and self.start_date.year or timezone.now().year
        return [
            (y, list(entries))
            for y, entries in groupby(
                self.allocations.order_by("period", "pk").all(),
                lambda r: start_year + r.period - 1,
            )
        ]

    @property
    def thread_index(self):
        return base64.b64encode(
            f"{self.site_id}:{self._meta.model_name}:{self.pk}".encode()
        ).decode()

    @property
    def thread_topic(self):
        return f"{self._meta.model_name}:{self.number}"

    @cached_property
    def key_person(self):
        return self.members.filter(role_id="PI").last()

    @cached_property
    def other_key_personnel(self):
        return list(self.members.filter(~Q(role_id="PI"), role__is_key_person=True).all())

    @classmethod
    def new_number(cls, application, org=None, year=None):
        round = application.round
        scheme = round.scheme
        fund = scheme.fund
        if round.site_id in [2, 5]:
            prefix = scheme.code
        else:
            prefix = fund and (fund.code3 or fund.code) or scheme.code
        if not org:
            if (n := Nomination.where(application=application).last()) and n.org:
                org = n.org
            else:
                org = application.org
        yy = year and f"{year:02d}" or application.created_at.strftime("%y")
        c = (
            cls.all_objects.filter(number__startswith=f"{prefix}-{org.code}{yy}")
            .order_by("-number")
            .first()
        )
        suffix = int(c.number[-2:]) + 1 if c else 1
        while True:
            number = f"{prefix}-{org.code}{yy}{suffix:02d}"
            if not cls.all_objects.filter(number=number).exists():
                return number
            suffix += 1

    def get_required_documents(self):
        """Returns the required documents with prefetched linked documents to the contract."""
        if not self.application:
            return RequiredContractDocument.objects.none()
        return self.application.round.required_contract_documents.prefetch_related(
            Prefetch("documents", queryset=ContractDocument.where(contract=self))
        ).order_by("ordering")

    @cached_property
    def agency(self):
        return (
            Organisation.where(code="ROY").first()
            or Organisation.where(code__in=["RSTA", "NZRS"]).order_by("-pk").first()
        )

    @property
    def host(self):
        return self.org

    def get_document(self, request=None, user=None, format="html", part=None, **kwargs):
        """Returns generated part of the contract text from a template."""

        year = self.year or self.start_date.year
        current_ts = timezone.now()
        contract = self
        if part not in ["headers_footers", "footers", "page", "toc"]:
            # clauses = list(self.clauses.all().order_by("type", "ordering"))
            clauses = list(
                self.application.round.contract_clauses.all().order_by("type", "ordering")
            )
            additional_clauses = [c for c in clauses if c.type == "A"]
            ammended_clauses = [c for c in clauses if c.type == "V"]
            agency = self.agency
            agency_short = "Society"
            stand_alone = True
        else:
            page_count = (
                kwargs.pop("page_count", None) or request and request.GET.get("page_count", 5)
            )
            page_no = int(kwargs.pop("page_no", None) or request and request.GET.get("page_no", 1))

        if part in [
            "agreement",
            "background",
            "cover",
            "cover_page",
            "preamble",
            "schedule",
            "schedule1",
        ]:
            template_name = "contracts/part.html"
        elif part == "toc":
            template_name = "contracts/parts/toc.html"
        elif part == "page":
            template_name = "contracts/page.html"
        elif part == "footers":
            template_name = "contracts/footers.html"
        elif part == "headers_footers":
            template_name = "contracts/headers_footers.html"
        elif part == "letter":
            template_name = "variations/letter.html"
        else:
            template_name = "contracts/document.html"

        if part == "toc":
            if "parts" not in kwargs:
                parts = {
                    part: self.get_part_pdf(request=request, part=part)
                    for part in ["cover", "preamble", "schedule1"]
                }
            if "schedule2_toc" not in kwargs:
                schedule2 = self.get_part_pdf(request=request, part="schedule2")
                if not isinstance(schedule2, PdfReader):
                    schedule2 = PdfReader(schedule2, strict=False)
                schedule2_toc = pdf_toc(schedule2)

        template = get_template(template_name)
        user = request and request.user
        fund = self.fund or self.application.round.scheme.fund
        SITE_ID = int(settings.SITE_ID)

        context = locals()
        if kwargs:
            context.update(kwargs)
        content = template.render(context)

        if not format or format in ["html", "htm"]:
            return content

        if format == "pdf":
            html = HTML(string=content)
            return PdfReader(io.BytesIO(html.write_pdf(presentational_hints=True)), strict=False)

        hf = tempfile.NamedTemporaryFile(suffix=".html", delete=False)
        hf.write(content.encode())
        hf.close()
        hf_path = Path(hf.name)

        cp = subprocess.run(
            [
                "lowriter",
                "--headless",
                "--convert-to",
                format,
                "--outdir",
                tempfile.tempdir,
                # Path.home() / "PMSPP" / f"schedule_{self.number}.fodt",
                # Path.home() / "PMSPP" / f"schedule_{self.number}.html",
                hf.name,
            ],
            capture_output=True,
            env=dict(os.environ, PAPERSIZE="a4"),
        )
        if cp.returncode or (
            (stderr := (cp.stderr and cp.stderr.decode())) and "error" in stderr.lower()
        ):
            raise Exception(f"Failed to generate schedule: {stderr or cp.returncode}")
        return hf_path.with_suffix(f".{format}")

    def get_cover_page(self, request=None, user=None, format="html"):

        year = self.year or self.start_date.year
        template = get_template("contract_cover_page.html")
        # template = get_template("contract_schedule.fodt")
        current_ts = timezone.now()
        contract = self
        user = request and request.user
        return template.render(locals())

        # pi = self.members.filter(role__code="PI").last() or self.application.submitted_by
        # fields = {
        #     "START_DATE": self.start_date.strftime("%d %B, %Y"),
        #     "END_DATE": self.end_date and self.end_date.strftime("%d %B, %Y"),
        #     "PROJECT_TITLE": self.project_title,
        #     # "TITLE": pi.title and pi.title.name or "",
        #     "TITLE": "Dr.",
        #     "FIRSTNAME": pi.first_name,
        #     # "MIDDLE_INITIALS": pi.middle_name_initials,
        #     "LASTNAME": pi.last_name,
        #     "LEGALNAME": self.org.name,
        #     "FULL_NAME_WITH_TITLE": pi.full_name_with_title,
        # }
        # schedule_output_path = self.get_part_odt(request=request, part="schedule")
        # with open(Path.home() / "Documents" / "RDF contract template.odt", "rb") as infile, open(
        #     Path.home() / "Documents" / "output.odt", "wb"
        # ) as outfile:
        #     o = OOoPy(infile=infile, outfile=outfile)
        #     t = Transformer(
        #         o.mimetype,
        #         Transforms.get_meta(o.mimetype),
        #         Transforms.Editinfo(),
        #         Transforms.Field_Replace(replace=fields),
        #         Transforms.Fix_OOo_Tag(),
        #         Transforms.Concatenate(schedule_output_path),
        #         Transforms.renumber_all(o.mimetype),
        #         Transforms.set_meta(o.mimetype),
        #         Transforms.Fix_OOo_Tag(),
        #         Transforms.Manifest_Append(),
        #     )
        #     t.transform(o)
        #     o.close()

    def get_part_odt(
        self, request=None, user=None, add_headers=None, skip_excluded=False, part=None
    ):
        output_path = Path.home() / "PMSPP" / "contracts" / f"schedule_{self.number}.html"
        with open(output_path, "w") as ofile:
            d = self.get_schedule_part(request=request)
            ofile.write(d)
        cp = subprocess.run(
            [
                "loffice",
                "--headless",
                "--convert-to",
                "odt",
                "--outdir",
                Path.home() / "PMSPP/",
                # Path.home() / "PMSPP" / f"schedule_{self.number}.fodt",
                # Path.home() / "PMSPP" / f"schedule_{self.number}.html",
                output_path,
            ],
            capture_output=True,
            env=dict(os.environ, PAPERSIZE="a4"),
        )
        if cp.returncode or (
            (stderr := (cp.stderr and cp.stderr.decode())) and "error" in stderr.lower()
        ):
            raise Exception(f"Failed to generate schedule: {stderr or cp.returncode}")
        return output_path.with_suffix(".odt")

    def get_part_pdf(
        self, request=None, user=None, part=None, add_headers=None, skip_excluded=False, **kwargs
    ):

        # with open(f"/home/rcir178/PMSPP/schedule_{self.number}.fodt", "w") as ofile:
        # output_dir = Path.home() / "PMSPP" / "contracts"
        output_dir = Path(tempfile.gettempdir())
        if contract_part := getattr(self, part, False):
            file_path = contract_part.path
        elif part == "schedule2":
            file_path = self.schedule2.path if self.schedule2 else self.default_schedule2.path
        elif part == "appendix_a":
            file_path = self.appendix_a and self.appendix_a.path
        # elif part == "appendix_b":
        #     file_path = self.appendix_b and self.appendix_b.path
        else:
            return self.get_document(request=request, user=user, format="pdf", part=part, **kwargs)
            # content = self.get_document(
            #     request=request, user=user, format="html", part=part, **kwargs
            # )
            # html = HTML(string=content)
            # pdf_object = html.write_pdf(presentational_hints=True)
            # # converting pdf bytes to stream which is required for pdf merger.
            # pdf_stream = io.BytesIO(pdf_object)
            # return PdfReader(pdf_stream, strict=False)

            # # file_path = output_dir / f"{self.number}_{part}.html"
            # # with open(file_path, "w") as ofile:
            # #     content = self.get_document(request=request, user=user, format="html", part=part)
            # #     ofile.write(content)

        base, ext = os.path.splitext(file_path)
        if ext.lower() != ".pdf":
            cp = subprocess.run(
                [
                    "lowriter",
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    output_dir,
                    file_path,
                ],
                capture_output=True,
                env=dict(os.environ, PAPERSIZE="a4"),
            )
            if cp.returncode or (
                (stderr := (cp.stderr and cp.stderr.decode())) and "error" in stderr.lower()
            ):
                if cp.returncode:
                    raise Exception(
                        f"Failed to convert {part} into PDF. "
                        "Please save your application form into PDF format and try to upload it again."
                    )

                raise Exception(
                    (
                        f"Failed to {part} form into PDF: %s. "
                        "Please save your application form into PDF format and try to upload it again."
                    )
                    % stderr,
                )
            file_path = output_dir / f"{os.path.basename(base)}.pdf"
        return file_path

    def variation_to_pdf(self, request=None, user=None, add_headers=None, skip_excluded=False):

        output_dir = Path(tempfile.gettempdir())

        output_filename = output_dir / f"{self.number}.pdf"
        merger.write(output_filename)
        return output_filename

    def to_pdf(self, request=None, user=None, add_headers=None, skip_excluded=False):
        # with open(Path.home() / f"schedule_{self.number}.fodt", "w") as ofile:
        # output_dir = Path.home() / "PMSPP" / "contracts"
        output_dir = Path(tempfile.gettempdir())

        parts = {
            part: self.get_part_pdf(request=request, part=part)
            for part in ["cover", "preamble", "schedule1"]
        }

        schedule1 = parts["schedule1"]
        if not isinstance(schedule1, PdfReader):
            schedule1 = PdfReader(schedule1)
            parts["schedule1"] = schedule1
        schedule1_page_count = len(schedule1.pages)
        schedule2 = self.get_part_pdf(request=request, part="schedule2")
        if not isinstance(schedule2, PdfReader):
            schedule2 = PdfReader(schedule2, strict=False)
        appendix_a = self.get_part_pdf(request=request, part="appendix_a")
        if not isinstance(appendix_a, PdfReader):
            appendix_a = PdfReader(appendix_a, strict=False)
        # appendix_b = self.get_part_pdf(request=request, part="appendix_b")
        # if not isinstance(appendix_b, PdfReader):
        #     appendix_b = PdfReader(appendix_b, strict=False)
        schedule2_toc = pdf_toc(schedule2)
        page_no = 2 + schedule1_page_count
        headers = {}
        for appendix_no, d in enumerate(self.documents.order_by("required_document__ordering"), 1):
            headers[page_no] = (
                f"APPENDIX {appendix_no} – {d.required_document.title or d.required_document.get_role_display()}"
            )
            if not d.page_count:
                d.update_page_count()
            page_no += d.page_count

        toc = self.get_part_pdf(
            request=request,
            part="toc",
            parts=parts,
            schedule2_toc=schedule2_toc,
            schedule2=schedule2,
            appendix_a=appendix_a,
            # appendix_b=appendix_b,
            page_no=1,
        )
        parts["toc"] = toc

        # merger = PdfMerger(strict=False)
        merger = PdfWriter()

        def part_list():
            """Change order and add the appendices"""
            for p in ["cover", "toc", "preamble", "schedule1"]:
                yield parts[p]
            for d in self.documents.order_by("required_document__ordering"):
                yield d.pdf_file.path
            yield schedule2
            yield appendix_a
            # yield appendix_b

        for part in part_list():
            # merger.append(a, outline_item=title, import_outline=True)
            if isinstance(part, HTML):
                pdf_object = part.write_pdf(presentational_hints=True)
                # converting pdf bytes to stream which is required for pdf merger.
                pdf_stream = io.BytesIO(pdf_object)
                merger.append(
                    pdf_stream,
                    import_outline=True,
                )
            elif isinstance(part, PdfReader):
                merger.append(part)
            else:
                reader = PdfReader(part, strict=False)
                merger.append(reader)

        # template = get_template("contracts/headers_footers.html")
        # html = HTML(
        #     string=template.render(
        #         {
        #             "page_count": len(merger.pages),
        #             "contract": self,
        #         }
        #     )
        # )
        # header_file = PdfReader(
        #     io.BytesIO(html.write_pdf(presentational_hints=True)), strict=False
        # )
        pages_to_skip = len(toc.pages) + 1
        page_count = len(merger.pages) - pages_to_skip

        template = get_template("contracts/page.html")
        for pn, dp in enumerate(merger.pages):
            if pn < pages_to_skip:
                continue
            box = dp.mediabox
            if box.height and box.width:
                width = int(round(box.width * 0.35277777777777775, 0))  # 2.54/72
                height = int(round(box.height * 0.35277777777777775, 0))  # 2.54/72
            else:  # A4 (portrait)
                width = 210
                height = 297
            page_no = pn - pages_to_skip + 1
            html = HTML(
                string=template.render(
                    {
                        "page_count": page_count,
                        "page_no": page_no,
                        "contract": self,
                        "header": headers.get(page_no),
                        "width": width,
                        "height": height,
                    }
                )
            )
            reader = PdfReader(io.BytesIO(html.write_pdf(presentational_hints=True)), strict=False)
            dp.merge_page(reader.pages[0])

        output_filename = output_dir / f"{self.number}.pdf"
        merger.write(output_filename)
        return output_filename

    def get_schedule_part(self, request=None, user=None, add_headers=None, skip_excluded=False):
        # d = od.Document()
        # b = d.body
        # b.append(od.Header(1, "Schedule"))
        # b.append(od.Paragraph(f"{_('Programme Contract Number')}:\t{self.number}"))
        # b.append(od.Paragraph(f"{_('Programme Title')}:\t{self.project_title}"))
        # l = od.List()
        # l.append(f"Application Number: {self.application.number}")
        # t = od.Table("Schedule", template-name="Simple Grid Columns")
        # r = od.Row()
        # r.set_values(["", "Funding amount (GST inclusive)", "Date of payments"])
        # t.append_row(r)
        # for a in self.allocations.all():
        #     r = od.Row()
        #     r.set_values([f"Year {a.period}", f"${a.allocation}", "[Monthly, on the 2nd Business Day after the 20th of month]"])
        #     t.append_row(r)
        # li = od.ListItem("Total approved funding and payment process:")
        # li.append(od.Paragraph(t))
        # l.append_item(li)
        # b.append(l)
        # b.append(t)
        # return d

        template = get_template("contract_schedule.html")
        # template = get_template("contract_schedule.fodt")
        current_ts = timezone.now()
        contract = self
        user = request.user
        return template.render(locals())

    def to_odt(self, request=None, user=None, add_headers=None, skip_excluded=False):
        pi = self.members.filter(role__code="PI").last() or self.application.submitted_by
        fields = {
            "START_DATE": self.start_date.strftime("%d %B, %Y"),
            "END_DATE": self.end_date and self.end_date.strftime("%d %B, %Y"),
            "PROJECT_TITLE": self.project_title,
            # "TITLE": pi.title and pi.title.name or "",
            "TITLE": "Dr.",
            "FIRSTNAME": pi.first_name,
            # "MIDDLE_INITIALS": pi.middle_name_initials,
            "LASTNAME": pi.last_name,
            "LEGALNAME": self.org.name,
            "FULL_NAME_WITH_TITLE": pi.full_name_with_title,
        }
        schedule_output_path = self.get_part_odt(request=request, part="schedule")
        with open(Path.home() / "Documents" / "RDF contract template.odt", "rb") as infile, open(
            Path.home() / "Documents" / "output.odt", "wb"
        ) as outfile:
            o = OOoPy(infile=infile, outfile=outfile)
            t = Transformer(
                o.mimetype,
                Transforms.get_meta(o.mimetype),
                Transforms.Editinfo(),
                Transforms.Field_Replace(replace=fields),
                Transforms.Fix_OOo_Tag(),
                Transforms.Concatenate(schedule_output_path),
                Transforms.renumber_all(o.mimetype),
                Transforms.set_meta(o.mimetype),
                Transforms.Fix_OOo_Tag(),
                Transforms.Manifest_Append(),
            )
            t.transform(o)
            o.close()

    @cached_property
    def host_address(self):
        return (
            ", ".join(
                map(
                    lambda s: s.strip(" ,\r\t\n"),
                    (self.address or self.org.address).__str__().splitlines(),
                )
            )
            if (self.address or self.org.address)
            else "N/A"
        )

    @cached_property
    def agency_address(self):
        return ", ".join(
            map(lambda s: s.strip(" ,\r\t\n"), self.agency.address.__str__().splitlines())
        )

    @fsm_log
    @transition(field=state, source=["*"], target="draft", custom=dict(admin=False))
    def save_draft(self, request=None, by=None, description=None, *args, **kwargs):
        pass

    @fsm_log
    @transition(
        field=state,
        source=["new", "draft", "submitted"],
        target="submitted",
        custom=dict(verbose="Submit", button_name="submit"),
    )
    def submit(self, *args, **kwargs):
        request = kwargs.get("request")
        by = kwargs.get("by") or request and request.user

        url = self.get_full_detail_url(request=request)
        link_name = domain_to_macrons(url)

        send_mail(
            f"Contract {self} Submitted",
            html_message=f'User {by} submitted the contract {self}: <a href="{link_name}">{link_name}</a>',
            message=f"User {by} submitted the contract {self}: {link_name}",
            from_email="contracts",
            recipients=(
                [self.fund.email]
                if self.fund and self.fund.email
                else User.where(staff_of_sites=self.site)
            ),
            fail_silently=False,
            request=request,
            # reply_to=settings.DEFAULT_FROM_EMAIL,
            thread_index=self.thread_index,
            thread_topic=self.thread_topic,
        )

    @fsm_log
    @transition(
        field=state,
        source=["new", "draft", "submitted", "released"],
        # target="released",
        target="submitted",
        custom=dict(verbose="Release", button_name="release"),
    )
    def release(self, *args, **kwargs):
        request = kwargs.get("request")
        by = kwargs.get("by") or request and request.user

        url = self.get_full_detail_url(request=request)
        link_name = domain_to_macrons(url)

        send_mail(
            f"Contract {self} Released",
            html_message=f'User {by} release the contract {self}: <a href="{link_name}">{link_name}</a>',
            message=f"User {by} release the contract {self}: {link_name}",
            recipients=(
                [self.fund.email]
                if self.fund and self.fund.email
                else User.where(staff_of_sites=self.site)
            ),
            fail_silently=False,
            request=request,
            # reply_to=settings.DEFAULT_FROM_EMAIL,
            thread_index=self.thread_index,
            thread_topic=self.thread_topic,
        )

    @fsm_log
    @transition(
        field=state,
        source=["submitted", "released"],
        target="current",
        custom=dict(verbose="Make Current", button_name="Make Current"),
    )
    def make_current(self, *args, **kwargs):
        pass

    def clone(self, is_variation=None, change_request=None, *args, **kwargs):
        """Clone the contract to create a variation of a transfer."""

        if not change_request:
            change_request = (
                self.change_requests.filter(derivative__isnull=True).order_by("-pk").first()
            )
        assert change_request, "Change request is required to clone a contract"

        if is_variation is None:
            is_variation = not change_request.types.filter(code="TR").exists()

        if is_variation:
            number = change_request.number
        else:
            assert change_request.new_host != self.org, (
                "Transfrer must have and organisation and "
                "it should be a different organisation from the original contract"
            )
            number = self.__class__.new_number(self.application, org=change_request.new_host)

        with transaction.atomic():

            nc = super().clone(
                exclude_related_models=[ContractComment, Contract, Report, ChangeRequest],
                is_variation=is_variation,
                number=number,
                state="draft",
                source=self,
                **(
                    {
                        "org": change_request.new_host,
                    }
                    if not is_variation
                    else {}
                ),
            )

            return nc

    class Meta:
        db_table = "contract"


simple_history.register(
    Contract,
    inherit=True,
    table_name="contract_history",
    bases=[ContractMixin, PersonMixin, PdfFileMixin, Model],
)


class ContractDocumentMixin:
    STATES = Choices(
        ("accepted", _("Accepted")),
        ("approved", _("Approved")),
        ("archived", _("Archived")),
        ("cancelled", _("Cancelled")),
        ("draft", _("WIP")),
        ("new", _("New")),
        ("released", _("Released")),
        ("submitted", _("Submitted")),
    )


class RequiredContractDocument(TimeStampMixin, HelperMixin, OrderableModel):
    round = ForeignKey(Round, on_delete=CASCADE, related_name="required_contract_documents")
    document_type = ForeignKey(
        DocumentType,
        on_delete=CASCADE,
        related_name="required_contract_documents",
        null=True,
        blank=True,
    )
    role = CharField(max_length=10, choices=DOCUMENT_ROLES, null=True, blank=True)
    # name = CharField(_("Name"), max_length=200, blank=True, default="")
    format = CharField(
        choices=Choices(("I", _("Image")), ("S", _("Spreadsheet")), ("T", _("Text"))),
        default="T",
        max_length=1,
    )
    # TODO: should be removed at some stage or renamed to 'name'
    title = CharField(
        _("Title"), max_length=200, null=True, blank=True, help_text=_("Contract document title")
    )
    is_optional = BooleanField(default=False)
    # min_pages = PositiveSmallIntegerField(null=True, blank=True)
    # max_pages = PositiveSmallIntegerField(null=True, blank=True)
    application_required_document = ForeignKey(
        RequiredDocument,
        on_delete=SET_NULL,
        null=True,
        blank=True,
        related_name="contract_required_documents",
        help_text="Application required document corresponding to the contract to",
        db_comment="Application required document corresponding to the contract to",
    )

    def save(self, *args, **kwargs):
        if not self.role:
            self.role = self.document_type.role
        if not self.format:
            self.format = self.document_type.format
        super().save(*args, **kwargs)

    def __str__(self):
        if self.document_type:
            dt = str(self.document_type)
        elif self.role:
            dt = self.get_role_display()
        else:
            dt = None
        title = self.title or dt
        if not dt or title == dt:
            return title
        return f"{dt}: {title}"

    class Meta(OrderableModel.Meta):
        db_table = "required_contract_document"


class ContractDocument(ContractDocumentMixin, PdfFileMixin, Model):
    contract = ForeignKey(Contract, on_delete=CASCADE, related_name="documents")
    state = StateField(default="new", verbose_name=_("state"))
    # TODO: remove at some stage
    document_type = ForeignKey(
        DocumentType, related_name="contract_documents", on_delete=SET_NULL, null=True, blank=True
    )
    required_document = ForeignKey(
        RequiredContractDocument, on_delete=DO_NOTHING, related_name="documents"
    )
    page_count = PositiveSmallIntegerField(null=True, blank=True)
    file = PrivateFileField(
        blank=True,
        null=True,
        upload_to="contracts",
        upload_subfolder=lambda instance: [
            # hash_int(instance.application_id),
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
                    "fdot",
                    "dot",
                    "dotm",
                    "dotx",
                    "odm",
                    "odt",
                    "fodt",
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

    @fsm_log
    @transition(field=state, source=["submitted", "new", "released", "draft"], target="approved")
    def approve(self, request=None, by=None, description=None, *args, **kwargs):
        pass

    @fsm_log
    @transition(field=state, source=["released", "approved", "draft", "new"], target="accepted")
    def accept(self, request=None, by=None, description=None, *args, **kwargs):
        pass

    @fsm_log
    @transition(field=state, source=["*"], target="draft", custom=dict(admin=False))
    def save_draft(self, request=None, by=None, description=None, *args, **kwargs):
        pass

    @fsm_log
    @transition(
        field=state,
        source=["new", "draft", "submitted"],
        target="released",
        custom=dict(verbose="Release", button_name="release"),
    )
    def release(self, *args, **kwargs):
        request = kwargs.get("request")
        by = kwargs.get("by") or request and request.user

        c = self.contract
        url = c.get_full_detail_url(request=request)
        link_name = domain_to_macrons(f"{url}#documents")
        site = getattr(self, "site", None) or c.site or settings.SITE_ID

        send_mail(
            f"Contract {c} document/appendix {self} released",
            html_message=f'User {by} release the contract {c} document {self}: <a href="{link_name}">{link_name}</a>',
            message=f"User {by} release the contract {self}: {link_name}",
            recipients=(
                [c.fund.email] if c.fund and c.fund.email else User.where(staff_of_sites=site)
            ),
            fail_silently=False,
            request=request,
            # reply_to=settings.DEFAULT_FROM_EMAIL,
            thread_index=c.thread_index,
            thread_topic=c.thread_topic,
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
        db_table = "contract_document"


simple_history.register(
    ContractDocument,
    inherit=True,
    table_name="contract_document_history",
    bases=[ContractDocumentMixin, PdfFileMixin, Model],
)


class ContractMemberManager(Manager):
    def get_by_natural_key(self, number, email, role, *args, **kwargs):
        return self.get(email=email, role_id=role, contract__number=number)


class ContractMember(PersonMixin, Model):
    """Contract team member."""

    objects = ContractMemberManager()
    # all_objects = Manager()

    contract = ForeignKey(Contract, on_delete=CASCADE, related_name="members")
    email = EmailField(max_length=120, null=True, blank=True)
    first_name = CharField(max_length=30, null=True, blank=True)
    middle_names = CharField(
        _("middle names"),
        blank=True,
        null=True,
        max_length=280,
        # help_text=_("Comma separated list of middle names"),
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
    address = ForeignKey(Address, null=True, blank=True, on_delete=PROTECT)
    # state = StateField(null=True, blank=True, default="new")
    # state_changed_at = MonitorField(monitor="state", null=True, blank=True, default=None, blank=True)
    # authorized_at = MonitorField(
    #     monitor="state", when=["authorized"], null=True, default=None, blank=True
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

    @property
    def total_fte(self):
        return self.efforts.aggregate(aggregates.Avg("fte", default=0)).get("fte__avg")

    def fte(self, period):
        if me := self.efforts.filter(period=period).first():
            return me.fte
        return None

    def __getattribute__(self, name):
        if name.startswith("fte_"):
            i = int(name.split("_")[1])
            return self.fte(i)
        return super().__getattribute__(name)

    def clean(self):
        super().clean()
        if not (c := getattr(self, "contract", None)):
            raise ValidationError(_("Missing contract"))
        member_id = getattr(self, "id", None)
        if self.email and self.email.strip():
            q = c.members.filter(email=self.email)
            if member_id:
                q = q.filter(~Q(id=member_id))
            if q.exists():
                raise ValidationError(
                    _("Team member with the email address %(email)s was already added"),
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
    purpose = CharField(_("Purpose of Funding"), null=True, blank=True, max_length=1000)
    details = CharField(
        _("Payment details"),
        null=True,
        blank=True,
        max_length=1000,
        help_text=_(
            "E.g., on the 2nd Business Day after the 20th day of each  month, "
            "or receipt of the 2024 interim / final report."
        ),
        default="In equal instalments on the 2nd Business Day after the 20th day of each month.",
    )
    allocation = DecimalField(
        _("allocation"),
        max_digits=15,
        decimal_places=2,
        help_text=_("Amount of funding (GST excl.)"),
    )

    history = HistoricalRecords(table_name="allocation_history")

    class Meta:
        db_table = "allocation"
        # unique_together = (("contract", "period"),)


class ContractClause(TimeStampMixin, HelperMixin, OrderableModel):
    contract = ForeignKey(Contract, on_delete=CASCADE, related_name="clauses")
    type = FixedCharField(
        _("Type"), max_length=1, choices=Choices(("A", _("Addition")), ("V", _("Variation")))
    )
    clause = CharField(_("Clause Number"), max_length=100)
    term = TextField(_("Term"), max_length=2000)

    def __str__(self):
        return f"{self.get_type_display()}: {self.clause}"

    class Meta(OrderableModel.Meta):
        db_table = "contract_clause"


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
        monitor="state", when=["acknowledged"], null=True, default=None, blank=True
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

    def __str__(self):
        return f"{self.contract}:{self.type}-{self.period}"

    class Meta:
        db_table = "reporting_schedule_entry"
        unique_together = (("contract", "period", "type", "due_date"),)


simple_history.register(
    ReportingScheduleEntry,
    inherit=True,
    table_name="reporting_schedule_entry_history",
    bases=[ReportingScheduleEntryMixin, Model],
)


class ReportKeyword(Model):
    report = ForeignKey("Report", on_delete=CASCADE)
    keyword = ForeignKey(Keyword, on_delete=CASCADE)

    class Meta:
        db_table = "report_keyword"


class ReportFor(Model):
    report = ForeignKey("Report", on_delete=CASCADE, related_name="report_fors")
    code = ForeignKey(FieldOfResearch, db_column="code", on_delete=CASCADE, verbose_name="FoR")
    share = PositiveSmallIntegerField(null=True, blank=True, default=None)

    def __str__(self):
        return self.code_id

    class Meta:
        # auto_created = True
        db_table = "report_for"
        unique_together = (("report", "code"),)
        verbose_name = _("report FoR")
        verbose_name_plural = _("report FoRs")


class ReportSeo(Model):
    report = ForeignKey("Report", on_delete=CASCADE, related_name="report_seos")
    code = ForeignKey(
        SocioEconomicObjective, on_delete=CASCADE, db_column="code", verbose_name="SEO"
    )
    share = PositiveSmallIntegerField(null=True, blank=True, default=None)

    def __str__(self):
        return self.code_id

    class Meta:
        # auto_created = True
        db_table = "report_seo"
        unique_together = (("report", "code"),)
        verbose_name = _("report SEO")
        verbose_name_plural = _("report SEOs")


class ReportMixin:
    STATES = Choices(
        ("accepted", _("accepted")),
        ("acknowledged", _("acknowledged")),
        ("approved", _("approved")),
        ("assessed", _("assessed")),
        ("archived", _("archived")),
        ("cancelled", _("cancelled")),
        ("draft", _("draft")),
        ("new", _("new")),
        ("submitted", _("submitted")),
        ("reported", _("reported")),
        # ("withdrawn", _("withdrawn")),
    )


class Report(ReportMixin, PdfFileMixin, CommentMixin, Model):
    tags = TaggableManager(blank=True)
    schedule_entry = OneToOneField(
        ReportingScheduleEntry, on_delete=CASCADE, related_name="report"
    )
    contract = ForeignKey(Contract, on_delete=CASCADE, related_name="reports")
    # number = models.CharField(unique=True, max_length=255)
    # report_id = models.CharField(unique=True, max_length=255, blank=True, null=True)
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
    state = StateField(default="new", verbose_name=_("state"))
    file = PrivateFileField(
        verbose_name=_("Completed research report"),
        blank=True,
        null=True,
        upload_to="reports",
        upload_subfolder=lambda instance: [
            # hash_int(instance.application_id),
            hash_int(instance.contract_id),
        ],
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
    converted_file = ForeignKey(
        ConvertedFile, null=True, blank=True, on_delete=SET_NULL, verbose_name=_("converted file")
    )
    assessment = TextField(blank=True, null=True)

    reported_at = MonitorField(
        monitor="state", when=["reported", "submitted"], null=True, default=None, blank=True
    )
    assessor = ForeignKey(User, on_delete=SET_NULL, blank=True, null=True)
    assessed_at = MonitorField(
        monitor="state", when=["assessed"], null=True, default=None, blank=True
    )

    @cached_property
    def due_date(self):
        return self.schedule_entry.due_date

    @cached_property
    def ci(self):
        return (
            (ci := self.efforts.filter(role="CI", person__user__isnull=False).last())
            and ci.person.user
            or self.contract.ci
        )

    @cached_property
    def pi(self):
        return (
            (pi := self.efforts.filter(role="PI", person__user__isnull=False).last())
            and pi.person.user
            or self.contract.pi
        )

    # exported = models.BooleanField(blank=True, null=True)
    # exported_date = models.DateField(blank=True, null=True)

    # email_acknowledgement = models.CharField(max_length=255, blank=True, null=True)
    # is_confidential = models.BooleanField(default=False, blank=True, null=True)
    # is_highlighted = models.BooleanField(default=False, blank=True, null=True)
    # notes = models.TextField(blank=True, null=True)
    # notes2 = models.TextField(blank=True, null=True)
    # duration = models.IntegerField(blank=True, null=True)

    fors = ManyToManyField(
        FieldOfResearch,
        blank=True,
        through=ReportFor,
        related_name="reports",
        verbose_name="FoRs",
    )
    seos = ManyToManyField(
        SocioEconomicObjective,
        blank=True,
        through=ReportSeo,
        related_name="reports",
        verbose_name="SEOs",
    )
    keywords = ManyToManyField(
        Keyword,
        verbose_name=_("Keywords"),
        through=ReportKeyword,
        blank=True,
        related_name="reports",
    )
    priorities = TaggableManager(
        blank=True,
        verbose_name=_("Priorities"),
        help_text=_("Research priorities"),
        through=ResearchPriorityItem,
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
            "iwi and hapū knowledge, culture and experience – including Kaitiakitanga - in New Zealand "
            "land and seascapes."
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

    def create(self, *args, **kwargs):
        obj = super().create(*args, **kwargs)
        if r := (obj.contract and obj.contract.application and obj.contract.application.round):
            AssessedPerformance.bulk_create(
                [
                    AssessedPerformance(
                        report=obj,
                        flag=f,
                        value="N" if not f.is_optional and not f.value_choices else None,
                    )
                    for f in r.performance_flags.all()
                ]
            )
        return obj

    def save(self, *args, **kwargs):
        if se := self.schedule_entry:
            if not self.contract:
                self.contract = se.contract
            if not self.period:
                self.period = se.period
            if not self.type:
                self.type = se.type
        elif self.period and self.type:
            if se := self.contract.reporting_schedule.filter(
                period=self.period, type=self.type
            ).last():
                self.schedule_entry = se
        super().save(*args, **kwargs)

    publications = ManyToManyField(
        "Publication", blank=True, db_table="report_publication", related_name="reports"
    )

    def __str__(self):
        return f"{self.period}:{self.type}:{self.contract}"

    @property
    def due_in_days(self):
        current_date = timezone.localdate()
        if self.due_date:
            return (self.due_date - current_date).days
        elif (c := self.contract) and c.start_date and self.period:
            return (c.start_date + timedelta(365 * self.period) - current_date).days
        return 365

    @classmethod
    def user_object_counts(
        cls, user, state=None, round=None, request=None, queryset=None, *args, **kwargs
    ):
        return (
            cls.where(
                pk__in=cls.user_objects(
                    user=user, state=state, round=round, select_related=False, request=request
                ).values("pk")
            )
            .values_list("state")
            .annotate(total=Count("pk", distinct=True))
            .order_by()
        )

    @classmethod
    def user_objects(
        cls,
        user,
        state=None,
        round=None,
        select_related=True,
        request=None,
        queryset=None,
        *args,
        **kwargs,
    ):
        q = queryset or cls.objects.all()
        # q = cls.where(round__site=Site.objects.get_current())

        if select_related:
            prefetch_related_objects(q, "contract__application__round")

        if state:
            if isinstance(state, (list, tuple)):
                q = q.filter(state__in=state)
            else:
                q = q.filter(state=state)
        else:
            q = q.filter(~Q(state="archived"))

        # if round:
        #     q = q.filter(contract__application__round=round)

        # if not round and not (
        #     (user.is_staff or user.is_superuser or user.is_site_staff) and include_inactive
        # ):
        #     q = q.filter(round=F("round__scheme__current_round"))

        if user.is_staff or user.is_superuser or user.is_site_staff:
            return q

        f = (
            Q(assessor=user)
            | Q(contract__application__submitted_by=user)
            # | Q(members__user=user, members__state="authorized")
            # | Q(referees__user=user)
            # | Q(nomination__nominator=user)
            # | Q(nomination__user=user)
            # | Q(
            #     Q(contract__org__research_offices__user=user),
            #     Q(
            #         Q(nomination__org=F("org"))
            #         | Q(nomination__nominator__research_offices__org=F("org"))
            #     ),
            # )
        )
        q = q.filter(f)
        q = q.distinct()

        return q

    @property
    def thread_index(self):
        site_id = self.contract and self.contract.site_id or settings.SITE_ID
        return base64.b64encode(f"{site_id}:{self.pk}".encode()).decode()

    @property
    def thread_topic(self):
        return f"REPORT:{self.period}:{self.type}:{self.contract.number}"

    @fsm_log
    @transition(
        field=state,
        source=["new", "draft", "submitted"],
        target="submitted",
        custom=dict(verbose="Submit", button_name="submit"),
    )
    def submit(self, *args, **kwargs):
        request = kwargs.get("request")
        by = kwargs.get("by") or request and request.user

        if self.assessor:
            url = self.get_full_detail_url(request=request)
            link_name = domain_to_macrons(url)

            send_mail(
                f"Report {self} Submitted",
                message=f"User {by} submitted the report {self}.",
                from_email="reports",
                recipients=[self.assessor],
                fail_silently=False,
                request=request,
                # reply_to=settings.DEFAULT_FROM_EMAIL,
                thread_index=self.thread_index,
                thread_topic=self.thread_topic,
            )

    @fsm_log
    @transition(
        field=state,
        source=["submitted", "assessed"],
        target="assessed",
        custom=dict(verbose="Assess", button_name="assess"),
    )
    def assess(self, *args, **kwargs):
        request = kwargs.get("request")
        by = kwargs.get("by") or request and request.user

        url = self.get_full_detail_url(request=request)
        link_name = domain_to_macrons(url)

        send_mail(
            f"Report {self} Assessed",
            message=f"User {by} submitted the report {self}.",
            from_email="reports",
            recipients=[self.pi],
            fail_silently=False,
            request=request,
            # reply_to=settings.DEFAULT_FROM_EMAIL,
            thread_index=self.thread_index,
            thread_topic=self.thread_topic,
        )

    class Meta:
        db_table = "report"
        unique_together = (("contract", "period", "type"),)


simple_history.register(
    Report,
    inherit=True,
    table_name="report_history",
    bases=[ReportMixin, Model],
)


class AssessedPerformance(Model):
    report = ForeignKey(
        Report,
        on_delete=CASCADE,
        related_name="performance",
    )
    flag = ForeignKey(PerformanceFlag, on_delete=CASCADE)
    # name = CharField(max_length=400)
    # value_choices = CharField(
    #     max_length=400,
    #     help_text="given in the format: 'VALUE1:DESCRIPTION1;VALUE2:DESCRIPTION2;...'",
    # )
    # is_optional = BooleanField(default=True)
    value = CharField(max_length=100, null=True, blank=True)
    comment = TextField(_("Comment"), max_length=1000, null=True, blank=True)

    history = HistoricalRecords(table_name="assessed_performance_history")

    class Meta:
        db_table = "assessed_performance"
        ordering = ["flag__ordering"]


class ReportedEffortMixin:
    STATES = Choices(
        ("accepted", _("accepted")),
        ("acknowledged", _("acknowledged")),
        ("approved", _("approved")),
        ("archived", _("archived")),
        ("cancelled", _("cancelled")),
        ("draft", _("draft")),
        ("new", _("new")),
        ("submitted", _("submitted")),
        ("reported", _("reported")),
        # ("withdrawn", _("withdrawn")),
    )


class ReportedEffort(ReportedEffortMixin, Model):
    report = ForeignKey(
        Report,
        on_delete=CASCADE,
        related_name="efforts",
    )
    member_effort = OneToOneField(
        ContractMemberEffort,
        on_delete=SET_NULL,
        blank=True,
        null=True,
        related_name="reported_efforts",
    )
    person = ForeignKey(
        Person,
        on_delete=SET_NULL,
        blank=True,
        null=True,
        related_name="reported_efforts",
    )
    full_name = CharField(
        _("person name"),
        blank=True,
        null=True,
        max_length=400,
    )
    role = ForeignKey(
        RoleType,
        on_delete=SET_NULL,
        related_name="+",
        null=True,
        blank=True,
        db_column="role",
    )
    fte = DecimalField(
        _("FTE"),
        help_text=_("Full-Time Equivalent from the contract"),
        max_digits=3,
        decimal_places=2,
        null=True,
        blank=True,
    )
    total_fte = DecimalField(
        _("Total FTE"),
        help_text=_("Total Full-Time Equivalent"),
        max_digits=3,
        decimal_places=2,
        null=True,
        blank=True,
    )
    state = StateField(default="new", verbose_name=_("state"))

    # @property
    # def fte_total(self):
    #     if self.person:
    #         return (
    #             self._meta.model.where(
    #                 report__contract=self.report.contract,
    #                 person=self.person,
    #                 # report__period__lt=self.report.period,
    #             )
    #             .aggregate(Sum("fte", default=0))
    #             .get("fte__sum", Decimal("0.00"))
    #         )  # + (self.fte or 0.0)
    #     elif self.full_name:
    #         return (
    #             self._meta.model.where(
    #                 report__contract=self.report.contract,
    #                 full_name=self.full_name,
    #                 person=self.person,
    #                 # report__period__lt=self.report.period,
    #             )
    #             .aggregate(Sum("fte", default=0))
    #             .get("fte__sum", Decimal("0.00"))
    #         )  # + (self.fte or 0.0)
    #     return 0.0

    @cached_property
    def user(self):
        if self.person and self.person.user:
            return self.person.user
        if self.member_effort and self.member_effort.member and self.member_effort.member.user:
            return self.member_effort.member.user

    @cached_property
    def email(self):
        if user := self.user:
            return user.email
        if self.member_effort and self.member_effort.member:
            return self.member_effort.member.email

    def save(self, *args, **kwargs):
        if me := self.member_effort:
            if not self.person:
                self.person = me.member.user.person
            if not self.full_name:
                self.full_name = me.member.full_name
            if not self.role:
                self.role = me.member.role
        super().save(*args, **kwargs)

    def __str__(self):
        if self.role:
            return f"{self.full_name} ({self.role})"
        return self.full_name

    class Meta:
        db_table = "reported_effort"


simple_history.register(
    ReportedEffort,
    inherit=True,
    table_name="reported_effort_history",
    bases=[ReportedEffortMixin, Model],
)


FUNDING_TYPES = Choices(
    ("A", _("Award")),
    ("C", _("Contract")),
    ("G", _("Grant")),
    ("S", _("Salary award")),
)


class ReportedFundingMixin:
    STATES = Choices(
        ("accepted", _("accepted")),
        ("acknowledged", _("acknowledged")),
        ("approved", _("approved")),
        ("application", _("application")),
        ("archived", _("archived")),
        ("cancelled", _("cancelled")),
        ("draft", _("draft")),
        ("new", _("new")),
        ("submitted", _("submitted")),
        # ("withdrawn", _("withdrawn")),
    )


class ReportedFunding(ReportedFundingMixin, Model):

    orcid = CharField(max_length=20, blank=True, null=True, editable=False)
    put_code = PositiveIntegerField(_("put-code"), null=True, blank=True, editable=False)
    report = ForeignKey(
        Report,
        on_delete=CASCADE,
        related_name="fundings",
    )
    state = StateField(default="new", verbose_name=_("status"))
    type = FixedCharField(
        _("Type"), max_length=1, choices=FUNDING_TYPES, help_text=_("Funding Type")
    )
    subtype = CharField(
        _("Subtype"), max_length=100, null=True, blank=True, help_text=_("Funding subtype")
    )
    title = CharField(
        _("Project"), max_length=400, null=True, blank=True, help_text=_("Title of funded project")
    )
    url = URLField(
        max_length=400,
        null=True,
        blank=True,
        help_text=_("Project link URL"),
    )
    description = TextField(null=True, blank=True)
    currency = ForeignKey(
        Currency,
        on_delete=SET_NULL,
        null=True,
        blank=True,
        db_column="currency",
        default="NZD",
        verbose_name=_("Funding currency"),
    )
    amount = DecimalField(
        null=True, blank=True, help_text=_("Total funding amount"), max_digits=10, decimal_places=2
    )
    share = PositiveSmallIntegerField(
        _("Share available"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        default=100,
    )

    start_date = DateField(blank=True, null=True)
    end_date = DateField(blank=True, null=True)
    agency = ForeignKey(
        Organisation, on_delete=SET_NULL, null=True, blank=True, verbose_name=_("Funding agency")
    )

    # def __str__(self):
    #     return f"{self.code}: {self.description}"

    class Meta:
        db_table = "reported_funding"


simple_history.register(
    ReportedFunding,
    inherit=True,
    table_name="reported_funding_history",
    bases=[ReportedFundingMixin, Model],
)


class PublicationType(Model):
    code = CharField(max_length=10, primary_key=True)
    code_2 = CharField(unique=True, max_length=2, null=True, blank=True)
    description = CharField(max_length=100, blank=True, null=True)
    orcid_type = CharField(
        max_length=100, unique=True, null=True, blank=True, help_text="ORCiD Work Type"
    )

    def natural_key(self):
        return self.code

    def __str__(self):
        return f"{self.code}: {self.description}"

    class Meta:
        db_table = "publication_type"


class RisPublicationType(Model):
    code = CharField(
        max_length=10,
        primary_key=True,
        verbose_name='Abbreviation ("Field Label")',
        db_column="code",
    )
    description = CharField(
        max_length=100, null=True, blank=True, verbose_name='Type ("Ref Type")'
    )
    category = CharField(max_length=100, blank=True, null=True, verbose_name="Category")
    type = ForeignKey(PublicationType, on_delete=SET_NULL, blank=True, null=True, db_column="type")

    def natural_key(self):
        return self.code

    def __str__(self):
        return f"{self.code}: {self.description}"

    class Meta:
        db_table = "ris_publication_type"
        db_table_comment = "RIS reference types (https://en.wikipedia.org/wiki/RIS_(file_format))"


class PublicationStatus(Model):
    # type = CharField(max_length=2)
    # type = ForeignKey(PublicationType, on_delete=DO_NOTHING)
    code = CharField(max_length=3, db_index=True)
    description = CharField(max_length=100, blank=True, null=True)

    def natural_key(self):
        return self.code

    def __str__(self):
        return f"{self.type.code}/{self.code}: {self.description}"

    class Meta:
        verbose_name_plural = _("publication statuses")
        db_table = "publication_status"
        # unique_together = (("type", "code"),)


class Publication(Model):
    # pid = IntegerField(primary_key=True)
    doi = CharField(
        max_length=400, blank=True, null=True, help_text=_("Digital Object Identifier (DOI)")
    )
    rsnz_ref = IntegerField(blank=True, null=True)

    # contract = ForeignKey(Contract, on_delete=CASCADE, blank=True, null=True)
    # contract_number = CharField(max_length=40, blank=True, null=True)

    # pstatus = CharField(max_length=3, blank=True, null=True)
    # ptype = CharField(max_length=2, blank=True, null=True)
    type = ForeignKey(PublicationType, on_delete=SET_NULL, blank=True, null=True, db_column="type")
    ris_type = ForeignKey(
        RisPublicationType, on_delete=SET_NULL, blank=True, null=True, db_column="ris_type"
    )
    status = ForeignKey(
        PublicationStatus, on_delete=DO_NOTHING, blank=True, null=True, db_column="status"
    )
    status_date = DateField(blank=True, null=True)
    title = CharField(max_length=1000)
    title2 = CharField(max_length=1000, blank=True, null=True)
    host = CharField(max_length=100, blank=True, null=True)
    journal = CharField(max_length=100, blank=True, null=True)
    publisher = CharField(max_length=100, blank=True, null=True)
    editor = CharField(max_length=100, blank=True, null=True)
    location = CharField(max_length=60, blank=True, null=True)
    url = CharField(max_length=150, blank=True, null=True)
    volume = CharField(max_length=10, blank=True, null=True)
    year_ref = IntegerField(blank=True, null=True)
    page_ref = CharField(max_length=14, blank=True, null=True)
    host_ref = CharField(max_length=10, blank=True, null=True)
    citations = IntegerField(blank=True, null=True)
    citations_date = DateField(blank=True, null=True)
    abstract = TextField(blank=True, null=True)
    uid = CharField(max_length=9, blank=True, null=True)
    updated_at = DateTimeField(blank=True, null=True)
    impact_factor = IntegerField(blank=True, null=True)
    impact_year = IntegerField(blank=True, null=True)
    xcr = FloatField(blank=True, null=True)
    isi_loc = CharField(max_length=50, blank=True, null=True)
    # imported form ORCID profile work record:
    orcid = CharField(max_length=20, blank=True, null=True, editable=False)
    put_code = PositiveIntegerField(_("put-code"), null=True, blank=True, editable=False)

    def __str__(self):
        return f"{self.title}"

    class Meta:
        db_table = "publication"


class PublicationAuthor(Model):
    publication = ForeignKey(Publication, on_delete=CASCADE, related_name="authors")
    name = CharField(max_length=400)
    type = CharField(
        max_length=100, blank=True, null=True, choices=Choices("PRIMARY", "SECONDARY")
    )

    class Meta:
        db_table = "publication_author"


class PublicationLink(Model):
    publication = ForeignKey(Publication, on_delete=CASCADE, related_name="links")
    link = URLField(max_length=255)
    type = CharField(
        max_length=100, blank=True, null=True, choices=Choices("LINK", "URL", "ATTACHMENT")
    )

    class Meta:
        db_table = "publication_link"


REPORT_COMMENT_CATEGORIES = Choices(("R", _("Risk of variation")), ("O", _("Other")))


class ReportComment(CommentModel):

    @property
    def object(self):
        return self.report

    @property
    def object_pk(self):
        return self.report_id

    report = ForeignKey(Report, on_delete=CASCADE, related_name="comments")
    # reply_to = ForeignKey("self", on_delete=CASCADE, related_name="replies", null=True, blank=True)
    # token = CharField(max_length=42, default=get_unique_invitation_token, unique=True)
    # comment = TextField(_("comment"), max_length=1000, null=True, blank=True)
    # attachment = PrivateFileField(
    #     _("attachment"),
    #     upload_to="reports",
    #     upload_subfolder=lambda instance: [
    #         hash_int(instance.report_id),
    #         "comments",
    #     ],
    #     null=True,
    #     blank=True,
    # )
    # submitted_by = ForeignKey(
    #     User,
    #     null=True,
    #     blank=True,
    #     on_delete=SET_NULL,
    #     verbose_name=_("submitted by"),
    #     related_name="report_comments",
    # )
    category = FixedCharField(
        choices=REPORT_COMMENT_CATEGORIES,
        max_length=1,
        null=True,
        blank=True,
    )
    alert_date = CharField(
        max_length=200,
        null=True,
        blank=True,
    )

    # @property
    # def target(self):
    #     return self.report

    # def import_reply(self, file, file_name=None, notify_author=True, request=None, by=None):
    #     return self.report.import_email(
    #         file,
    #         file_name=file_name,
    #         notify_author=notify_author,
    #         request=request,
    #         by=by,
    #         reply_to=self,
    #     )

    # def __str__(self):
    #     return f"Submitted by {self.submitted_by} at {self.created_at}"

    class Meta(CommentModel.Meta):
        db_table = "report_comment"
        default_related_name = "report_comments"


class ReportCommentRecipient(Model):
    comment = ForeignKey(ReportComment, on_delete=CASCADE, related_name="recipients")
    user = ForeignKey(User, on_delete=SET_NULL, null=True, blank=True, related_name="+")
    email = EmailField(max_length=200)
    is_cced = BooleanField(default=False)

    class Meta:
        db_table = "report_comment_recipient"
        verbose_name = _("recipient")


class ReportCommentAttachment(Model):
    comment = ForeignKey(ReportComment, on_delete=CASCADE, related_name="attachments")
    attachment = PrivateFileField(
        _("attachment"),
        upload_to="reports",
        upload_subfolder=lambda instance: [
            # hash_int(instance.application_id),
            hash_int(instance.comment.report_id),
            "comments",
            hash_int(instance.comment_id),
            "attachments",
        ],
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "report_comment_attachment"
        verbose_name = _("attachment")


ACTIVITY_CATEGORIES = Choices(
    ("A", _("Award")),
    ("C", _("Collaboration")),
    ("P", _("Publicity")),
    ("V", _("Visits")),
)


# class ActivityType(Model):

#     category = FixedCharField(max_length=1, choices=ACTIVITY_CATEGORIES)
#     description = CharField(_("description"), max_length=255, blank=True, null=True)

#     class Meta:
#         db_table = "activity_type"
#         # unique_together = (("contract", "period", "type"),)

# # Publicity
# #     Activity: Radio, TV, Newspaper, Popular Article, Newsletter, Outreach, Public Lecture, Conference, Other
# #     Details: ... (description)


class ReportedActivity(Model):
    # category = FixedCharField(max_length=1, choices=ACTIVITY_CATEGORIES)
    type = CharField(max_length=100, null=True, blank=True)
    orcid = CharField(max_length=20, blank=True, null=True, editable=False)
    put_code = PositiveIntegerField(_("put-code"), null=True, blank=True, editable=False)
    start_date = DateField(_("start date"), null=True, blank=True)
    end_date = DateField(_("end date"), null=True, blank=True)
    description = TextField(_("description"), max_length=2000, blank=True, null=True)
    organisation = CharField(
        _("organisation"), max_length=200, null=True, blank=True
    )  # entered name
    org = ForeignKey(
        Organisation,
        on_delete=SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("organisation"),
    )
    member = ForeignKey(ReportedEffort, null=True, blank=True, on_delete=SET_NULL)

    def __str__(self):
        return f"{self._meta.verbose_name.title()}: {getattr(self, 'full_name', self.member) or self.organisation or self.type}"

    class Meta:
        abstract = True


class ReportedPublicity(ReportedActivity):

    report = ForeignKey(Report, on_delete=CASCADE, related_name="publicities")

    class Meta:
        db_table = "reported_publicity"


class ReportedCollaboration(ReportedActivity):

    report = ForeignKey(Report, on_delete=CASCADE, related_name="collaborations")

    full_name = CharField(_("collaborator"), max_length=400)
    country = ForeignKey(
        Country,
        verbose_name=_("country"),
        db_column="country",
        on_delete=SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        default="NZ",
    )
    person = ForeignKey(
        Person,
        on_delete=SET_NULL,
        blank=True,
        null=True,
        related_name="+",
    )

    class Meta:
        db_table = "reported_collaboration"


class ReportedVisit(ReportedActivity):

    report = ForeignKey(Report, on_delete=CASCADE, related_name="visits")

    full_name = CharField(_("host"), max_length=400)
    person = ForeignKey(
        Person,
        on_delete=SET_NULL,
        blank=True,
        null=True,
        related_name="+",
    )
    country = ForeignKey(
        Country,
        verbose_name=_("country"),
        db_column="country",
        on_delete=SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        default="NZ",
    )

    class Meta:
        db_table = "reported_visit"


class ReportedAward(ReportedActivity):

    report = ForeignKey(Report, on_delete=CASCADE, related_name="awards")

    class Meta:
        db_table = "reported_award"


class ChangeType(Model):

    code = FixedCharField(max_length=2, primary_key=True)
    description = CharField(max_length=100)
    definition = TextField(max_length=200, null=True, blank=True)

    def __str__(self):
        return self.description

    class Meta:
        db_table = "change_type"
        ordering = ["description"]


class ChangeCategory(Model):

    type = ForeignKey(ChangeType, on_delete=CASCADE, db_column="type")
    code = CharField(max_length=2, primary_key=True)
    description = CharField(max_length=100)
    definition = TextField(max_length=200, null=True, blank=True)
    parent = ForeignKey(
        "self",
        on_delete=CASCADE,
        null=True,
        blank=True,
        related_name="subcategories",
        db_column="category",
        help_text="Parent category",
    )

    def __str__(self):
        return self.description

    class Meta:
        db_table = "change_category"
        ordering = ["description"]
        verbose_name_plural = _("variant categories")


class ChangeRequestMixin:
    STATES = Choices(
        ("accepted", _("Under Review")),
        ("acknowledged", _("Acknowledged")),
        ("approved", _("Approved")),
        ("application", _("Application")),
        ("archived", _("Archived")),
        ("cancelled", _("Cancelled")),
        ("declined", _("Declined")),
        ("draft", _("WIP")),
        ("submitted", _("Received")),
        # ("submitted", _("Submitted")),
        ("withdrawn", _("Withdrawn")),
    )


# TODO: add history
class ChangeRequest(PdfFileMixin, CommentMixin, ChangeRequestMixin, Model):

    tags = TaggableManager(blank=True)
    number = CharField(
        _("number"), max_length=24, null=True, blank=True, unique=True, editable=False
    )
    state = StateField(default="draft", verbose_name=_("state"))
    state_changed_at = MonitorField(monitor="state", null=True, default=None, blank=True)
    types = ManyToManyField(
        ChangeType,
        db_table="change_request_change_type",
        verbose_name=_("Type(s)"),
        related_name="change_requests",
    )
    categories = ManyToManyField(
        ChangeCategory,
        db_table="change_request_change_category",
        verbose_name=_("Categories"),
        related_name="change_requests",
        blank=True,
    )
    subcategories = ManyToManyField(
        ChangeCategory,
        db_table="change_request_change_subcategory",
        verbose_name=_("Subcategories"),
        related_name="+",
        blank=True,
    )
    contract = ForeignKey(Contract, on_delete=CASCADE, related_name="change_requests")
    derivative = ForeignKey(
        Contract,
        on_delete=CASCADE,
        null=True,
        blank=True,
        related_name="originated_by",
        help_text="Derivative contract (variation or extension)",
    )
    new_host = ForeignKey(
        Organisation,
        null=True,
        blank=True,
        on_delete=CASCADE,
        related_name="change_requests",
        help_text="New host organisation",
    )
    submitted_by = ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=SET_NULL,
        related_name="change_requests",
    )
    description = TextField(null=True, blank=True)
    file = PrivateFileField(
        verbose_name=_("Request Letter"),
        blank=True,
        null=True,
        upload_to="changes",
        upload_subfolder=lambda instance: [
            "requests",
            # hash_int(instance.application_id),
            hash_int(instance.contract_id),
        ],
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
    converted_file = ForeignKey(ConvertedFile, null=True, blank=True, on_delete=SET_NULL)
    reply = TextField(
        null=True, blank=True, default='<p style="font-family: Arial; font-size: 10px;"></p>'
    )

    def is_ro(self, user):
        return self.contract and self.contract.org.research_offices.filter(user=user).exists()

    def is_admin(self, user):
        return user.is_staff or user.is_superuser or user.is_site_staff

    @cached_property
    def pi(self):
        return self.contract and self.contract.pi

    @classmethod
    def user_object_counts(
        cls, user, state=None, round=None, request=None, queryset=None, *args, **kwargs
    ):
        return (
            cls.user_objects(
                user=user, state=state, round=round, select_related=False, request=request
            )
            .values_list("state")
            .annotate(total=Count("pk", distinct=True))
            .order_by()
        )

    @classmethod
    def user_objects(
        cls,
        user,
        state=None,
        round=None,
        select_related=True,
        request=None,
        queryset=None,
        *args,
        **kwargs,
    ):
        q = (queryset or cls.objects.all()).filter(contract__site_id=settings.SITE_ID)

        if select_related:
            prefetch_related_objects(q, "contract__application__round")

        if state:
            if isinstance(state, (list, tuple)):
                q = q.filter(state__in=state)
            else:
                q = q.filter(state=state)
        else:
            q = q.filter(~Q(state="archived"))

        if user.is_staff or user.is_superuser or user.is_site_staff:
            return q

        f = (
            Q(submitted_by=user)
            | Q(contract__submitted_by=user)
            | Q(contract__members__user=user)
            | Q(contract__org__research_offices__user=user)
        )
        q = q.filter(f)
        q = q.distinct()

        return q

    def __str__(self):
        return f"{self.contract.number}:{self.pk}"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self.get_number(self.contract)
        super().save(*args, **kwargs)
        if not self.number:
            self.number = self.new_number(self.contract)
            self.save(update_fields=["number"])

    def get_number(self, contract=None):
        if self.number:
            return self.number

        if not contract and self.pk and self.contract_id:
            contract = self.contract

        q = ChangeRequest.objects.filter(~Q(number=""), number__isnull=False, contract=contract)
        if self.pk:
            q = q.exclude(pk=self.pk)
        v = (
            max(
                [
                    0,
                    *[
                        int(n.split(":")[-1])
                        for n in q.values_list("number", flat=True)
                        if n and n.strip()
                    ],
                ]
            )
            + 1
        )
        self.number = f"{contract.number}:{v:1d}"
        return self.number

    @fsm_log
    @transition(
        field=state,
        source=["*"],
        target="draft",
        custom=dict(verbose="Save Draft", button_name="Save Draft", admin=False),
    )
    def save_draft(self, *args, **kwargs):
        if not self.submitted_by:
            by = kwargs.get("by") or kwargs.get("request") and kwargs["request"].user
            if not (by.is_superuser or by.is_site_staff):
                self.submitted_by = by

    @fsm_log
    @transition(
        field=state,
        source=["accepted", "approved", "declined"],
        target="archived",
        custom=dict(verbose="Archive", button_name="Archive"),
        permission=lambda instance, user: instance.is_admin(user),
    )
    def archive(self, *args, **kwargs):
        pass

    @fsm_log
    @transition(
        field=state,
        source=["new", "draft"],
        target="submitted",
        custom=dict(verbose="Submit", button_name="Submit for review", admin=False),
        permission=lambda instance, user: instance.is_ro(user),
    )
    def submit(self, *args, **kwargs):
        if not self.submitted_by:
            by = kwargs.get("by") or kwargs.get("request") and kwargs["request"].user
            if not (by.is_superuser or by.is_site_staff):
                self.submitted_by = by
        pass

    @fsm_log
    @transition(
        field=state,
        source=["draft", "submitted", "accepted", "approved"],
        target="withdrawn",
        custom=dict(verbose="Withdraw", button_name="Withdraw"),
        permission=lambda instance, user: instance.is_ro(user),
    )
    def withdraw(self, *args, **kwargs):
        request = kwargs.get("request")
        if not self.submitted_by:
            by = kwargs.get("by") or kwargs.get("request") and kwargs["request"].user
            if not (by.is_superuser or by.is_site_staff):
                self.submitted_by = by
        if d := self.derivative:
            d.delete()
            if request:
                messages.info(
                    request, f"The contract variation and/or transfer record {d} was deleted."
                )

    def create_new_contract(self, request=None, by=None, description=None, *args, **kwargs):
        is_variation = not self.types.filter(code="TR").exists()
        new_contract = self.contract.clone(
            change_request=self,
            is_variation=is_variation,
        )
        self.derivative = new_contract

        if request:
            url = reverse("contract", args=[new_contract.pk])
            messages.success(
                request,
                (
                    f'Variation <a href="{url}" target="_blank">{new_contract}</a> created.'
                    if is_variation
                    else f'Transferred contract <a href="{url}" target="_blank">{new_contract}</a> created.'
                ),
            )
        return new_contract

    @fsm_log
    @transition(
        field=state,
        source=["submitted"],
        target="approved",
        custom=dict(verbose="Approve", button_name="Approve"),
        permission=lambda instance, user: instance.is_admin(user),
    )
    def approve(self, request=None, by=None, description=None, *args, **kwargs):
        assert self.contract, "Contract is required to approve the change request."
        if not self.derivative:
            try:
                self.create_new_contract(
                    request=request, by=by, description=description, *args, **kwargs
                )
            except Exception as e:
                if request:
                    messages.error(request, f"Failed to approve the change request: {e}")
                capture_message(e)

    # @fsm_log
    # @transition(
    #     field=state,
    #     source=["*"],
    #     target="accepted",
    #     custom=dict(verbose="Accept", button_name="Accept", admin=False),
    #     permission=lambda instance, user: instance.is_admin(user),
    # )
    # def accept(self, request=None, by=None, description=None, *args, **kwargs):
    #     assert self.contract, "Contract is required to accept the change request."
    #     try:
    #         self.create_new_contract(request=request, by=by, description=description, *args, **kwargs)
    #     except Exception as e:
    #         if request:
    #             messages.error(request, f"Failed to accept the change request: {e}")
    #         capture_message(e)

    @fsm_log
    @transition(
        field=state,
        source=["draft", "submitted"],
        target="declined",
        custom=dict(verbose="Decline", button_name="Decline", admin=False),
        permission=lambda instance, user: instance.is_admin(user),
    )
    def decline(self, request=None, by=None, description=None, *args, **kwargs):
        if not by and request:
            by = request.user
        url = self.get_full_detail_url(request=request)
        link_name = domain_to_macrons(url)
        html_message = (
            f"<p>Kia ora {self.submitted_by.full_name}</p>"
            if self.submitted_by
            else "<p>Kia ora!</p>"
            f'<p>The change request <a href="{url}">{link_name}'
            "</a> was declined by {by}.</p>"
        )
        recipients = self.host_recipients
        if description:
            html_message += f"<p>Reason:<p><pre>{description}</pre>"
        send_mail(
            from_email="variations",
            subject=f"Change request was declined by {by.full_name_with_email}",
            html_message=html_message,
            cc=by.email,
            recipients=self.host_recipients,
            thread_index=self.thread_index,
            thread_topic=self.thread_topic,
            request=request,
            site=self.contract.site,
        )
        if request:
            messages.info(
                request,
                "Notification was sent to "
                f"{', '.join(r if isinstance(r, str) else r.full_name_with_email for r in recipients)}.",
            )

    @property
    def agency_recipients(self):
        c = self.contract
        return [c.fund.email] if c.fund and c.fund.email else c.site.staff_users.all()

    @property
    def host_recipients(self):
        return self.contract.host_emails

    class Meta:
        db_table = "change_request"


class ChangeRequestComment(CommentModel):

    @property
    def object(self):
        return self.change_request

    @property
    def object_pk(self):
        return self.change_request_id

    change_request = ForeignKey(ChangeRequest, on_delete=CASCADE, related_name="comments")
    # attachment = PrivateFileField(
    #     _("attachment"),
    #     upload_to="change_requests",
    #     upload_subfolder=lambda instance: [
    #         # "change_requests",
    #         # hash_int(instance.application_id),
    #         hash_int(instance.change_request_id),
    #         "comments",
    #     ],
    #     null=True,
    #     blank=True,
    # )
    # submitted_by = ForeignKey(
    #     User,
    #     null=True,
    #     blank=True,
    #     on_delete=SET_NULL,
    #     verbose_name=_("submitted by"),
    #     related_name="change_request_comments",
    # )

    # def __str__(self):
    #     return f"Submitted by {self.submitted_by} at {self.created_at}"

    # @property
    # def target(self):
    #     return self.change_request

    class Meta(CommentModel.Meta):
        db_table = "change_request_comment"
        default_related_name = "change_request_comments"


class ChangeRequestCommentRecipient(Model):

    comment = ForeignKey(ChangeRequestComment, on_delete=CASCADE, related_name="recipients")
    user = ForeignKey(User, on_delete=SET_NULL, null=True, blank=True, related_name="+")
    email = EmailField(max_length=200)
    is_cced = BooleanField(default=False)

    class Meta:
        db_table = "change_request_comment_recipient"
        verbose_name = _("recipient")


class ChangeRequestCommentAttachment(Model):
    comment = ForeignKey(ChangeRequestComment, on_delete=CASCADE, related_name="attachments")
    attachment = PrivateFileField(
        _("attachment"),
        upload_to="change_requests",
        upload_subfolder=lambda instance: [
            # hash_int(instance.application_id),
            hash_int(instance.comment.change_request_id),
            "comments",
            hash_int(instance.comment_id),
            "attachments",
        ],
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "change_request_comment_attachment"
        verbose_name = _("attachment")


class Impersonation(HelperMixin, Base):
    impersonated_at = DateTimeField(null=True, default=timezone.now, editable=False)
    user = ForeignKey(User, on_delete=CASCADE, related_name="impersonations")
    impersonated = ForeignKey(User, on_delete=PROTECT, related_name="impersonations_by")

    class Meta:
        db_table = "impersonation"


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
