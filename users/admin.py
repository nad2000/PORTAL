from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.filters import SimpleListFilter
from django.contrib.auth import admin as auth_admin
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.db.models.deletion import get_candidate_relations_to_delete
from django.shortcuts import render
from django.utils.translation import gettext as _
from sentry_sdk import capture_exception
from simple_history.admin import SimpleHistoryAdmin
from simple_history.models import HistoricalChanges
from simple_history.utils import bulk_update_with_history

from portal.models import (
    CurriculumVitae,
    Person,
    ResearchOffice,
    PersonProtectionPattern,
    ProtectionPatternPerson,
)


from .forms import UserChangeForm, UserCreationForm

User = get_user_model()


def titled_filter(filter_class, title):
    class Wrapper(filter_class):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.title = title

    return Wrapper


class IsStaff(SimpleListFilter):
    title = "staff status"
    parameter_name = "is_staff"

    def lookups(self, request, model_admin):
        return (("Yes", True), ("No", False))

    def queryset(self, request, queryset):
        if self.value():
            # If is_paid=True filter is activated
            return queryset.filter(staff_of_sites__site=settings.SITE_ID)
        else:
            # If is_paid=True filter is activated
            return queryset.filter(
                Q(staff_of_sites__isnull=True) | ~Q(staff_of_sites=settings.SITE_ID)
            ).distinct()


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
                    "is_site_staff",
                    "staff_of_sites",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    readonly_fields = ["is_site_staff"]

    list_display = [
        "username",
        "email",
        "full_name",
        "is_superuser",
        "date_joined",
        "is_site_staff",
    ]
    search_fields = [
        "email",
        "name",
        "username",
        "first_name",
        "last_name",
        "orcid",
        "emailaddress__email",
    ]
    search_help_text = "username, name, first name, last name, or email"
    list_filter = (
        # "is_staff",
        # IsStaff,
        "is_superuser",
        "is_active",
        (
            "research_offices__org",
            titled_filter(admin.RelatedOnlyFieldListFilter, "Research Office"),
        ),
        "date_joined",
    )
    date_hierarchy = "date_joined"

    def is_site_staff(self, obj):
        return obj.is_site_staff

    is_site_staff.description = "Designates whether the user can log into this admin site."
    is_site_staff.boolean = True

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
            u = request.user
            if target_id := request.POST.get("target"):
                target = User.get(target_id)
                profile = Person.where(user=target).first()
                users = queryset.filter(~Q(id=target_id))
                object_ids = [u.id for u in users]
                profiles = Person.where(user_id__in=object_ids)
                profile_ids = [p.id for p in profiles]

                # for u in list(queryset.filter(~Q(id=target_id))):
                #     try:
                #         with transaction.atomic():
                #             EmailAddress.objects.filter(user=u).update(
                #                 user=target, primary=(F("email") == target.email)
                #             )
                #             u.socialaccount_set.update(user=target)

                #             Application.where(submitted_by=u).update(submitted_by=target)
                #             Member.where(user=u).update(user=target)
                #             Nomination.where(nominator=u).update(nominator=target)
                #             Nomination.where(user=u).update(user=target)
                #             Referee.where(user=u).update(user=target)
                #             Panellist.where(user=u).update(user=target)
                #             CurriculumVitae.where(owner=u).update(owner=target)
                #             ResearchOffice.where(user=u).update(user=target)

                #             if p := Person.where(user=u).first():
                #                 if profile:
                #                     CurriculumVitae.where(profile=p).update(profile=profile)
                #                 else:
                #                     CurriculumVitae.where(profile=p).delete()
                #             Person.where(user=u).delete()
                #             u.delete()
                #             deleted.append(u.username)
                #     except Exception as ex:
                #         errors.append(ex)
                try:
                    with transaction.atomic():
                        for u_id in object_ids:
                            p = Person.where(user_id=u_id).first()
                            if p:
                                if profile:
                                    for cv in CurriculumVitae.where(person=p):
                                        cv.person = profile
                                        cv._change_reason = (
                                            f"User {p.user} merged into {target} by {u}"
                                        )
                                        cv.save()
                                else:
                                    for cv in CurriculumVitae.where(person=p):
                                        cv.person = profile
                                        cv._change_reason = (
                                            f"User {p.user} merged into {target} by {u}"
                                        )
                                        cv.delete()

                        if profile:
                            for model, field, objects in (
                                (
                                    model,
                                    field,
                                    [
                                        setattr(
                                            o,
                                            "_change_reason",
                                            f"User {getattr(o, field)} merged into {profile} by {u}",
                                        )
                                        or setattr(o, field, profile)
                                        or o
                                        for o in (
                                            model.all_objects
                                            if hasattr(model, "all_objects")
                                            else model.objects
                                        ).filter(**{f"{field}__in": profile_ids})
                                    ],
                                )
                                for (model, field) in (
                                    (rel.related_model, rel.remote_field.name)
                                    for rel in get_candidate_relations_to_delete(Person._meta)
                                    if not issubclass(
                                        rel.related_model,
                                        (
                                            HistoricalChanges,
                                            ProtectionPatternPerson,
                                        ),
                                    )
                                )
                            ):
                                if hasattr(model, "history"):
                                    bulk_update_with_history(
                                        objects,
                                        model,
                                        [field],
                                        default_user=u,
                                        manager=getattr(
                                            model, "all_objects", model._default_manager
                                        ).filter(**{f"{field}__in": profile_ids}),
                                    )
                                else:
                                    if model is PersonProtectionPattern:
                                        objects = [
                                            o
                                            for o in objects
                                            if not profile.person_protection_patterns.filter(
                                                protection_pattern=o.protection_pattern
                                            ).exists()
                                        ]
                                    elif model.__name__ == "Person_ethnicities":
                                        objects = [
                                            o
                                            for o in objects
                                            if not profile.ethnicities.filter(
                                                code=o.ethnicity.code
                                            ).exists()
                                        ]
                                    elif model.__name__ == "Person_languages_spoken":
                                        objects = [
                                            o
                                            for o in objects
                                            if not profile.languages_spoken.filter(
                                                code=o.language.code
                                            ).exists()
                                        ]
                                    elif model.__name__ == "Person_iwi_groups":
                                        breakpoint()
                                        objects = [
                                            o
                                            for o in objects
                                            if not profile.iwi_groups.filter(
                                                code=o.iwigroup.code
                                            ).exists()
                                        ]
                                    # elif model.__name__.startswith("Person_"):
                                    #     breakpoint()
                                    if objects:
                                        getattr(
                                            model, "all_objects", model._default_manager
                                        ).bulk_update(objects, [field])
                            else:
                                for model, field in (
                                    (rel.related_model, rel.remote_field.name)
                                    for rel in get_candidate_relations_to_delete(Person._meta)
                                    if not issubclass(
                                        rel.related_model,
                                        (HistoricalChanges, ProtectionPatternPerson),
                                    )
                                ):
                                    to_delete = list(
                                        (
                                            model.all_objects
                                            if hasattr(model, "all_objects")
                                            else model.objects
                                        ).filter(**{f"{field}__in": profile_ids})
                                    )
                                    for o in to_delete:
                                        o._change_reason = (
                                            f"User {o.person.user} merged into {target} by {u}"
                                        )
                                        o.delete()
                                    deleted = [f"{o.person}" for o in to_delete]

                        for o in Person.where(user_id__in=object_ids):
                            o._change_reason = f"User {o} merged into {target} by {u}"
                            o.delete()

                        for model, field, objects in (
                            (
                                model,
                                field,
                                [
                                    setattr(
                                        o,
                                        "_change_reason",
                                        f"User {getattr(o, field)} merged into {target} by {u}",
                                    )
                                    or setattr(o, field, target)
                                    or o
                                    for o in (
                                        model.all_objects
                                        if hasattr(model, "all_objects")
                                        else model.objects
                                    ).filter(**{f"{field}__in": object_ids})
                                ],
                            )
                            for (model, field) in (
                                (rel.related_model, rel.remote_field.name)
                                for rel in get_candidate_relations_to_delete(User._meta)
                                if not issubclass(rel.related_model, HistoricalChanges)
                                and rel.related_model is not User.staff_of_sites.through
                            )
                        ):
                            if hasattr(model, "history"):
                                bulk_update_with_history(
                                    objects,
                                    model,
                                    [field],
                                    default_user=u,
                                    manager=getattr(model, "all_objects", model._default_manager),
                                )
                            else:
                                getattr(model, "all_objects", model._default_manager).bulk_update(
                                    objects, [field]
                                )

                        deleted.extend([f"{o}" for o in users])
                        for o in users:
                            o._change_reason = f"User {o} merged into {target} by {u}"
                            o.delete()
                except Exception as ex:
                    capture_exception(ex)
                    errors.append(ex)

            if deleted:
                messages.success(
                    request,
                    f'{len(deleted)} user(s) merged and deleted: {", ".join(deleted)}',
                )
            if errors:
                for e in errors:
                    messages.error(request, e)
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
