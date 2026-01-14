from hashlib import md5
from urllib.parse import urlencode

from allauth.socialaccount.models import SocialAccount, SocialToken
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.contrib.sites.models import Site
from django.core import mail
from django.db.models import (
    DO_NOTHING,
    SET_NULL,
    BooleanField,
    CharField,
    DateTimeField,
    ForeignKey,
    ManyToManyField,
)
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from simple_history.models import HistoricalRecords

from common.models import HelperMixin, PersonMixin, Title


class User(HelperMixin, PersonMixin, AbstractUser):

    username_validator = UnicodeUsernameValidator()
    username = CharField(
        _("username"),
        max_length=150,
        unique=True,
        help_text=_("Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only."),
        validators=[username_validator],
        error_messages={
            "unique": _(
                "The username is already taken and not available. Please choose a different username."
            ),
        },
    )
    # title = CharField(max_length=40, null=True, blank=True, choices=TITLES)
    title = ForeignKey(
        Title,
        null=True,
        blank=True,
        verbose_name=_("title"),
        db_column="title",
        on_delete=DO_NOTHING,
    )
    middle_names = CharField(
        _("middle names"),
        blank=True,
        null=True,
        max_length=280,
        # help_text=_("Comma separated list of middle names"),
    )
    # First Name and Last Name do not cover name patterns
    # around the globe.
    name = CharField(_("Name of User"), blank=True, null=True, max_length=255)
    orcid = CharField("ORCID iD", blank=True, null=True, max_length=80)
    history = HistoricalRecords()
    is_approved = BooleanField(_("Is Approved"), default=False)

    is_identity_verified = BooleanField(null=True, blank=True)
    identity_verified_by = ForeignKey("self", null=True, blank=True, on_delete=SET_NULL)
    identity_verified_at = DateTimeField(null=True, blank=True)

    staff_of_sites = ManyToManyField(Site, blank=True, related_name="staff_users")
    registered_on = ForeignKey(
        Site,
        null=True,
        blank=True,
        related_name="registered_users",
        on_delete=SET_NULL,
        default=HelperMixin.get_current_site_id,
    )

    def __str__(self):
        return f"{super().__str__()} ({self.username})"

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.lower()

        super().save(*args, **kwargs)

    @cached_property
    @admin.display(description=_("staff status"), boolean=True)
    def is_site_staff(self):
        """Test if the user is staff of the current site"""
        # if not self.is_staff:
        #     return False
        return self.staff_of_sites.through.objects.filter(
            site_id=self.current_site_id, user=self
        ).exists()

    @cached_property
    @admin.display(description=_("is admin"), boolean=True)
    def is_admin(self):
        """Test if the user is staff member or superuser"""
        return self.is_superuser or self.is_staff or self.is_site_staff

    @cached_property
    @admin.display(description=_("is R.O."), boolean=True)
    def is_ro(self):
        return self.research_offices.exists()

    @property
    def can_apply(self):
        """Admin nor staff cannot apply nor nominate other user."""
        return not self.is_superuser and not self.is_site_staff

    @cached_property
    def needs_identity_verification(self):
        return not (
            self.is_identity_verified
            or self.identity_verifications.filter(state="accepted").exists()
        )

    def get_absolute_url(self):
        return reverse("users:detail", kwargs={"username": self.username})

    def in_group(self, group_name):
        return self.groups.filter(name=group_name).exists()

    # @property
    # def full_name(self):
    #     return self.get_full_name()

    @property
    def full_name_with_email(self):
        return f"{self.full_name} ({self.email})"

    @property
    def is_applicant(self):
        return self.in_group("APPLICANT")

    @property
    def is_nominator(self):
        return self.in_group("NOMINATOR")

    @property
    def is_referee(self):
        return self.in_group("REFEREE")

    def get_orcid(self):
        """find user ORCID value."""
        orcid = self.orcid
        if not orcid and (sa := SocialAccount.objects.filter(user=self, provider="orcid").last()):
            orcid = sa.uid
        if not orcid and (
            ppi := self.person.person_identifiers.filter(code_id="02", person__user=self).last()
        ):
            orcid = ppi.value
        return orcid

    @property
    def orcid_access_token(self):
        """
        Get the user ORCID token and if ORCID ID is not set or
        is different update it.
        """
        social_accounts = self.socialaccount_set.all()
        for sa in social_accounts:
            if sa.provider == "orcid":
                orcid_id = sa.uid
                access_token = SocialToken.objects.get(
                    account__user=self, account__provider=sa.provider
                )
                if not access_token:
                    return
                if not self.orcid or self.orcid != orcid_id:
                    self.orcid = orcid_id
                    self.save()

                return access_token

    @property
    def has_orcid_account(self):
        return self.socialaccount_set.all().filter(provider="orcid").exists()

    @property
    def has_rapidconnect_account(self):
        return self.socialaccount_set.all().filter(provider="rapidconnect").exists()

    @cached_property
    def avatar(self):
        return self.image_url(size=38)

    def image_url(self, size=None, default="identicon"):
        """Return user image link or Gravatar service user avatar URL."""
        sa = self.socialaccount_set.filter(provider="google").first()
        if not (sa and (url := sa.extra_data.get("picture"))):
            # default = "https://www.example.com/default.jpg"
            url = (
                "https://www.gravatar.com/avatar/"
                + md5(self.email.lower().encode()).hexdigest()
                + "?"
            )
            queries = dict(d=default)
            if size:
                queries["s"] = str(size)
            url += urlencode(queries)
        return url

    @cached_property
    def email_addresses(self):
        """All user email addresses"""
        # return [self.email, *(r[0] for r in self.emailaddress_set.values_list("email"))]
        return [r for r, in self.emailaddress_set.values_list("email__lower")]

    def email_user(self, subject, message, from_email=None, **kwargs):
        """Send an email to this user."""
        mail.send_mail(subject, message, from_email, [self.email], **kwargs)

    def natural_key(self):
        return self.username
