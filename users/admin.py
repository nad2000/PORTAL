from allauth.account.models import EmailAddress
from django.contrib import admin, messages
from django.contrib.auth import admin as auth_admin
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F, Q
from django.db.models.deletion import get_candidate_relations_to_delete
from django.shortcuts import render
from django.utils.translation import gettext as _
from simple_history.admin import SimpleHistoryAdmin
from simple_history.models import HistoricalChanges
from simple_history.utils import bulk_update_with_history
from sentry_sdk import capture_exception

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
    search_help_text = "username, name, first name, last name, or email"
    list_filter = (
        "is_staff",
        "is_superuser",
        "is_active",
        (
            "research_offices__org",
            titled_filter(admin.RelatedOnlyFieldListFilter, "Research Office"),
        ),
        "date_joined",
    )
    date_hierarchy = "date_joined"

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
                profile = Profile.where(user=target).first()
                users = queryset.filter(~Q(id=target_id))
                object_ids = [u.id for u in users]
                profiles = Profile.where(user_id__in=object_ids)
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

                #             if p := Profile.where(user=u).first():
                #                 if profile:
                #                     CurriculumVitae.where(profile=p).update(profile=profile)
                #                 else:
                #                     CurriculumVitae.where(profile=p).delete()
                #             Profile.where(user=u).delete()
                #             u.delete()
                #             deleted.append(u.username)
                #     except Exception as ex:
                #         errors.append(ex)
                try:
                    with transaction.atomic():
                        for u_id in object_ids:
                            p = Profile.where(user_id=u_id).first()
                            if p:
                                if profile:
                                    for cv in CurriculumVitae.where(profile=p):
                                        cv.profile = profile
                                        cv._change_reason = (
                                            f"User {p.user} merged into {target} by {u}"
                                        )
                                        cv.save()
                                else:
                                    for cv in CurriculumVitae.where(profile=p):
                                        cv.profile = profile
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
                                    for rel in get_candidate_relations_to_delete(Profile._meta)
                                    if not issubclass(rel.related_model, HistoricalChanges)
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
                                    getattr(
                                        model, "all_objects", model._default_manager
                                    ).bulk_update(objects, [field])
                            else:
                                for model, field in (
                                    (rel.related_model, rel.remote_field.name)
                                    for rel in get_candidate_relations_to_delete(Profile._meta)
                                    if not issubclass(rel.related_model, HistoricalChanges)
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
                                            f"User {o.profile.user} merged into {target} by {u}"
                                        )
                                        o.delete()
                                    deleted = [f"{o.profile}" for o in to_delete]

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

                        for o in users:
                            o._change_reason = f"User {o} merged into {target} by {u}"
                            o.delete()
                        deleted.extend([f"{o}" for o in users])
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
