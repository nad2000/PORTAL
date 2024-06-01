from django.conf import settings
from django.core import checks, validators
from django.db import connection, connections, models, router
from django.db.models import CharField, DateTimeField
from django.db.models import Model as Base
from django.urls import reverse
from django.utils.functional import cached_property
from model_utils import Choices

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


class TimeStampMixin(Base):
    created_at = DateTimeField(auto_now_add=True, null=True)
    updated_at = DateTimeField(auto_now=True, null=True)

    class Meta:
        abstract = True


class HelperMixin:
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
    def get_or_create(cls, defaults=None, **kwargs):
        return cls.objects.get_or_create(defaults, **kwargs)

    @classmethod
    def where(cls, *args, **kwargs):
        return cls.objects.filter(*args, **kwargs)


class Model(TimeStampMixin, HelperMixin, Base):
    # TODO: figure out how to make generic table naming:
    # history = HistoricalRecords(inherit=True)

    def get_absolute_url(self):
        model_name_slug = self._meta.db_table.replace("_", "-")
        try:
            return reverse(model_name_slug, args=[str(self.id)])
        except:
            return reverse(f"{model_name_slug}-detail", args=[str(self.id)])

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

    @cached_property
    def full_name(self):
        user = self.get_user()
        first_name = getattr(self, "first_name", None) or user and user.first_name
        middle_names = getattr(self, "middle_names", None) or user and user.middle_names
        last_name = getattr(self, "last_name", None) or user and user.last_name
        full_name = " ".join(s for s in [first_name, middle_names, last_name] if s)
        if hasattr(self, "title") and self.title:
            full_name = f"{self.title} {full_name}"
        return full_name.strip() or user and user.username or self.email

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
