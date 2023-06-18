from allauth.account.models import EmailAddress
from django.contrib import admin, messages
from django.contrib.auth import admin as auth_admin
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F, Q
from django.shortcuts import render
from django.utils.translation import gettext as _
from simple_history.admin import SimpleHistoryAdmin

from portal.models import (
    Application,
    CurriculumVitae,
    Member,
    Nomination,
    Panellist,
    Profile,
    Referee,
    ResearchOffice,
)

from .forms import UserChangeForm, UserCreationForm

User = get_user_model()


def titled_filter(filter_class, title):
    class Wrapper(filter_class):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.title = title

    return Wrapper


@admin.register(User)
class UserAdmin(auth_admin.UserAdmin, SimpleHistoryAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    fieldsets = (
        (None, {"fields": ("username", "password", "orcid")}),
        (
            _("Personal info"),
            {
                "fields": (
                    "title",
                    "first_name",
                    "middle_names",
                    "last_name",
                    "email",
                )
            },
        ),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_approved",
                    "is_identity_verified",
                    "is_active",
                    "is_staff",
                    "staff_of_sites",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )

    list_display = [
        "username",
        "email",
        "full_name",
        "is_superuser",
        "date_joined",
    ]
    search_fields = [
        "email",
        "name",
        "username",
        "first_name",
        "last_name",
    ]
    list_filter = (
        "is_staff",
        "is_superuser",
        "is_active",
        (
            "research_offices__org",
            titled_filter(admin.RelatedOnlyFieldListFilter, "Research Office"),
        ),
    )

    class EmailAddressInline(admin.TabularInline):
        extra = 0
        model = EmailAddress

        # def view_on_site(self, obj):
        #     return reverse("admin:account_emailaddress_change", kwargs={"object_id": obj.pk})

    class ResearchOfficeInline(admin.TabularInline):
        extra = 0
        model = ResearchOffice
        view_on_site = False
        autocomplete_fields = ["org"]

    inlines = [EmailAddressInline, ResearchOfficeInline]

    actions = ["merge_users"]

    @admin.action(description="Merge Users")
    def merge_users(self, request, queryset):
        if "do_action" in request.POST:
            deleted = []
            errors = []
            if target_id := request.POST.get("target"):
                target = User.get(target_id)
                profile = Profile.where(user=target).first()

                for u in list(queryset.filter(~Q(id=target_id))):
                    try:
                        with transaction.atomic():
                            EmailAddress.objects.filter(user=u).update(
                                user=target, primary=(F("email") == target.email)
                            )
                            u.socialaccount_set.update(user=target)

                            Application.where(submitted_by=u).update(submitted_by=target)
                            Member.where(user=u).update(user=target)
                            Nomination.where(nominator=u).update(nominator=target)
                            Nomination.where(user=u).update(user=target)
                            Referee.where(user=u).update(user=target)
                            Panellist.where(user=u).update(user=target)
                            CurriculumVitae.where(owner=u).update(owner=target)

                            if p := Profile.where(user=u).first():
                                if profile:
                                    CurriculumVitae.where(profile=p).update(profile=profile)
                                else:
                                    CurriculumVitae.where(profile=p).delete()
                            Profile.where(user=u).delete()
                            u.delete()
                            deleted.append(u.username)
                    except Exception as ex:
                        errors.append(ex)

            if deleted:
                messages.success(
                    request, f'{len(deleted)} users merged and deleted: {", ".join(deleted)}'
                )
            if errors:
                messages.error(
                    request,
                    "Failed to merge all users:<ul>%s</ul>"
                    % "".join(f"<li>{e}</li>" for e in errors),
                )

            return

        return render(
            request,
            "action_merge_users.html",
            {
                "title": "Choose target user account",
                "objects": queryset,
                "users": queryset,
            },
        )
