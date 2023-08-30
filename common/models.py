from django.conf import settings
from django.db import models
from django.db.models import DateTimeField
from django.db.models import Model as Base
from django.urls import reverse
from model_utils import Choices

SEX_CHOICES = Choices("female", "male", "other")

ETHNICITY_COICES = Choices(
    "European",
    "Maori",
    "Chinese",
    "Indian",
    "Samoan",
    "Tongan",
    "Cook Islands Maori",
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
        return reverse(self._meta.db_table.replace("_", "-"), args=[str(self.id)])

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

    @property
    def full_name(self):
        user = self.get_user()
        first_name = getattr(self, "first_name", None) or user and user.first_name
        middle_names = getattr(self, "middle_names", None) or user and user.middle_names
        last_name = getattr(self, "last_name", None) or user and user.last_name
        full_name = " ".join(s for s in [first_name, middle_names, last_name] if s)
        if hasattr(self, "title") and self.title:
            full_name = f"{self.title} {full_name}"
        return full_name or user and user.username or self.email

    @property
    def full_name_with_email(self):
        user = self.get_user()
        email = getattr(self, "email", None) or user and user.email
        if (full_name := self.full_name):
            return f"{full_name} ({email})"
        else:
            return email

    @property
    def full_email_address(self):
        user = self.get_user()
        email = getattr(self, "email", None) or user.email
        if full_name := self.full_name:
            return f'"{full_name}" <{email}>'
        return email

    def __str__(self):
        return self.full_name


class EmailField(models.EmailField):
    def get_prep_value(self, value):
        if value:
            return value.lower()
