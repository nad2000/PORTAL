import copy
import base64
from django.conf import settings
from django.contrib.sites.models import Site
from django.core import checks, validators
from django.db import connection, connections, models, router
from django.db.models import CharField, DateTimeField, EmailField, ForeignObjectRel
from django.db.models import Model as Base
from django.db.models.functions import Lower
from django.urls import reverse
from django.utils.functional import cached_property
from model_utils import Choices
from django.shortcuts import get_object_or_404
from django.utils import timezone

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


class TimeStampMixin(Base):
    # created_at = DateTimeField(auto_now_add=True, null=True)
    created_at = DateTimeField(null=True, default=timezone.now, editable=False)
    updated_at = DateTimeField(auto_now=True, null=True)

    class Meta:
        abstract = True


class HelperMixin:

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

    @property
    def thread_index(self):
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
        return cls.objects.bulk_create(*args, **kwargs)

    @classmethod
    def get_or_create(cls, defaults=None, **kwargs):
        if o := cls.objects.filter(**kwargs).order_by("-pk").first():
            return o, False
        return cls.objects.get_or_create(defaults, **kwargs)

    @classmethod
    def where(cls, *args, **kwargs):
        return cls.objects.filter(*args, **kwargs)

    @property
    def admin_url(self):
        return reverse(
            f"admin:{self._meta.app_label}_{self._meta.model_name}_change", args=[str(self.id)]
        )


class Model(TimeStampMixin, HelperMixin, Base):
    # TODO: figure out how to make generic table naming:
    # history = HistoricalRecords(inherit=True)

    @property
    def model_name(self):
        return self._meta.model_name

    @property
    def detail_url(self):
        model_name_slug = self._meta.db_table.replace("_", "-")
        try:
            return reverse(f"{model_name_slug}-detail", args=[str(self.number)])
        except:
            try:
                return reverse(f"{model_name_slug}-detail", args=[str(self.code)])
            except:
                return reverse(model_name_slug, args=[str(self.pk)])

    def get_full_detail_url(self, request=None):
        url = self.detail_url
        if url:
            if request:
                url = request.build_absolute_uri(url)
            else:
                site = Site.objects.get_current()
                url = f"https://{site.domain}{url}"
            return domain_to_macrons(url)

    def get_absolute_url(self):
        model_name_slug = self._meta.db_table.replace("_", "-")
        try:
            return reverse(model_name_slug, args=[str(self.id)])
        except:
            try:
                return reverse(f"{model_name_slug}-detail", args=[str(self.id)])
            except:
                return reverse(f"{model_name_slug}-list")

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
        elif email:
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
        if not self.code or not self.cone.strip():
            self.code = self.name[:10].upper()
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
