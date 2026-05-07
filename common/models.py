import base64
import copy
import os
import pathlib

import boto3
import hashlib
from pathlib import Path
from django.core.files import File

from botocore.exceptions import ClientError
from django.conf import settings
from django.contrib import admin
from django.contrib.contenttypes.models import ContentType
from django.contrib.sites.models import Site
from django.core import checks, validators
from django.db import connection, connections, models, router
from django.db.models import CharField, DateTimeField, EmailField, ForeignObjectRel
from django.db.models import Model as Base
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.deconstruct import deconstructible
from django.utils.functional import LazyObject, cached_property
from django.utils.safestring import mark_safe
from django_q.tasks import async_task
from model_utils import Choices
from private_storage.servers import DjangoServer, add_no_cache_headers
from private_storage.storage.files import PrivateFileSystemStorage
from sentry_sdk import capture_exception

EmailField.register_lookup(Lower)

SEX_CHOICES = Choices("female", "male", "other")

ETHNICITY_COICES = Choices(
    "European",
    "Māori",
    "Chinese",
    "Indian",
    "Samoan",
    "Tongan",
    "Cook Islands Māori",
    "English",
    "Filipino",
    "New Zealander",
    "Other",
)

TITLES = Choices(
    ("MR", "Mr"),
    ("MRS", "Mrs"),
    ("MS", "Ms"),
    ("DR", "Dr"),
    ("PROF", "Prof"),
)


def domain_to_macrons(url):
    if url.startswith("https://xn--"):
        p1, p2 = url.split("xn--")
        p2 = f"xn--{p2}".encode().decode("idna")
        return f"{p1}{p2}"
    return url


def calculate_file_hash(f, algorithm='sha256'):
    """Calculate the hash of a file-like object."""
    hasher = hashlib.sha256() if algorithm == 'sha256' else hashlib.md5()
    # Read the file in chunks to be memory efficient
    for chunk in f.chunks():
        hasher.update(chunk)
    return hasher.hexdigest()


# class PrivateFile(PivateFile):
#     pass

# class ArchivalDjangoServer(DjangoServer):

#     @staticmethod
#     @add_no_cache_headers
#     def serve(private_file):
#         # retrieve the file from archive storage if needed
#         if not private_file.exists_locally(name):
#             private_file.storage.retrieve_from_archive(private_file.relative_name)

#         response = super().serve(private_file)
#         return response
#         pass


@deconstructible
class ArchivalStorage(PrivateFileSystemStorage):
    def __init__(
        self,
        location=None,
        base_url=None,
        file_permissions_mode=None,
        directory_permissions_mode=None,
        allow_overwrite=False,
        *args,
        **kwargs,
    ):
        super().__init__(
            location=location,
            base_url=base_url,
            file_permissions_mode=file_permissions_mode,
            directory_permissions_mode=directory_permissions_mode,
            allow_overwrite=allow_overwrite,
            *args,
            **kwargs,
        )

        access_key = getattr(settings, "AWS_ACCESS_KEY_ID", None)
        secret_key = getattr(settings, "AWS_SECRET_ACCESS_KEY", None)
        self.bucket = bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", "rsta-portal-archive")
        region_name = getattr(settings, "AWS_S3_REGION_NAME", None)
        # website_endpoint_format ="http://%(bucket)s.s3-website-%(location)s.amazonaws.com/"
        hostname = f"{region_name}.vultrobjects.com"

        session = boto3.session.Session()
        client = session.client(
            "s3",
            region_name=region_name,
            endpoint_url=f"https://{hostname}",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        # resp=client.list_buckets()
        self.s3 = client

    def get_alternative_name(self, file_root, file_ext):
        return "%s_%s%s" % (file_root, get_random_string(2), file_ext)

    def open(self, name, mode="rb"):
        # Try to open from primary location first
        try:
            return super().open(name, mode)
        except FileNotFoundError as e:
            try:
                # response = self.s3.get_object(Bucket='archive', Key=name)
                # return response['Body']
                full_path = os.path.join(self.location, name)
                directory = os.path.dirname(full_path)
                if not os.path.exists(directory):
                    os.makedirs(directory)
                self.s3.download_file(self.bucket, name, full_path)
                return super().open(full_path, mode)
            except self.s3.exceptions.NoSuchKey as ex:
                capture_exception(ex)
                raise e
            except ClientError as ex:
                capture_exception(ex)
                raise e
            raise  # Re-raise if not found anywhere

    def exists_in_archive(self, name):
        try:
            self.s3.head_object(Bucket=self.bucket, Key=name)
            return True
        except self.s3.exceptions.NoSuchKey:
            return False
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False  # Object does not exist
            else:
                # Re-raise for other errors (e.g., permission issues, network problems)
                raise e

    def exists_locally(self, name):
        return super().exists(name)

    def exists(self, name):
        if self.exists_locally(name):
            return True
        return self.exists_in_archive(name)

    def retrieve_from_archive(self, name):
        try:
            # response = self.s3.get_object(Bucket='archive', Key=name)
            # return response['Body']
            full_path = os.path.join(self.location, name)
            self.s3.download_file(self.bucket, name, full_path)
        except self.s3.exceptions.NoSuchKey as ex:
            capture_exception(ex)
            raise ex
        except ClientError as ex:
            capture_exception(ex)
            raise ex

    def save(self, name, content, max_length=None):

        if content and not hasattr(content, "chunks"):
            content = File(content, name)

        if name is None:
            name = content.name

        file_hash = calculate_file_hash(content)
        for file_path in (Path(self.location) / "HASHES").rglob(f"{file_hash}.md5"):
            if file_path.is_file():
                with open(file_path, "r") as hash_file:
                    existing_file_name = hash_file.readline().strip()
                    has_in_the_list = name in hash_file.read()
                if existing_file_name and (Path(self.location) / existing_file_name).is_file():
                    if not has_in_the_list:
                        with open(file_path, "a") as hash_file:
                            hash_file.write(f"\n{name}")
                    return existing_file_name

        name = super().save(name=name, content=content, max_length=max_length)

        # full_path = self.path(name)
        # directory = os.path.dirname(full_path)
        # shaddow copy to archive location
        if pathlib.Path(name).parts[0] not in ["converted", "archive", "archived", "temp", "tmp"]:
            try:
                async_task(
                    save_to_archive,
                    # sync=True,
                    name=name,
                )
            except Exception as e:
                capture_exception(e)

        hash_file_name = os.path.join(self.location, "HASHES", f"{file_hash}.md5")
        directory = os.path.dirname(hash_file_name)
        if not os.path.exists(directory):
            os.makedirs(directory)

        with open(hash_file_name, "w") as hash_file:
            hash_file.write(name)

        return name

    # You would also need to override 'url', 'path', etc. to handle the archive location correctly
    # based on your specific requirements.


archive_storage = ArchivalStorage()


def save_to_archive(name=None, names=None, keep=True):

    if name:
        names = [name]
    for n in names:
        if n.startswith(archive_storage.base_location):
            full_path = n
            n = n.removeprefix(archive_storage.base_location)
        else:
            full_path = archive_storage.path(n)

        try:
            if not archive_storage._allow_overwrite and not archive_storage.exists_in_archive(n):
                archive_storage.s3.upload_file(full_path, archive_storage.bucket, n)
        except Exception as e:
            capture_exception(e)
            raise e
        else:
            if keep is False and keep is not None:
                if archive_storage.exists_locally(n):
                    os.remove(full_path)


def sync_with_archive(name=None, names=None):
    """Sync files to archive storage if not already present locally."""

    if name:
        names = [name]
    for n in names:
        if n.startswith(archive_storage.base_location):
            full_path = n
            n = n.removeprefix(archive_storage.base_location)
        else:
            full_path = archive_storage.path(n)

        try:
            if not archive_storage.exists_locally(n):
                archive_storage.s3.download_file(archive_storage.bucket, n, full_path)
        except Exception as e:
            capture_exception(e)
            raise e


class TimeStampModel(Base):
    # created_at = DateTimeField(auto_now_add=True, null=True)
    created_at = DateTimeField(null=True, default=timezone.now, editable=False)
    updated_at = DateTimeField(auto_now=True, null=True)

    class Meta:
        abstract = True
        get_latest_by = "updated_at"


class TimeStampMixin(Base):
    # created_at = DateTimeField(auto_now_add=True, null=True)
    created_at = DateTimeField(null=True, default=timezone.now, editable=False)
    updated_at = DateTimeField(auto_now=True, null=True)

    class Meta:
        abstract = True
        get_latest_by = "updated_at"


# class TimeStampedModel(models.Model):
#     """
#     TimeStampedModel

#     An abstract base class model that provides self-managed "created" and
#     "modified" fields.
#     """

#     created = CreationDateTimeField(_("created"))
#     modified = ModificationDateTimeField(_("modified"))

#     def save(self, **kwargs):
#         self.update_modified = kwargs.pop(
#             "update_modified", getattr(self, "update_modified", True)
#         )
#         super().save(**kwargs)

#     class Meta:
#         abstract = True
#         get_latest_by = "modified"


class HelperMixin:

    def get_full_url(self, name, request=None, *args, **kwargs):
        if name.startswith("/"):
            url = name
        else:
            url = reverse(name, args=args, kwargs=kwargs)
        if url:
            if request:
                url = request.build_absolute_uri(url)
            else:
                site = Site.objects.get_current()
                url = f"https://{site.domain}{url}"
            return domain_to_macrons(url)

    def clone(self, exclude_related_models=None, *args, **kwargs):
        clone = copy.copy(self)
        clone.pk = None
        setattr(clone, "created_at", timezone.now())
        setattr(clone, "updated_at", None)
        if kwargs:
            for k, v in kwargs.items():
                setattr(clone, k, v)
        clone.save()

        for field in self._meta.get_fields():
            if (
                not isinstance(field, ForeignObjectRel)
                or exclude_related_models
                and field.related_model in exclude_related_models
            ):
                continue

            model = field.related_model
            related = list(model.objects.filter(**{field.remote_field.name: self}))
            if not related:
                continue
            for o in related:
                o.pk = None
                setattr(o, field.remote_field.name, clone)
            model.objects.bulk_create(related)

        return clone

    @admin.display(description="State", empty_value="N/A")
    def STATE(self):
        if hasattr(self, "state") and self.state:
            if self.state_changed_at:
                sca = self.state_changed_at.strftime("%d-%m-%Y %H:%m")
                return mark_safe(
                    f"""<b title="State changed at {sca}">{self.get_state_display().upper()}</b> ({sca})"""
                )
            return mark_safe(f"<b>{self.get_state_display().upper()}</b>")
        return ""

    @classmethod
    def get_by_thread_index(cls, thread_index, thread_topic=None):
        try:
            decoded = base64.b64decode(thread_index).decode()
            parts = decoded.split(":")
            # site_id = None
            model = None
            if len(parts) == 3:
                site_id = parts[0]
                model = parts[1]
                pk = parts[3]
            elif len(parts) == 2:
                model = parts[0]
                pk = parts[1]
            else:
                pk = parts[0]
            if model and cls._meta.abstract:
                if model.isdigit():
                    ct = ContentType.objects.get_for_id(int(model))
                    cls = ct.model_class()
                else:
                    cls = cls._meta.apps.get_model(model)
            return getattr(cls, "all_objects", cls.objects).get(pk=pk)
        except Exception:
            return None

    @property
    def thread_index(self):
        if ct := ContentType.objects.get_for_model(self):
            return base64.b64encode(f"{ct.pk}:{self.pk}".encode()).decode()
        if site_id := getattr(self, "site_id", None):
            return base64.b64encode(f"{site_id}:{self.pk}".encode()).decode()
        return base64.b64encode(f"{self.pk}".encode()).decode()

    @property
    def thread_topic(self):
        if hasattr(self, "number"):
            return self.number
        return str(self)

    @property
    def can_export_to_pdf(self):
        return hasattr(self, "to_pdf")

    @property
    def current_site_id(self):
        return int(settings.SITE_ID)

    @classmethod
    def get_current_site_id(self):
        return int(settings.SITE_ID)

    @classmethod
    def first(cls):
        return cls.objects.first()

    @classmethod
    def last(cls):
        return cls.objects.last()

    @classmethod
    def get(cls, *args, **kwargs):
        if args:
            return cls.objects.get(pk=args[0])
        elif kwargs:
            return cls.objects.get(**kwargs)
        return cls.objects.first()

    @classmethod
    def create(cls, *args, **kwargs):
        return cls.objects.create(*args, **kwargs)

    @classmethod
    def bulk_create(cls, *args, **kwargs):
        return getattr(cls, "all_objects", cls.objects).bulk_create(*args, **kwargs)

    @classmethod
    def bulk_update(cls, *args, **kwargs):
        return getattr(cls, "all_objects", cls.objects).bulk_update(*args, **kwargs)

    @classmethod
    def get_or_create(cls, *args, defaults=None, **kwargs):
        if o := cls.objects.filter(*args, **kwargs).order_by("-pk").first():
            return o, False
        return cls.objects.get_or_create(defaults, **kwargs)

    @classmethod
    def where(cls, *args, **kwargs):
        return cls.objects.filter(
            *args, **{k: v.pk if isinstance(v, LazyObject) else v for (k, v) in kwargs.items()}
        )

    @property
    def admin_url(self):
        return reverse(
            f"admin:{self._meta.app_label}_{self._meta.model_name}_change", args=[str(self.id)]
        )

    def get_round(self):
        return getattr(self, "round", None)

    # def to_pdf(
    #     self,
    #     request=None,
    #     user=None,
    #     add_headers=None,
    #     skip_excluded=False,
    #     cache=False,
    #     *args,
    #     **kwargs
    # ):
    #     """Create PDF file for export and return PdfMerger"""

    #     r = self.get_round()
    #     site_id = getattr(self, "site_id", None) or settings.SITE_ID

    #     if not user and request:
    #         user = request.user

    #     attachments = []
    #     if not for_panellists and request:
    #         for_panellists = request.GET.get("for_panellists", False)
    #     include_header_page = not (site_id in [2, 5] and for_panellists)
    #     if self.file:
    #         attachments.append(
    #             (_("Application Form"), settings.PRIVATE_STORAGE_ROOT + "/" + str(self.pdf_file))
    #         )

    #     if (user.is_admin or for_panellists or is_panellist) and self.budget:
    #         attachments.append(
    #             (
    #                 _("Budget"),
    #                 # settings.PRIVATE_STORAGE_ROOT + "/" + str(self.budget),
    #                 self.bugget_pdf,
    #             )
    #         )

    #     if (
    #         r.applicant_cv_required
    #         and not self.documents.filter(document_type__role="CV").exists()
    #         and (cv := self.cv or CurriculumVitae.last_user_cv(self.submitted_by))
    #     ):
    #         cvs.append(cv)
    #         attachments.append(
    #             (
    #                 f"{cv.full_name} {_('Curriculum Vitae')}",
    #                 # settings.PRIVATE_STORAGE_ROOT + "/" + str(cv.pdf_file),
    #                 cv.pdf_file.path,
    #                 include_header_page and cv.title_page,
    #             )
    #         )

        def add_testimonials(attachments, user=None):
            for t in self.get_testimonials(has_testified=True, user=user):
                referee = t.referee
                if referee:
                    if (
                        referee.survey_token
                        and referee.survey_token_id
                        and referee.survey_completed_at
                        and connection.vendor != "sqlite"
                    ):
                        response = referee.get_response(
                            output_format="pdf",
                            exclude_scores=for_panellists or is_panellist,
                            exclude_confidential=exclude_confidential,
                        )
                        if response and not isinstance(
                            response, dict
                        ):  ## {'status': 'No Data, survey table does not exist.'}
                            attachments.append(
                                (
                                    _("Referee Survey Submitted By %s") % t.referee.full_name,
                                    response,
                                    t.title_page,
                                )
                            )
                    if t.file and not exclude_confidential:  ## dont't attache files
                        attachments.append(
                            (
                                (
                                    _("Referee Report Submitted By %s")
                                    if site_id == 5
                                    else _("Testimonial Form Submitted By %s")
                                )
                                % t.referee.full_name,
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
                user.is_admin
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
            # resync referee with LimeSurvey:
            if r.survey_id:
                # referees that might need to be re-synced:
                referees = self.referees.filter(
                    Q(survey_completed_at__isnull=True) | Q(testimonial__isnull=True)
                )
                if referees.exists():
                    try:
                        r.sync_referee_surveys(request=request, referees=referees)
                    except Exception as ex:
                        logger.exception("Error syncing referee surveys: %s", ex)
                        capture_exception(ex)
            if (
                user.is_admin
                or self.is_applicant(user)
                or user.is_site_staff
                or is_panellist
                or for_panellists
            ):
                if r.survey_id or not exclude_confidential:
                    add_testimonials(attachments)
            else:
                if r.survey_id or not exclude_confidential:
                    add_testimonials(attachments, user=user)

        ssl._create_default_https_context = ssl._create_unverified_context

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
                "round": self.round,
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
                "for_pdf_export": True,
            }
            if for_panellists and (user.is_superuser or user.is_site_staff):
                if site_id in [2, 5]:
                    referees = (
                        self.referees.order_by("survey_completed_at")
                        if r.survey_id
                        else self.referees.order_by("testified_at")
                    )
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
                    import_outline = site_id != 5
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


class Model(HelperMixin, TimeStampModel):
    # TODO: figure out how to make generic table naming:
    # history = HistoricalRecords(inherit=True)

    @property
    def model_name(self):
        return self._meta.model_name

    @property
    def detail_url(self):
        model_name_slug = self._meta.db_table.replace("_", "-")
        if number := (getattr(self, "number", None) or getattr(self, "code", None)):
            try:
                return reverse(f"{model_name_slug}-detail", args=[str(number)])
            except:
                return reverse("object-detail", kwargs={"model": self._meta.model_name, "number": str(number)})
        try:
            return reverse(model_name_slug, args=[str(self.pk)])
        except:
            try:
                return reverse(f"{model_name_slug}s", args=[str(self.pk)])
            except:
                return reverse("object", kwargs={"model": self._meta.model_name, "pk": str(self.pk)})

    @cached_property
    def export_filename(self):
        if number := (getattr(self, "number", None) or getattr(self, "code", None)):
            return f"{number}.pdf"
        return f"{self._meta.model_name}_{self.pk}.pdf"

    @cached_property
    def export_url(self):
        model_name_slug = self._meta.db_table.replace("_", "-")
        try:
            if filename := self.get_export_filename():
                return reverse(
                    f"{model_name_slug}-export-fn",
                    kwargs={"pk": self.pk, "filename": filename},
                )
            else:
                return reverse(f"{model_name_slug}-export", args=[str(self.pk)])
        except:
            try:
                return reverse(f"{model_name_slug}-export", args=[str(self.pk)])
            except:
                return None

    def get_full_detail_url(self, request=None):
        return self.get_full_url(self.detail_url, request=request)

    def get_absolute_url(self):
        model_name_slug = self._meta.db_table.replace("_", "-")
        try:
            url = reverse(model_name_slug, args=[str(self.id)])
        except:
            try:
                url = reverse(f"{model_name_slug}-detail", args=[str(self.id)])
            except:
                url = reverse(f"{model_name_slug}-list")
        if url:
            return url

    @property
    def update_url(self):
        model_name_slug = self._meta.db_table.replace("_", "-")
        return reverse(f"{model_name_slug}-update", args=[str(self.pk)])

    def get_full_update_url(self, request=None):
        url = self.update_url
        if url:
            if request:
                url = request.build_absolute_uri(url)
            else:
                site = Site.objects.get_current()
                url = f"https://{site.domain}{url}"
            return domain_to_macrons(url)

    @classmethod
    def get_or_404(cls, *args, **kwargs):
        return get_object_or_404(cls, *args, **kwargs)

    class Meta:
        abstract = True
        ordering = ["-id"]


class PersonMixin:

    def get_orcid(self):
        """find user ORCID value."""
        if orcid := getattr(self, "orcid", None):
            return orcid
        if user := self.get_user():
            return user.get_orcid()

    def get_user(self):
        if hasattr(self, "user"):
            return self.user
        elif hasattr(self, "owner") and self.owner:
            return self.owner
        elif hasattr(self, "submitted_by"):
            return self.submitted_by
        elif hasattr(self, "profile") and self.profile.user:
            return self.profile.user
        elif getattr(self, "referee", None) and self.referee.user:
            return self.referee.user
        elif hasattr(self, "username"):
            return self

    @cached_property
    def full_name(self):
        user = self.get_user()
        first_name = getattr(self, "first_name", None) or user and user.first_name
        if middle_names := getattr(self, "middle_names", None) or user and user.middle_names:
            middle_names = (
                middle_names.replace(",", " ").replace(", ", " ").replace("  ", " ").strip()
            )
        last_name = getattr(self, "last_name", None) or user and user.last_name
        full_name = " ".join(s for s in [first_name, middle_names, last_name] if s)
        if hasattr(self, "title") and self.title:
            full_name = f"{self.title} {full_name}"
        return full_name and full_name.strip() or user and user.username or self.email

    def get_first_name(self):
        user = self.get_user()
        return getattr(self, "first_name", None) or user and user.first_name

    def get_last_name(self):
        user = self.get_user()
        return getattr(self, "last_name", None) or user and user.last_name

    @cached_property
    def full_name_with_email(self):
        user = self.get_user()
        email = getattr(self, "email", None) or user and user.email
        if full_name := self.full_name:
            return f"{full_name} ({email})"
        if email:
            return email
        return getattr(self, "code", None)

    @cached_property
    def full_name_with_title(self):
        user = self.get_user()
        first_name = getattr(self, "first_name", None) or user and user.first_name
        middle_names = getattr(self, "middle_names", None) or user and user.middle_names
        middle_name_initials = middle_names and "".join(
            f"{n.strip()[0].upper()}." for n in middle_names.split(",")
        )
        last_name = getattr(self, "last_name", None) or user and user.last_name
        full_name = " ".join(s for s in [first_name, middle_name_initials, last_name] if s)
        if hasattr(self, "title") and self.title:
            full_name = f"{self.title.name} {full_name}"
        return full_name or user and user.username or self.email

    # def get_title(self):
    #     if not (title := getattr(self, "title", None)):
    #         if u := self.get_user():
    #             if not (title := getattr(u, "title", None)):

    @cached_property
    def full_email_address(self):
        user = self.get_user() or self
        email = (
            getattr(self, "email", None)
            or user
            and (
                user.email
                or user.emailaddress_set.filter(primary=True).first()
                or user.emailaddress_set.last()
            )
        )

        if full_name := self.full_name:
            return f'"{full_name}" <{email}>'
        return email

    def __str__(self):
        return self.full_name

    def get_org_email(self, org=None):
        if org:
            if hasattr(self, "org") and self.org == org and hasattr(self, "email") and self.email:
                return self.email
            if hasattr(self, "person"):
                if affiliation := self.person.affiliations.filter(org=org).order_by("-pk").first():
                    email = affiliation.email
                    if email:
                        return email
            if hasattr(self, "user"):
                if (
                    affiliation := self.user.person.affiliations.filter(org=org)
                    .order_by("-pk")
                    .first()
                ):
                    email = affiliation.email
                    if email:
                        return email
        email = getattr(self, "email", None)
        if not email and (user := self.get_user()):
            email = (
                user and user.email or user and user.emailaddress_set.filter(primary=True).last()
            )
        return email


class EmailField(models.EmailField):
    def get_prep_value(self, value):
        if value:
            return value.lower()


class FixedCharField(models.Field):
    def __init__(self, *args, db_collation=None, **kwargs):
        self.length = kwargs.get("max_length")
        super().__init__(*args, **kwargs)
        self.db_collation = db_collation
        self.validators.append(validators.MaxLengthValidator(self.max_length))

    @property
    def description(self):
        return _("Fixed Length String (%(length)s)")

    def check(self, **kwargs):
        databases = kwargs.get("databases") or []
        return [
            *super().check(**kwargs),
            *self._check_db_collation(databases),
            *self._check_length_attribute(**kwargs),
        ]

    def _check_length_attribute(self, **kwargs):
        if not isinstance(self.length, int) or isinstance(self.length, bool) or self.length <= 0:
            return [
                checks.Error(
                    "'length' must be a positive integer.",
                    obj=self,
                    id="fields.E121",
                )
            ]
        else:
            return []

    def _check_db_collation(self, databases):
        errors = []
        for db in databases:
            if not router.allow_migrate_model(db, self.model):
                continue
            connection = connections[db]
            if not (
                self.db_collation is None
                or "supports_collation_on_charfield" in self.model._meta.required_db_features
                or connection.features.supports_collation_on_charfield
            ):
                errors.append(
                    checks.Error(
                        "%s does not support a database collation on "
                        "CharFields." % connection.display_name,
                        obj=self,
                        id="fields.E190",
                    ),
                )
        return errors

    def cast_db_type(self, connection):
        return f"char({self.length}" if self.length else f"char({self.max_length})"

    def db_parameters(self, connection):
        db_params = super().db_parameters(connection)
        db_params["collation"] = self.db_collation
        return db_params

    def get_internal_type(self):
        return "CharField"

    def to_python(self, value):
        if isinstance(value, str) or value is None:
            return value
        return str(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return self.to_python(value)

    def formfield(self, **kwargs):
        # Passing max_length to forms.CharField means that the value's length
        # will be validated twice. This is considered acceptable since we want
        # the value in the form field (to pass into widget for example).
        defaults = {"max_length": self.max_length}
        # TODO: Handle multiple backends with different feature flags.
        if self.null and not connection.features.interprets_empty_strings_as_nulls:
            defaults["empty_value"] = None
        defaults.update(kwargs)
        return super().formfield(**defaults)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.db_collation:
            kwargs["db_collation"] = self.db_collation
        return name, path, args, kwargs


# class SeparatedValuesField(CharField):

#     def __init__(self, *args, **kwargs):
#         self.token = kwargs.pop("token", ",")
#         super().__init__(*args, **kwargs)

#     def to_python(self, value):
#         if not value:
#             return
#         if isinstance(value, list):
#             return value
#         return value.split(self.token)

#     def get_db_prep_value(self, value):
#         if not value:
#             return
#         assert isinstance(value, list) or isinstance(value, tuple)
#         return self.token.join(value)

#     def value_to_string(self, obj):
#         value = self._get_val_from_obj(obj)
#         return self.get_db_prep_value(value)


class Title(Model):
    code = CharField(max_length=10, primary_key=True, blank=False)
    name = CharField(max_length=200, blank=False)

    def save(self, *args, **kwargs):
        if not self.code or not self.code.strip():
            code = (self.name[:10] or get_random_string(5)).strip().upper()
            for i in range(1, 10):
                if not self._meta.model.objects.filter(code=code).exists():
                    break
                code = f"{code[:9]}{i}"
            self.code = code
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        db_table = "title"
        ordering = ["code"]
        app_label = "portal"


def add_title_data(apps, schema_editor):
    """
    Add to the migrations:
    migrations.RunPython(common.models.add_title_data, lambda *args, **kwargs: None),
    """
    Title = apps.get_model("portal", "Title")
    db_alias = schema_editor.connection.alias

    Title.objects.using(db_alias).bulk_create(
        [Title(code=code, name=name, name_en=name) for (code, name) in TITLES],
        ignore_conflicts=True,
    )
