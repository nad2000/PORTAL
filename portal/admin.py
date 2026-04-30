import os
import re
from functools import cache
import inspect
from django.contrib.contenttypes.admin import GenericTabularInline
from allauth.account.adapter import get_adapter
from dateutil.relativedelta import relativedelta

import dal
import django
import djhacker
import modeltranslation
from admin_ordering.admin import OrderableAdmin
from allauth.socialaccount.admin import SocialAccountAdmin, SocialTokenAdmin
from allauth.socialaccount.models import SocialAccount, SocialToken
from dal import autocomplete
from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.contrib.admin.widgets import SELECT2_TRANSLATIONS
from django.contrib.flatpages.admin import FlatPageAdmin
from django.contrib.flatpages.models import FlatPage
from django.db import transaction
from django.db.models import F, Q, Count
from django.db.models.deletion import get_candidate_relations_to_delete
from django.shortcuts import render, reverse, redirect
from django.urls import NoReverseMatch
from django.utils import timezone
from django.utils.datastructures import OrderedSet
from django.utils.html import format_html, html_safe
from django.utils.safestring import mark_safe
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _
from django_fsm_log.admin import StateLogInline
from django_summernote.admin import SummernoteModelAdminMixin

from easyaudit import admin as easyaudit_admin
from easyaudit.models import CRUDEvent, LoginEvent, RequestEvent
from fsm_admin.mixins import FSMTransitionMixin
from import_export import fields
from import_export.admin import (
    ExportActionMixin,
    ImportExportMixin,
    ImportExportModelAdmin,
)
from import_export.resources import ModelResource
from import_export.widgets import ForeignKeyWidget
from modeltranslation.admin import TranslationAdmin
from rest_framework.authtoken.models import Token
from sentry_sdk import capture_exception
from simple_history.admin import SimpleHistoryAdmin
from simple_history.models import HistoricalChanges
from simple_history.utils import bulk_create_with_history, bulk_update_with_history

from . import filters, models
from .forms import ModelSelect2NoPK
from common.admin import StaffPermsMixin

# from dalf.admin import DALFModelAdmin, DALFRelatedOnlyField, DALFRelatedFieldAjax
# from autocompletefilter.admin import AutocompleteFilterMixin
# from autocompletefilter.filters import AutocompleteListFilter


djhacker.formfield(
    models.Organisation.signatory,
    forms.ModelChoiceField,
    widget=autocomplete.ModelSelect2(
        url="person-autocomplete",
        forward=[
            dal.forward.Const("EMP", "affiliation_type"),
            dal.forward.Field("code", "org_code"),
        ],
    ),
)


class OrgChoiceField(forms.ModelChoiceField):

    def label_from_instance(self, obj):
        return f" {obj.code}: {obj.name}"


djhacker.formfield(
    models.Affiliation.org,
    OrgChoiceField,
    widget=autocomplete.ModelSelect2(url="org-autocomplete"),
)


# djhacker.formfield(
#     CRUDEvent.user,
#     forms.ModelChoiceField,
#     widget=autocomplete.ModelSelect2(url="user-autocomplete"),
# )

djhacker.formfield(
    Token.user,
    forms.ModelChoiceField,
    widget=autocomplete.ModelSelect2(url="user-autocomplete"),
)


# djhacker.formfield(
#     LoginEvent.user,
#     forms.ModelChoiceField,
#     widget=autocomplete.ModelSelect2(url="user-autocomplete"),
# )


# djhacker.formfield(
#     RequestEvent.user,
#     forms.ModelChoiceField,
#     widget=autocomplete.ModelSelect2(url="user-autocomplete"),
# )

djhacker.formfield(
    models.Panellist.user,
    forms.ModelChoiceField,
    widget=autocomplete.ModelSelect2(url="user-autocomplete"),
)

djhacker.formfield(
    SocialAccount.user,
    forms.ModelChoiceField,
    widget=autocomplete.ModelSelect2(url="user-autocomplete"),
)

# for m in [models.Round, models.Application, models.Contract, models.Report]:
#     m.priorities.field = lambda: m.prioritie
#     djhacker.formfield(
#         m.priorities,
#         forms.ModelMultipleChoiceField,
#         widget=autocomplete.ModelSelect2Multiple(
#             url="research-priority-autocomplete",
#             forward=[
#                 dal.forward.Field("round", "round"),
#                 dal.forward.Field("application", "application"),
#                 dal.forward.Field("contract", "contract"),
#                 # dal.forward.Const(m.model_name(), "model"),
#             ],
#         ),
#     )

djhacker.formfield(
    models.ApplicationDocument.required_document,
    forms.ModelChoiceField,
    widget=autocomplete.ModelSelect2(
        url="required-document-autocomplete",
        forward=[
            dal.forward.Field("round", "round"),
            dal.forward.Field("scheme", "scheme"),
        ],
    ),
)

djhacker.formfield(
    models.RoundDocumentTemplate.document_type,
    forms.ModelChoiceField,
    widget=autocomplete.ModelSelect2(
        url="document-type-autocomplete",
        forward=[
            dal.forward.Field("scheme", "scheme"),
        ],
    ),
)

djhacker.formfield(
    models.RoundDocumentTemplate.required_document,
    forms.ModelChoiceField,
    widget=autocomplete.ModelSelect2(
        url="required-document-autocomplete",
        forward=[
            dal.forward.Field("scheme", "scheme"),
            dal.forward.Field("round", "round"),
        ],
    ),
)

djhacker.formfield(
    models.Report.schedule_entry,
    forms.ModelChoiceField,
    widget=autocomplete.ModelSelect2(
        url="reporting-schedule-entry-autocomplete",
        forward=[
            dal.forward.Field("contract", "contract"),
            dal.forward.Const("1", "exclude_taken"),
        ],
    ),
)

djhacker.formfield(
    models.RequiredContractDocument.application_required_document,
    forms.ModelChoiceField,
    widget=autocomplete.ModelSelect2(
        url="required-document-autocomplete",
        forward=[
            dal.forward.Field("round", "round"),
            # dal.forward.Field("contract", "contract"),
            # dal.forward.Const("1", "exclude_taken"),
        ],
    ),
)

djhacker.formfield(
    models.ChangeRequest.types,
    forms.ModelMultipleChoiceField,
    widget=autocomplete.ModelSelect2Multiple(url="change-type-autocomplete"),
)


djhacker.formfield(
    models.ChangeRequest.categories,
    forms.ModelMultipleChoiceField,
    widget=autocomplete.ModelSelect2Multiple(
        url="change-category-autocomplete",
        forward=[
            dal.forward.Field("types", "types"),
            dal.forward.Const("1", "level"),
        ],
    ),
)


djhacker.formfield(
    models.ChangeRequest.subcategories,
    forms.ModelMultipleChoiceField,
    widget=autocomplete.ModelSelect2Multiple(
        url="change-category-autocomplete",
        forward=[
            dal.forward.Field("types", "types"),
            "categories",
            dal.forward.Const("2", "level"),
        ],
    ),
)


# djhacker.formfield(
#     models.Person.code,
#     forms.ChoiceField,
#     widget=ModelSelect2NoPK(url="person-code-autocomplete"),
# )

# categories=autocomplete.ModelSelect2Multiple(
#     url="change-category-autocomplete",
#     forward=[
#         "types",
#         forward.Const("1", "level"),
#     ],
# ),
# subcategories=autocomplete.ModelSelect2Multiple(
#     url="change-category-autocomplete",
#     forward=[
#         "types",
#         "categories",
#         forward.Const("2", "level"),
#     ],
# ),
# types=autocomplete.ModelSelect2Multiple(url="change-type-autocomplete"),

# class QueryField(forms.ChoiceField):

#     def __init__(self, *args, **kwargs):
#         kwargs.pop("max_length", None)
#         kwargs.pop("empty_value", None)
#         super().__init__(*args, **kwargs)


# djhacker.formfield(
#     models.Address.city,
#     QueryField,
#     widget=autocomplete.ModelSelect2(
#         url="city-autocomplete",
#         forward=[dal.forward.Field("county", "county")],
#     ),
#     # queryset=models.Address.objects.none(),
# )

admin.site.site_url = "/start"
admin.site.site_header = _("Portal Administration")
admin.site.site_title = _("Portal Administration")
admin.site.index_title = _("Portal Administration")


# class RFDAModelAdminMixin:
#     def get_form(self, request, obj=None, change=False, **kwargs):
#         form = super().get_form(request, obj=obj, change=change, **kwargs)
#         for f in form.base_fields.values():
#             if f.help_text:
#                 f.widget.attrs.update({"placeholder": f.help_text, "title": f.help_text})
#         return form

#     @property
#     def media(self):
#         return super().media + forms.Media(
#             css={"screen": ["//code.jquery.com/ui/1.13.2/themes/base/jquery-ui.css"]},
#             js=["https://code.jquery.com/ui/1.13.2/jquery-ui.js"],
#         )

# class ModelAdmin(RFDAModelAdminMixin, admin.ModelAdmin):
#     pass


@html_safe
class JSPath:
    def __str__(self):
        return (
            '<script src="https://code.jquery.com/ui/1.13.2/jquery-ui.min.js" '
            'integrity="sha256-lSjKY0/srUM9BE3dPm+c4fBo1dky2v27Gdjm2uoZaL0=" '
            'crossorigin="anonymous"></script>'
        )


class FSMTransitionMixin(FSMTransitionMixin):
    class Media:
        # css = {"all": ("//code.jquery.com/ui/1.13.2/themes/smoothness/jquery-ui.css",)}
        # css = {"all": ("//code.jquery.com/ui/1.13.2/themes/cupertino/jquery-ui.css",)}
        # css = {"all": ("//code.jquery.com/ui/1.13.2/themes/redmond/jquery-ui.css",)}
        css = {"all": ("//code.jquery.com/ui/1.13.2/themes/blitzer/jquery-ui.css",)}
        # js = ("//code.jquery.com/ui/1.10.4/jquery-ui.js",)
        js = (JSPath(),)


class AutocompleteFilterMixin:
    @property
    def media(self):
        media = super().media

        i18n_file = None
        i18n_name = SELECT2_TRANSLATIONS.get(get_language(), None)
        if i18n_name:
            i18n_file = "admin/js/vendor/select2/i18n/%s.js" % i18n_name

        extra_js = [
            "admin/js/vendor/jquery/jquery.js",
            "admin/js/vendor/select2/select2.full.js",
        ]
        if i18n_file:
            extra_js.append(i18n_file)
        extra_js.extend(
            [
                "admin/js/jquery.init.js",
                "admin/js/autocomplete.js",
                # "admin/js/autocomplete_filter.js",  #  moved to the change_list.html
            ]
        )
        extra_css = [
            "admin/css/vendor/select2/select2.css",
            "admin/css/autocomplete.css",
        ]
        if django.VERSION >= (2, 2, 0, "final", 0):
            media._js_lists.append(extra_js)
            media._css_lists.append({"screen": extra_css})
        else:
            media._js = OrderedSet(extra_js + media._js)
            media._css.setdefault("screen", [])
            media._css["screen"].extend(extra_css)
        return media


class InlineNoteForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        if self.request and not self.instance.pk:
            self.fields["author"].initial = self.request.user

    class Meta:
        model = models.Note
        fields = "__all__"


class NoteInline(GenericTabularInline):
    model = models.Note
    form = InlineNoteForm
    extra = 1
    view_on_site = False
    readonly_fields = (
        "created_at",
        "updated_at",
        "author",
        # "date",
    )
    # fields = ("topic", "date", "content", "public", "author")
    fields = ("content", "author")
    can_delete = True
    show_change_link = True


admin.site.register(models.Note)


class StateLogInline(StateLogInline):
    classes = ["collapse"]


class UnaccentMixin:

    def get_search_fields(self, request):
        sf = super().get_search_fields(request)
        if settings.ENV == "prod":
            return ["_name" in f and f.replace("_name", "_name__unaccent") or f for f in sf]
        return sf


class CRUDEventAdmin(AutocompleteFilterMixin, easyaudit_admin.CRUDEventAdmin):

    autocomplete_fields = ["user"]

    list_filter = [
        "event_type",
        ("content_type", admin.RelatedOnlyFieldListFilter),
        # ("user", RelatedOnlyFieldListFilter),
        ("user", filters.AutocompleteListFilter),
        "datetime",
    ]


# # Re-register CRUDEventAdmin
admin.site.unregister(easyaudit_admin.CRUDEvent)
admin.site.register(CRUDEvent, CRUDEventAdmin)


class RequestEventAdmin(AutocompleteFilterMixin, easyaudit_admin.RequestEventAdmin):

    # list_filter = REQUEST_EVENT_LIST_FILTER
    list_filter = [
        "method",
        ("user", filters.AutocompleteListFilter),
        "datetime",
    ]


# Re-register CRUDEventAdmin
admin.site.unregister(easyaudit_admin.RequestEvent)
admin.site.register(RequestEvent, RequestEventAdmin)


class LoginEventAdmin(AutocompleteFilterMixin, easyaudit_admin.LoginEventAdmin):

    # list_filter = LOGIN_EVENT_LIST_FILTER
    list_filter = [
        "login_type",
        ("user", filters.AutocompleteListFilter),
        "datetime",
    ]


# Re-register CRUDEventAdmin
admin.site.unregister(easyaudit_admin.LoginEvent)
admin.site.register(LoginEvent, LoginEventAdmin)


class CurrentSiteRelatedListFilter(admin.RelatedFieldListFilter):
    def choices(self, changelist):
        for pk_val, val in self.lookup_choices:
            yield {
                "selected": self.lookup_val == str(pk_val)
                or (not self.lookup_val and pk_val == settings.SITE_ID),
                "query_string": changelist.get_query_string(
                    {self.lookup_kwarg: pk_val}, [self.lookup_kwarg_isnull]
                ),
                "display": val,
            }
        if self.include_empty_choice:
            yield {
                "selected": bool(self.lookup_val_isnull),
                "query_string": changelist.get_query_string(
                    {self.lookup_kwarg_isnull: "True"}, [self.lookup_kwarg]
                ),
                "display": self.empty_value_display,
            }

    def queryset(self, request, queryset):
        q = super().queryset(request, queryset)
        if "sites__id__exact" not in self.used_parameters:
            return q.filter(sites__id__exact=settings.SITE_ID)
        return q


class FlatPageAdmin(SummernoteModelAdminMixin, FlatPageAdmin):
    summernote_fields = ("content",)
    fieldsets = (
        (None, {"fields": ("url", "title", "content", "sites")}),
        (
            _("Advanced options"),
            {
                "classes": ("collapse",),
                "fields": (
                    "enable_comments",
                    "registration_required",
                    "template_name",
                ),
            },
        ),
    )
    list_filter = (("sites", CurrentSiteRelatedListFilter), "registration_required")

    def view_on_site(self, obj):
        return reverse("flatpage", kwargs={"url": obj.url[1:]})


# Re-register FlatPageAdmin
admin.site.unregister(FlatPage)
admin.site.register(FlatPage, FlatPageAdmin)


class SocialTokenAdmin(SocialTokenAdmin):
    search_fields = [
        "account__user__username",
        "account__user__email",
    ]
    ordering = ["-id"]


admin.site.unregister(SocialToken)
admin.site.register(SocialToken, SocialTokenAdmin)


class SocialAccountAdmin(SocialAccountAdmin):

    search_fields = ["uid"]
    raw_id_fields = ()
    date_hierarchy = "date_joined"

    def get_search_fields(self, request):
        search_fields = super().get_search_fields(request)
        return search_fields + self.search_fields


admin.site.unregister(SocialAccount)
admin.site.register(SocialAccount, SocialAccountAdmin)


class PdfFileAdminMixin:
    """Mixin for handling attached file update and conversion to a PDF copy."""

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if change and "file" in form.changed_data and obj.file:
            try:
                if cf := obj.update_converted_file():
                    obj.save()
                    messages.success(
                        request,
                        format_html(
                            (
                                "The attachment was converted into PDF file. "
                                "Please review the converted file version <a href='%s'>%s</a>."
                            )
                            % (cf.file.url, os.path.basename(cf.file.name))
                        ),
                    )

            except:
                messages.error(
                    request,
                    (
                        "Failed to convert the attachment form into PDF. "
                        "Please save your attachment  into PDF format and try to upload it again."
                    ),
                )
                raise


# class StaffPermsMixin:
#     def get_model_perms(self, request):
#         if (u := request.user) and u.is_active and (u.is_superuser or u.is_staff):
#             return {"add": True, "change": True, "delete": True, "view": True}
#         return super().get_model_perms(request)
#
#     def has_add_permission(self, request, *args):
#         if (u := request.user) and u.is_active and (u.is_superuser or u.is_staff):
#             return True
#         return super().has_add_permission(request, *args)
#
#     def has_change_permission(self, request, obj=None):
#         if (u := request.user) and u.is_active and (u.is_superuser or u.is_staff):
#             return True
#         return super().has_change_permission(request, obj)
#
#     def has_delete_permission(self, request, obj=None):
#         if (u := request.user) and u.is_active and (u.is_superuser or u.is_staff):
#             return True
#         return super().has_delete_permission(request, obj)
#
#     def has_view_permission(self, request, obj=None):
#         if (u := request.user) and u.is_active and (u.is_superuser or u.is_staff):
#             return True
#         return super().has_view_permission(request, obj)
#
#     def has_module_permission(self, request):
#         return request.user.is_active and (request.user.is_superuser or request.user.is_site_staff)
#


class HistoryAdmin(SimpleHistoryAdmin):

    def view_on_site(self, obj):
        try:
            return obj.get_absolute_url()
        except (AttributeError, NoReverseMatch):
            return super().view_on_site(obj)

    def get_history_list_display(self, request):
        if hasattr(self.model, "state"):
            # return ["state", "state_changed_at"]
            return ["STATE"]
        return []

    @admin.display(description="State", empty_value="N/A")
    def STATE(self, obj):
        if obj.state:
            if state_changed_at := getattr(obj, "state_changed_at", None):
                sca = obj.state_changed_at.strftime("%d-%m-%Y %H:%m")
                return mark_safe(
                    f"""<b title="State changed at {sca}">{obj.get_state_display().upper()}</b> ({sca})"""
                )
            return mark_safe(f"<b>{obj.get_state_display().upper()}</b>")
        return ""


class KeepSelectedMixin:

    def response_action(self, request, queryset):
        resp = super().response_action(request, queryset)
        if helpers.ACTION_CHECKBOX_NAME in request.POST:
            resp.set_cookie(
                "selected_action",
                ":".join(request.POST.getlist(helpers.ACTION_CHECKBOX_NAME)),
                max_age=60,
            )
        return resp


@admin.register(models.Subscription)
class SubscriptionAdmin(StaffPermsMixin, ImportExportMixin, ExportActionMixin, HistoryAdmin):
    view_on_site = False
    save_on_top = True
    exclude = [
        "site",
    ]
    list_display = ["email", "name"]
    list_filter = ["created_at", "updated_at", "is_confirmed"]
    search_fields = ["email"]
    date_hierarchy = "created_at"


@admin.register(models.ContractDocument)
class ContractDocumentAdmin(StaffPermsMixin, HistoryAdmin):
    view_on_site = False
    save_on_top = True
    list_display = [
        "contract__number",
        "required_document",
        "file",
        "state",
        "created_at",
        "updated_at",
    ]
    list_display_links = ["file", "contract__number"]
    list_filter = [
        "created_at",
        "updated_at",
        "state",
        ("contract", admin.RelatedOnlyFieldListFilter),
        ("required_document", admin.RelatedOnlyFieldListFilter),
    ]
    search_fields = ["file", "contract__number"]
    date_hierarchy = "created_at"
    # autocomplete_fields = ["contract", "converted_file", "required_document"]
    autocomplete_fields = ["contract", "converted_file"]
    # exclude = ["converted_file"]
    exclude = ["document_type"]

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # if db_field.name == "document_type":
        #     kwargs["queryset"] = models.Application.objects.filter(site_id=settings.SITE_ID)
        if db_field.name == "required_document":
            if (m := re.search(r"contractdocument/(\d+)/change", request.path)) and (
                document_id := m.group(1)
            ):
                kwargs["queryset"] = models.RequiredContractDocument.where(
                    Q(documents__pk=document_id)
                    | Q(round__applications__contracts__documents__pk=document_id)
                ).distinct()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(models.Currency)
class CurrencyAdmin(StaffPermsMixin, ImportExportMixin, ExportActionMixin, admin.ModelAdmin):
    view_on_site = False
    save_on_top = True
    list_display = ["code", "currency", "numeric_code", "minor_unit"]
    search_fields = ["code", "currency"]
    date_hierarchy = "updated_at"
    ordering = ["code", "currency"]


@admin.register(models.Country)
class CountryAdmin(StaffPermsMixin, ImportExportMixin, ExportActionMixin, admin.ModelAdmin):
    view_on_site = False
    save_on_top = True
    list_display = ["code", "code3", "name"]
    search_fields = ["name", "code", "code3"]
    date_hierarchy = "created_at"
    ordering = ["code", "code3"]


@admin.register(models.ReportingScheduleEntry)
class ReportingScheduleEntryAdmin(admin.ModelAdmin):

    search_fields = ["contract__number"]

    def get_model_perms(self, request):
        """
        Return empty perms dict thus hiding the model from admin index.
        """
        return {}

    def get_search_results(self, request, queryset, search_term):
        r = super().get_search_results(request, queryset, search_term)
        return r


@admin.register(models.Address)
class AddressAdmin(
    StaffPermsMixin, ImportExportMixin, ExportActionMixin, AutocompleteFilterMixin, HistoryAdmin
):
    view_on_site = False
    save_on_top = True
    list_display = ["address", "city", "country"]
    # list_filter = [("country", admin.RelatedOnlyFieldListFilter)]
    list_filter = [("country", filters.AutocompleteListFilter)]
    search_fields = ["address", "city", "country__name"]
    date_hierarchy = "created_at"
    autocomplete_fields = ["country"]


@admin.register(models.Keyword)
class KeywordAdmin(ExportActionMixin, ImportExportModelAdmin):
    show_close_button = True

    # class KeywordedItemInline(admin.StackedInline):
    #     model = models.KeywordedItem

    # inlines = [KeywordedItemInline]
    list_display = ["name", "slug"]
    ordering = ["name", "slug"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(models.ResearchPriority)
class ResearchPriorityAdmin(ExportActionMixin, ImportExportModelAdmin):
    show_close_button = True

    # class KeywordedItemInline(admin.StackedInline):
    #     model = models.KeywordedItem

    # inlines = [KeywordedItemInline]
    list_display = ["name", "slug"]
    ordering = ["name", "slug"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ["name"]}


class PanelDecisionResource(ModelResource):

    number = fields.Field(attribute="number", column_name="Proposal")
    grade = fields.Field(attribute="grade", column_name="Grade%")
    decision = fields.Field(attribute="decision", column_name="Decision")
    panel = fields.Field(attribute="panel", column_name="Panel")
    rank = fields.Field(attribute="rank", column_name="Rank")
    adjust = fields.Field(column_name="Adjust", saves_null_values=False)
    f7 = fields.Field(column_name="F7", saves_null_values=False)
    f8 = fields.Field(column_name="F8", saves_null_values=False)
    f9 = fields.Field(column_name="F9", saves_null_values=False)

    def before_save_instance(self, instance, row, **kwargs):
        if instance.decision:
            instance.decision = instance.decision.upper()

    class Meta:
        model = models.PanelDecision
        exclude = ["site", "created_at", "updated_at"]
        import_id_fields = ["number"]
        skip_unchanged = True
        report_skipped = True
        raise_errors = False
        use_transactions = True


@admin.register(models.PanelDecision)
class PanelDecisionAdmin(ExportActionMixin, ImportExportModelAdmin):
    show_close_button = True

    # class KeywordedItemInline(admin.StackedInline):
    #     model = models.KeywordedItem
    # inlines = [KeywordedItemInline]

    list_editable = ["grade", "decision", "panel", "rank"]
    list_display = ["number", "grade", "decision", "panel", "rank"]
    ordering = ["number", "panel"]
    search_fields = ["number", "panel"]
    list_filter = ["panel", "decision"]
    resource_classes = [PanelDecisionResource]


class EthnicityResource(ModelResource):
    class Meta:
        model = models.Ethnicity
        exclude = ["created_at", "updated_at"]
        import_id_fields = ["code"]
        skip_unchanged = True
        report_skipped = True
        raise_errors = False


@admin.register(models.Ethnicity)
class EthnicityAdmin(ImportExportMixin, ExportActionMixin, HistoryAdmin):
    save_on_top = True
    view_on_site = False
    search_fields = [
        "description",
        "level_three_description",
        "level_two_description",
        "level_one_description",
        "definition",
    ]
    resource_classes = [EthnicityResource]
    list_display = ["code", "description"]
    ordering = ["description"]

    def get_search_fields(self, request):
        if (q := request.GET.get("q")) and (
            (q[0] in ["^", "=", "@", "$"] and q[1:].isdigit()) or q.isdigit()
        ):
            return ["^code"]
        return super().get_search_fields(request)


# class SeoResource(ModelResource):
#     class Meta:
#         model = models.SocioEconomicObjective
#         exclude = ["created_at", "updated_at"]
#         import_id_fields = ["code"]
#         skip_unchanged = True
#         report_skipped = True
#         raise_errors = False


# @admin.register(models.SocioEconomicObjective)
# class SeoAdmin(ImportExportModelAdmin, HistoryAdmin):
#     save_on_top = True
#     view_on_site = False
#     search_fields = [
#         "code",
#         "description",
#         "source",
#     ]
#     resource_classes = [SeoResource]


class CodeResource(ModelResource):
    class Meta:
        exclude = ["created_at", "updated_at", "id"]
        import_id_fields = ["code"]
        skip_unchanged = True
        report_skipped = True
        raise_errors = False


@admin.register(models.Language)
class LanguageAdmin(ImportExportMixin, ExportActionMixin, HistoryAdmin):
    save_on_top = True
    view_on_site = False

    class LanguageResource(CodeResource):
        class Meta:
            model = models.Language

    list_display = ["code", "description"]
    search_fields = ["description", "definition"]
    resource_classes = [LanguageResource]


@admin.register(models.Rcc)
class RccAdmin(admin.ModelAdmin):
    show_close_button = True
    list_display = ("code", "description", "source", "code")
    search_fields = ["code", "description", "rcc"]

    def has_module_permission(self, request):
        return False


@admin.register(models.FieldOfStudy)
class FieldOfStudyAdmin(ImportExportModelAdmin):
    save_on_top = True
    view_on_site = False

    class FieldOfStudyResource(CodeResource):
        class Meta:
            exclude = ["created_at", "updated_at", "id"]
            model = models.FieldOfStudy

    def get_search_fields(self, request):
        if (q := request.GET.get("q")) and (
            (q[0] in ["^", "=", "@", "$"] and q[1:].isdigit()) or q.isdigit()
        ):
            return ["^code"]
        return super().get_search_fields(request)

    search_fields = ["description", "definition", "^code"]
    resource_classes = [FieldOfStudyResource]
    # list_display = ["code", "description", "definition", "version"]
    # list_filter = ["version", "two_digit_code"]


@admin.register(models.SocioEconomicObjective)
class SocioEconomicObjectiveAdmin(ImportExportModelAdmin):
    save_on_top = True
    view_on_site = False

    class SocioEconomicObjectiveResource(CodeResource):
        class Meta:
            exclude = ["created_at", "updated_at"]
            model = models.SocioEconomicObjective
            import_id_fields = ["code"]
            skip_unchanged = True
            report_skipped = True
            raise_errors = False

    def get_search_fields(self, request):
        if (q := request.GET.get("q")) and (
            (q[0] in ["^", "=", "@", "$"] and q[1:].isdigit()) or q.isdigit()
        ):
            return ["^code"]
        return super().get_search_fields(request)

    search_fields = ["description", "definition", "^code"]
    resource_classes = [SocioEconomicObjectiveResource]
    list_display = ["code", "description", "definition", "version"]
    list_filter = ["version", "source"]


@admin.register(models.FieldOfResearch)
class FieldOfResearchAdmin(ImportExportModelAdmin):
    save_on_top = True
    view_on_site = False
    show_close_button = True

    @admin.action(description="Toggle STEM")
    def toggle_stem(self, request, queryset, *args, **kwargs):
        c = self.model.where(code__in=[r.code for r in queryset]).update(
            is_stem=models.Q(is_stem=False)
        )
        messages.success(request, "%d FoRs records updated" % c)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if "is_stem" in form.changed_data:
            count = self.model.where(
                ~Q(code=obj.code), ~Q(is_stem=obj.is_stem), two_digit_code=obj.two_digit_code
            ).update(is_stem=obj.is_stem)
            if count:
                messages.success(request, "%d FoRs records marked as STEM entries" % count)

    class FieldOfResearchResource(CodeResource):
        class Meta:
            exclude = ["created_at", "updated_at", "id", "rcc", "is_stem"]
            model = models.FieldOfResearch

    def get_search_fields(self, request):
        if (q := request.GET.get("q")) and (
            (q[0] in ["^", "=", "@", "$"] and q[1:].isdigit()) or q.isdigit()
        ):
            return ["^code"]
        return super().get_search_fields(request)

    search_fields = ["description", "definition", "^code"]
    resource_classes = [FieldOfResearchResource]
    list_display = ["code", "description", "definition", "version", "is_stem"]
    list_filter = ["is_stem", "version", "two_digit_code"]
    actions = ["toggle_stem"]


@admin.register(models.CareerStage)
class CareerStageAdmin(ExportActionMixin, ImportExportModelAdmin):
    save_on_top = True
    view_on_site = False

    class CareerStageResource(CodeResource):
        class Meta:
            model = models.CareerStage

    search_fields = ["description", "definition"]
    resource_classes = [CareerStageResource]


@admin.register(models.PersonIdentifierType)
class PersonIdentifierTypeAdmin(ExportActionMixin, ImportExportModelAdmin):
    save_on_top = True
    view_on_site = False

    class PersonIdentifierTypeResource(CodeResource):
        class Meta:
            model = models.PersonIdentifierType

    search_fields = ["description", "definition"]
    list_display = ["code", "description", "definition"]
    resource_classes = [PersonIdentifierTypeResource]


@admin.register(models.IwiGroup)
class IwiGroupAdmin(ExportActionMixin, ImportExportModelAdmin):
    save_on_top = True
    view_on_site = False

    class IwiGroupResource(CodeResource):
        class Meta:
            model = models.IwiGroup

    search_fields = ["description", "definition", "parent_description"]
    resource_classs = [IwiGroupResource]


@admin.register(models.ProtectionPattern)
class ProtectionPatternAdmin(ImportExportMixin, ExportActionMixin, TranslationAdmin):
    save_on_top = True
    view_on_site = False

    class ProtectionPatternResource(CodeResource):
        class Meta:
            model = models.ProtectionPattern

    search_fields = ["description", "pattern"]
    list_display = ["code", "description", "pattern"]
    resource_classes = [ProtectionPatternResource]
    fieldsets = [
        (
            None,
            {
                "fields": (
                    "code",
                    "description",
                    "pattern",
                )
            },
        ),
        (
            _("Comment"),
            {
                "classes": ("collapse",),
                "fields": (
                    "comment_en",
                    "comment_mi",
                ),
            },
        ),
    ]


@admin.register(models.OrgIdentifierType)
class OrgIdentifierTypeAdmin(ExportActionMixin, ImportExportModelAdmin):
    save_on_top = True
    view_on_site = False

    class OrgIdentifierTypeResource(CodeResource):
        class Meta:
            model = models.OrgIdentifierType

    search_fields = ["description", "definition"]
    resource_classes = [OrgIdentifierTypeResource]


@admin.register(models.ChangeType)
class ChangeTypeAdmin(ExportActionMixin, ImportExportModelAdmin):
    save_on_top = True
    view_on_site = False

    class CategoryInline(admin.TabularInline):
        model = models.ChangeCategory
        extra = 0
        view_on_site = False

    class ChangeTypeResource(CodeResource):
        class Meta:
            model = models.ChangeType

    search_fields = ["description", "definition"]
    resource_classes = [ChangeTypeResource]
    inlines = [CategoryInline]


@admin.register(models.ChangeCategory)
class ChangeCategoryAdmin(ExportActionMixin, ImportExportModelAdmin):
    save_on_top = True
    view_on_site = False
    search_fields = ["description", "definition", "type__description", "type__definition"]
    list_display = ["type__code", "code", "description"]
    list_display_links = ["code", "description"]

    class SubCategoryInline(admin.TabularInline):
        model = models.ChangeCategory
        extra = 0
        view_on_site = False

    class ChangeCategoryResource(CodeResource):
        class Meta:
            model = models.ChangeCategory

    search_fields = ["description", "definition"]
    resource_classes = [ChangeCategoryResource]
    inlines = [SubCategoryInline]


@admin.register(models.ApplicationDecision)
class ApplicationDecisionAdmin(ExportActionMixin, ImportExportModelAdmin):
    save_on_top = True
    view_on_site = False

    class ApplicationDecisionResource(CodeResource):
        class Meta:
            model = models.ApplicationDecision

    searcah_fields = ["description", "definition"]
    resource_classes = [ApplicationDecisionResource]


@admin.register(models.Qualification)
class QualificationDecisionAdmin(ExportActionMixin, ImportExportModelAdmin):
    save_on_top = True
    view_on_site = False

    class QualificationDecisionResource(CodeResource):
        class Meta:
            fields = ["code", "description", "definition"]
            model = models.Qualification
            import_id_fields = ["description"]

    search_fields = ["description", "definition"]
    list_display = ["code", "description", "definition"]
    resource_classes = [QualificationDecisionResource]


class FundResource(ModelResource):
    class Meta:
        exclude = ["created_at", "updated_at", "id"]
        import_id_fields = ["code"]
        skip_unchanged = True
        report_skipped = True
        raise_errors = False
        model = models.Fund


# @admin.register(models.Fund)
# class FundAdmin(StaffPermsMixin, ExportActionMixin, ImportExportMixin, TranslationAdmin):
#     save_on_top = True
#     list_display = ["code", "code3", "description", "site"]
#     list_filter = ["site"]
#     search_fields = ["code", "code", "description_en", "description_mi"]
#     resource_classes = [FundResource]


@admin.register(models.Fund)
class FundAdmin(StaffPermsMixin, ExportActionMixin, ImportExportMixin, TranslationAdmin):
    show_close_button = True
    save_on_top = True
    resource_classes = [FundResource]
    list_filter = ["site"]

    class PanelInline(admin.StackedInline):
        extra = 0
        model = models.Panel
        view_on_site = False
        classes = ["collapse"]

    # class CoordinatorRolesInline(admin.TabularInline):
    #     extra = 0
    #     model = models.CoordinatorRole.funds.through
    #     # view_on_site = False
    #     verbose_name = "Coordinator Role"
    #     verbose_name_plural = "Coordinator Roles"
    #     # show_change_link = False

    list_display = (
        "code",
        "code3",
        "description",
        "cost_centre",
        "catalyst_cost_centre",
    )
    search_fields = ["code", "code3", "description_en", "description_mi"]
    # filter_horizontal = ("coordinator_roles",)

    # inlines = [PanelInline, CommitteeInline, CoordinatorRolesInline]
    inlines = [PanelInline]


class PanelResource(ModelResource):

    class Meta:
        model = models.Panel
        import_id_fields = ["code", "fund", "state"]
        exclude = (
            "created_at",
            "updated_at",
            "id",
        )
        # fields = [
        #     "code",
        #     "fund",
        #     "description",
        #     "state",
        # ]
        skip_unchanged = True
        report_skipped = True
        raise_errors = False
        name = "Export/Import Panels"


@admin.register(models.Panel)
class PanelAdmin(StaffPermsMixin, ImportExportMixin, ExportActionMixin, admin.ModelAdmin):
    resource_classes = [PanelResource]
    show_close_button = True
    list_display = ("code", "state", "description", "is_active", "fund")
    list_filter = (
        ("fund", admin.RelatedOnlyFieldListFilter),
        "state",
    )
    search_fields = ["code", "description"]
    fields = (("state", "is_active"), "code", "description", "fund")
    readonly_fields = ("is_active",)

    def is_active(self, obj):
        return obj.is_active

    is_active.boolean = True
    is_active.short_description = "Is active?"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("fund")

    class PanellistInline(admin.StackedInline):
        extra = 0
        model = models.Panellist
        view_on_site = False
        # autocomplete_fields = ["user", "fund"]
        autocomplete_fields = ["user"]

        # def get_queryset(self, *args, **kwargs):
        #     return super().get_queryset(*args, **kwargs).prefetch_related("person").prefetch_related("fund")

    # class FundInline(admin.StackedInline):
    #     extra = 0
    #     model = models.Fund
    #     view_on_site = False

    inlines = [PanellistInline]


@admin.register(models.Person)
class PersonAdmin(StaffPermsMixin, HistoryAdmin):
    save_on_top = True
    autocomplete_fields = ["address", "user", "title"]

    def get_search_fields(self, request):
        if (q := request.GET.get("q")) and (qq := q.strip()) and qq.isupper():
            return ["^code"]
        return super().get_search_fields(request)

    def get_search_results(self, request, queryset, search_term):
        queryset, may_have_duplicates = super().get_search_results(
            request,
            queryset,
            search_term,
        )
        model_name = request.GET.get("model_name")
        if model_name == "organisation":
            if request.GET.get("field_name") == "signatory":
                return queryset.distinct(), False
        return queryset, may_have_duplicates

    def save_formset(self, request, form, formset, change):
        # Save the formset instances with commit=False
        if formset.model != models.Note:
            return super().save_formset(request, form, formset, change)

        instances = formset.save(commit=False)
        # Loop through each instance and set the user

        for instance in instances:
            if not instance.author:
                instance.author = request.user  # Or 'created_by'
            instance.save()

        # Save any many-to-many relationships
        formset.save_m2m()

    class PersonCareerStageInline(admin.StackedInline):
        extra = 1
        model = models.PersonCareerStage
        view_on_site = False

    class PersonPersonIdentifierInline(admin.StackedInline):
        extra = 1
        model = models.PersonPersonIdentifier
        view_on_site = False

    class AffiliationInline(admin.StackedInline):
        extra = 1
        model = models.Affiliation
        view_on_site = False
        # autocomplete_fields = ["org"]

    class CurriculumVitaeInline(admin.StackedInline):
        extra = 1
        exclude = ["owner", "converted_file"]
        model = models.CurriculumVitae
        view_on_site = False

    class ProtectionPatternInline(admin.TabularInline):
        extra = 0
        model = models.PersonProtectionPattern
        verbose_name = _("Protection Pattern")
        verbose_name_plural = _("Protection Patterns")

        def has_add_permission(self, request, obj=None):
            return False

        def has_delete_permission(self, request, obj=None):
            return False

        def has_change_permission(self, request, obj=None):
            return False

    class EmailInline(admin.TabularInline):
        extra = 0
        model = models.PersonEmail
        view_on_site = False
        classes = ["collapse"]

    filter_horizontal = ["ethnicities", "languages_spoken", "iwi_groups"]
    search_fields = [
        "user__username",
        "code",
        "user__email",
        "user__first_name",
        "user__last_name",
        "first_name",
        "last_name",
        "email",
    ]
    list_display = ["username", "code", "user", "full_name_with_email", "created_at"]
    # list_display_links = ["username"]
    list_filter = ["created_at", "updated_at"]
    autocomplete_fields = ["user", "title", "address"]

    def username(self, obj):
        return (obj.user and obj.user.username) or obj.code or obj.full_name_with_email

    inlines = [
        PersonCareerStageInline,
        PersonPersonIdentifierInline,
        AffiliationInline,
        CurriculumVitaeInline,
        ProtectionPatternInline,
        EmailInline,
        NoteInline,
    ]

    # def get_queryset(self, request):
    #     return (
    #         super()
    #         .get_queryset(request)
    #         # .select_related("referee__application", "referee__application__round", "referee__user")
    #     )

    @admin.action(description="Merge Persons/Profiles")
    def merge(self, request, queryset):

        if "do_action" in request.POST:
            if target_id := (request.POST.get("target") or request.POST.get("chosen_object")):
                if target_id.isdigit():
                    target = self.model.objects.filter(id=target_id).first()
                else:
                    target = self.model.objects.filter(code=target_id).first()
                if not target:
                    messages.error(request, "Target person/profile not found.")
                    return
                keep = request.POST.get("keep") in ["on", "yes", "true", "1"]
                target.merge(queryset=queryset, request=request, keep=keep, by=request.user)
            return

        # Get the code object from the frame and then the name
        action_name = inspect.currentframe().f_code.co_name
        action = self.get_action(action_name)
        action_label = action and action[2] or action_name.replace("_", " ").capitalize()
        return render(
            request,
            "action_select_item.html",
            {
                **self.admin_site.each_context(request),
                "title": "Choose target profile/person to merge the rest of the profiles/persons",
                "item_label": "Target profile/person",
                "objects": queryset,
                "subtitle": None,
                "object_name": str(self.opts.verbose_name),
                "objects_name": str(self.opts.verbose_name_plural),
                "object": None,
                "deleted_objects": queryset,
                "model_count": queryset.count(),
                "action_name": action_name,
                "action_label": action_label,
                "first_item": queryset.filter(is_active=True, user__isnull=False)
                .order_by("pk")
                .first()
                or queryset.filter(user__isnull=False).order_by("pk").first()
                or queryset.filter(is_active=True).order_by("pk").first()
                or queryset.order_by("pk").first(),
                "opts": self.opts,
                "keep": False,
                "app_label": self.opts.app_label,
                "preserved_filters": self.get_preserved_filters(request),
                "is_popup": admin.options.IS_POPUP_VAR in request.POST
                or admin.options.IS_POPUP_VAR in request.GET,
                # "to_field": to_field,
                # "perms_lacking": perms_needed,
                # "protected": protected,
            },
        )

    actions = ["merge"]

    def view_on_site(self, obj):
        return reverse("profile-instance", kwargs={"pk": obj.pk})

    def save_form(self, request, form, change):
        if (
            change
            and "code" in form.changed_data
            and (old_code := self.model.where(pk=form.instance.pk).values_list("code").first()[0])
        ):
            models.PersonCode.get_or_create(
                person=form.instance,
                code=old_code,
            )
        # if not created and self.code:
        #     pass
        return super().save_form(request=request, form=form, change=change)


class IsActiveRoundApplicationListFilter(admin.SimpleListFilter):
    title = "Is Active Round"

    parameter_name = "is_active_round"

    def get_facet_counts(self, pk_attname, filtered_qs):

        return {
            "ACTIVE__c": models.Count(
                pk_attname,
                filter=Q(round__scheme__current_round__id=F("round_id")),
            ),
            "PREVIOUS__c": models.Count(
                pk_attname,
                filter=~Q(round__scheme__current_round__id=F("round_id")),
            ),
            "All__c": models.Count(pk_attname),
        }

    def choices(self, changelist):

        add_facets = changelist.add_facets
        facet_counts = self.get_facet_queryset(changelist) if add_facets else None

        yield {
            "selected": self.value() == "ACTIVE" or self.value() is None,
            "query_string": changelist.get_query_string(remove=[self.parameter_name]),
            "display": f"ACTIVE ({facet_counts['ACTIVE__c']})" if add_facets else "ACTIVE",
        }
        for lookup, title in self.lookup_choices:
            v = self.value()
            c = facet_counts and facet_counts.get(f"{lookup}__c", 0)
            yield {
                "selected": v == str(lookup),
                "query_string": changelist.get_query_string({self.parameter_name: lookup}),
                "display": f"{title} ({c})" if add_facets else title,
            }

    def lookups(self, request, model_admin):
        return (
            ("PREVIOUS", _("Previous")),
            ("All", _("All")),
        )

    def queryset(self, request, queryset):
        if self.value() == "ACTIVE" or self.value() is None:
            return queryset.filter(round__scheme__current_round__id=F("round_id"))
        if self.value() == "PREVIOUS":
            return queryset.filter(~Q(round__scheme__current_round__id=F("round_id")))
        return queryset


# class ApplicationForm(forms.ModelForm):
#     class Meta:
#         model = models.Application
#         widgets = {
#             # "keywords": autocomplete.TaggitSelect2(
#             "keywords": autocomplete.ModelSelect2Multiple(
#                 url="keyword-autocomplete",
#             )
#
#         fields = "__all__"


@admin.action(description="Refresh Appendices Page Counts")
def refresh_page_counts(modeladmin, request, queryset):
    count = 0
    for obj in queryset:
        count += modeladmin.model.refresh_page_counts(queryset=obj.documents.all())
    messages.success(request, f"{count} document page counts refreshed.")


# @admin.action(description="Convert or reconvert files to PDF")
# def convert_files(modeladmin, request, queryset):
#     count = 0
#         for obj in queryset:
#     for obj in queryset:
#         count += modeladmin.model.refresh_page_counts(queryset=obj.documents.all())
#     messages.success(request, f"{count} document page counts refreshed.")


@admin.action(description="Revert Object States")
def revert_object_states(modeladmin, request, queryset):
    count = 0
    objects = []

    content_type = models.ContentType.objects.get_for_model(modeladmin.model)

    # StateLog.objects.for_(a).order_by("-id").first()
    for obj in queryset:
        state_log_entry = (
            models.StateLog.objects.for_(obj)
            .filter(~Q(source_state=obj.state))
            .order_by("-id")
            .first()
        )
        if state_log_entry:
            obj._change_reason = (
                f"State reverted form {obj.state} to {state_log_entry.source_state} by admin ({request.user}).",
            )
            obj.state = state_log_entry.source_state
            obj.state_changed_at = state_log_entry.timestamp
            obj.updated_at = timezone.now()
            objects.append(obj)
            count += 1
    if objects:
        # modeladmin.model.objects.bulk_update(objects)
        bulk_update_with_history(
            objects,
            modeladmin.model,
            ["state", "state_changed_at", "updated_at"],
            default_user=request.user,
            manager=modeladmin.model.objects,
        )
    messages.success(request, f"{count} object state(s) were reverted.")


@admin.action(description="Archive Objects")
def archive_objects(modeladmin, request, queryset):
    count = 0
    objects = []
    for obj in queryset:
        if obj.state != "archived":
            obj.archive(
                request=request,
                user=request.user,
                description=f"Archived by admin ({request.user}).",
            )
            objects.append(obj)
            count += 1
    if objects:
        # modeladmin.model.objects.bulk_update(objects)
        bulk_update_with_history(
            objects,
            modeladmin.model,
            ["state", "state_changed_at", "updated_at"],
            default_user=request.user,
            manager=modeladmin.model.objects,
        )
    messages.success(request, f"{count} object(s) were archived.")


@admin.register(models.Member)
class MemberAdmin(UnaccentMixin, StaffPermsMixin, FSMTransitionMixin, HistoryAdmin):
    save_on_top = True
    list_display = [
        "email",
        "full_name",
        "role",
        "application",
        "state",
        "has_authorized",
        "changed_at",
    ]
    search_fields = [
        "email",
        "first_name",
        "last_name",
        "application__number",
        "application__application_title",
    ]
    list_filter = ["application__round", "role", "created_at", "updated_at", "state"]
    date_hierarchy = "created_at"
    inlines = [StateLogInline]
    readonly_fields = [
        "application",
        "state",
        "state_changed_at",
        "authorized_at",
        "has_authorized",
        "cv",
    ]
    autocomplete_fields = ["user", "application", "converted_file", "country", "org"]

    def has_authorized(self, obj):
        if obj.state == "authorized":
            return True
        elif obj.state == "opted_out":
            return False

    has_authorized.boolean = True

    def changed_at(self, obj):
        return obj.state_changed_at or obj.updated_at or obj.created_at

    def view_on_site(self, obj):
        return reverse("application", kwargs={"pk": obj.application_id})

    class EffortInline(admin.TabularInline):
        model = models.MemberEffort
        extra = 0
        view_on_site = False

    def get_inlines(self, request, obj):
        inlines = super().get_inlines(request, obj)
        if (
            obj
            and obj.application
            and obj.application.round.has_ftes
            and self.EffortInline not in inlines
        ):
            inlines.append(self.EffortInline)
        return inlines


@admin.register(models.Application)
class ApplicationAdmin(
    UnaccentMixin,
    PdfFileAdminMixin,
    StaffPermsMixin,
    FSMTransitionMixin,
    TranslationAdmin,
    HistoryAdmin,
):

    history_list_display = ["changed_fields"]

    def changed_fields(self, obj):
        if obj.prev_record:
            delta = obj.diff_against(obj.prev_record)
            return delta.changed_fields
        return ""

    # form = ApplicationForm
    show_close_button = True
    save_on_top = True
    date_hierarchy = "created_at"
    list_display = [
        "number",
        # "state_icon",
        "complete",
        "application_title",
        "full_name",
        "org",
        "state",
        "is_active_round",
        # "tag_list",
    ]
    list_filter = [
        IsActiveRoundApplicationListFilter,
        ("round", admin.RelatedOnlyFieldListFilter),
        ("org", admin.RelatedOnlyFieldListFilter),
        ("panel", admin.RelatedOnlyFieldListFilter),
        "state",
        "created_at",
        "updated_at",
    ]
    readonly_fields = [
        "nomination_url",
        "created_at",
        "updated_at",
        "converted_file",
        "letter_of_support",
        # "number",
        "state",
        "STATE",
        "main_applicant",
        "previous_numbers",
        "agent_declaration_accepted_at",
        "applicant_declaration_accepted_by",
    ]
    search_fields = [
        "number",
        "first_name",
        "last_name",
        "middle_names",
        "email",
        "organisation",
        "org__name",
        "round__title",
        "members__email",
        "referees__email",
    ]
    autocomplete_fields = [
        "address",
        "cv",
        "org",
        "panel",
        "submitted_by",
        "title",
    ]
    # summernote_fields = ["summary"]
    exclude = ["summary", "summary_en", "summary_mi", "is_bilingual_summary", "site"]

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["show_save_and_add_another"] = False
        return super().change_view(
            request,
            object_id,
            form_url,
            extra_context=extra_context,
        )

    def get_queryset(self, request):
        return (
            super().get_queryset(request).prefetch_related("tags").select_related("round", "org")
        )

    def complete(self, obj):
        return obj.state == "submitted" or obj.state == "archive"

    complete.boolean = True

    # @admin.display(description="State", empty_value="N/A")
    # def STATE(self, obj):
    #     if obj.state:
    #         if obj.state_changed_at:
    #             sca = obj.state_changed_at.strftime("%d-%m-%Y %H:%m")
    #             return mark_safe(
    #                 f"""<b title="State changed at {sca}">{obj.get_state_display().upper()}</b> ({sca})"""
    #             )
    #         return mark_safe(f"<b>{obj.get_state_display().upper()}</b>")
    #     return ""

    @admin.display(description="Previous Numbers")
    def previous_numbers(self, obj, *args, **kwargs):
        return mark_safe(
            ", ".join(
                f'<b style="color:red;">{n}</b>'
                for n, in obj.numbers.values_list("number").order_by("number")
            )
        )

    def is_active_round(self, obj):
        return obj.round.scheme.current_round == obj.round

    is_active_round.boolean = True

    class MemberInline(StaffPermsMixin, admin.TabularInline):

        extra = 0
        model = models.Member
        readonly_fields = ["STATE", "state", "state_changed_at"]
        # readonly_fields = ["is_complete", "state", "state_changed_at"]
        autocomplete_fields = ["user"]
        fields = ["STATE", "email", "first_name", "last_name", "role"]
        show_change_link = True
        view_on_site = False

        # fields = ["is_complete", "email", "first_name", "middle_names", "last_name", "role_description", "role",
        # "user", "state", "state_changed_at", "authorized_at"]

        # def is_complete(self, obj):
        #     if self.members.filter(Q(authorized_at__isnull=True) | Q(user__isnull=True)).exists():
        # is_complete.boolean = True

        # def view_on_site(self, obj):
        #     return reverse("application", kwargs={"pk": obj.application_id})

    class RefereeInline(StaffPermsMixin, admin.TabularInline):
        extra = 0
        view_on_site = False
        model = models.Referee
        readonly_fields = [
            "STATE",
            "state_changed_at",
            "has_testified",
            "testified_at",
            "survey_completed_at",
            "survey_url",
        ]
        exclude = ["survey_token", "survey_token_id", "survey_invitation_sent_at"]
        autocomplete_fields = ["user", "org"]

        def get_exclude(self, request, obj=None):
            exclude = super().get_exclude(request, obj)
            if settings.SITE_ID in [2, 4, 5]:
                exclude.extend(["survey_completed_at", "survey_url"])
            return exclude

        def has_testified(self, obj):
            return obj.state == "testified"

        def survey_url(self, obj):
            if obj.application.round_id:
                return obj.survey_url

        has_testified.boolean = True

        def view_on_site(self, obj):
            # return reverse("application", kwargs={"pk": obj.application_id})
            return reverse("admin:portal_referee_change", kwargs={"object_id": obj.pk})

    class DocumentInline(admin.TabularInline):
        model = models.ApplicationDocument
        # autocomplete_fields = ["document_type"]
        fields = ["required_document", "page_count", "file"]

        extra = 0
        view_on_site = False
        show_change_link = True
        # classes = ["collapse"]

    class ForInline(admin.TabularInline):
        model = models.ApplicationFor
        autocomplete_fields = ["code"]
        extra = 0
        view_on_site = False
        classes = ["collapse"]

    class SeoInline(admin.TabularInline):
        model = models.ApplicationSeo
        autocomplete_fields = ["code"]
        extra = 0
        view_on_site = False
        classes = ["collapse"]

    class KeywordInline(admin.TabularInline):
        model = models.ApplicationKeyword
        autocomplete_fields = ["keyword"]
        extra = 0
        view_on_site = False
        classes = ["collapse"]

    inlines = [
        MemberInline,
        RefereeInline,
        DocumentInline,
        ForInline,
        SeoInline,
        KeywordInline,
        NoteInline,
        StateLogInline,
    ]

    def save_formset(self, request, form, formset, change):
        # Save the formset instances with commit=False
        if formset.model != models.Note:
            return super().save_formset(request, form, formset, change)

        instances = formset.save(commit=False)
        # Loop through each instance and set the user

        for instance in instances:
            if not instance.author:
                instance.author = request.user  # Or 'created_by'
            instance.save()

        # Save any many-to-many relationships
        formset.save_m2m()

    @admin.display(description="Main Applicant")
    def main_applicant(self, obj):
        if obj.submitted_by:
            return format_html(
                '<a href="{0}?_popup=1" target="_blank">{1}</a>',
                reverse("admin:users_user_change", kwargs={"object_id": obj.submitted_by.pk}),
                f"{obj.submitted_by.full_name_with_email} : {obj.submitted_by.username}",
            )

    @admin.display(description="Nomination")
    def nomination_url(self, obj):
        if n := models.Nomination.where(application=obj).last():
            return format_html(
                '<a href="{0}?_popup=1" target="_blank">{1}</a>',
                reverse("admin:portal_nomination_change", kwargs={"object_id": n.id}),
                f"{n} by {n.nominator.full_name_with_email}",
            )

    @admin.display(description="State")
    def state_icon(self, obj):
        return format_html(
            '<i class="fa fa-check text-success text-center" title="{0}">&nbsp;{0}</i>',
            obj.state.upper(),
        )

    fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": [
                    "STATE",
                    ("number", "application_title_en", "application_title_mi"),
                    "is_bilingual",
                    "round",
                    ("title", "first_name", "middle_names", "last_name", "position"),
                    ("daytime_phone", "mobile_phone"),
                    ("email", "main_applicant"),
                    "presentation_url",
                    "is_tac_accepted",
                    ("tags", "priorities"),
                ],
            },
        ),
        (
            "Other fields (CHANGE WITH CARE)",
            {
                "classes": ("collapse",),
                "fields": [
                    "submitted_by",
                ],
            },
        ),
        (
            "Organisation",
            {
                "fields": [
                    "org",
                    "postal_address",
                    "city",
                    "postcode",
                ],
            },
        ),
        (
            "Summary and Files",
            {
                "classes": ("collapse",),
                "fields": [
                    "file",
                    "cv",
                ],
            },
        ),
        (
            "Vision Mātauranga",
            {
                "classes": ("collapse",),
                "fields": [
                    "vm_ecs",
                    "vm_ens",
                    "vm_hsw",
                    "vm_ink",
                    "is_vm_na",
                    "vm_rationale",
                ],
            },
        ),
        (
            "Type of Activity",
            {
                "classes": ("collapse",),
                "fields": [
                    "toa_applied",
                    "toa_basic",
                    "toa_strategic",
                    "toa_experimental",
                ],
            },
        ),
    )

    def get_fieldsets(self, request, obj):
        # fieldsets = super().get_fieldsets(request, obj).copy()
        site_id = obj and obj.site_id or settings.SITE_ID
        nomination = models.Nomination.where(application=obj).order_by("-pk").first()
        fieldsets = (
            (
                None,
                {
                    "classes": ("wide",),
                    "fields": [
                        "STATE",
                        ("number", "application_title_en", "application_title_mi"),
                        "is_bilingual",
                        (
                            ("round", "panel")
                            if obj and obj.round and obj.round.can_specify_panel
                            else "round"
                        ),
                        ("title", "first_name", "middle_names", "last_name", "position"),
                        ("daytime_phone", "mobile_phone", "address"),
                        ("email", "main_applicant"),
                        "presentation_url",
                        (
                            (
                                "is_tac_accepted",
                                "agent_declaration_accepted_at",
                                "applicant_declaration_accepted_by",
                            )
                            if obj.round.applicant_declaration
                            else "is_tac_accepted"
                        ),
                        ("tags", "priorities"),
                    ],
                },
            ),
            (
                "Other fields (CHANGE WITH CARE)",
                {
                    "classes": ("collapse",),
                    "fields": [
                        "submitted_by",
                    ],
                },
            ),
            (
                "Organisation",
                {
                    "fields": [
                        ("org", "organisation") if nomination else "org",
                        "postal_address",
                        "city",
                        "postcode",
                    ],
                },
            ),
            (
                "Summary and Files",
                {
                    "classes": ("collapse",),
                    "fields": (
                        [
                            "file",
                            "budget",
                            "cv",
                        ]
                        if site_id in [1, 7]
                        else [
                            "file",
                            "cv",
                        ]
                    ),
                },
            ),
            (
                "Vision Mātauranga",
                {
                    "classes": ("collapse",),
                    "fields": [
                        "vm_ecs",
                        "vm_ens",
                        "vm_hsw",
                        "vm_ink",
                        "is_vm_na",
                        "vm_rationale",
                    ],
                },
            ),
            (
                "Type of Activity",
                {
                    "classes": ("collapse",),
                    "fields": [
                        "toa_applied",
                        "toa_basic",
                        "toa_strategic",
                        "toa_experimental",
                    ],
                },
            ),
        )

        if obj and obj.numbers.exists():
            fieldsets[0][1]["fields"].insert(2, "previous_numbers")
        if obj and obj.round.can_nominate and models.Nomination.where(application=obj).exists():
            fieldsets[0][1]["fields"][0] = ("nomination_url", "STATE")
        if (obj and obj.site_id or settings.SITE_ID) in [2, 4, 5]:
            fieldsets[0][1]["fields"].insert(2, "research_experience_in_years")

        return fieldsets

    def view_on_site(self, obj):
        return reverse("application", kwargs={"pk": obj.id})

    @admin.action(description="Approve on behalf of R.O.")
    def approve(self, request, queryset):
        # count = queryset.count()
        submitted = queryset.filter(state="submitted")
        submitted_count = submitted.count()
        if not submitted_count:
            messages.warning(request, "Only SUBMITTED applications can be approved...")
            return

        u = request.user
        applications = []
        for a in submitted:
            a.approve(by=u, request=request, description=f"Approved on behalf of R.O. by {u}")
            applications.append(a)

        bulk_update_with_history(
            applications,
            models.Application,
            default_user=u,
            fields=["state", "state_changed_at", "updated_at"],
            default_change_reason=f"Approved on behalf of R.O. by {u}",
        )
        messages.success(
            request, f"{submitted_count} approved: {','.join(a.number for a in applications)}."
        )

    @admin.action(description="Accept in bulk")
    def accept(self, request, queryset):

        if "do_action" in request.POST:
            resolution = request.POST.get("resolution")
            approved = queryset.filter(state="approved")
            approved_count = approved.count()
            if not approved_count:
                messages.warning(request, "Only APPROVED applications can be accepted...")
                return

            u = request.user
            applications = []
            for a in approved:
                a.accept(by=u, request=request, description=resolution or f"Accepted by {u}")
                applications.append(a)

            bulk_update_with_history(
                applications,
                models.Application,
                default_user=u,
                fields=["state", "state_changed_at", "updated_at"],
                default_change_reason=resolution or f"Accepted by {u}",
            )
            messages.success(
                request, f"{approved_count} accepted: {','.join(a.number for a in applications)}."
            )

        return render(
            request,
            "action_resolution.html",
            {
                "title": "Resolution or notes",
                "objects": queryset,
                "action_label": self.get_action("accept")[-1],
            },
        )

    @admin.action(description="Invite referees")
    def invite_referees(self, request, queryset):
        if request.site_id not in [2, 5] or "do_action" in request.POST:
            invitation_count = models.invite_referees(
                request=request,
                applications=queryset,
                by=request.user,
                after_round_closes=("force" not in request.POST)
                or (request.POST.get("force") != "1"),
            )
            messages.success(request, f"{invitation_count} referee invitation(s) dispatched.")
            return

        return render(
            request,
            "action_invite_referees.html",
            {
                "title": "Invite referees",
                "objects": queryset,
                "applications": queryset,
                "action_label": self.get_action("invite_referees")[-1],
            },
        )

    @admin.action(description="Initialize a new contract/contracs")
    def initialize_contracts(self, request, queryset):
        contract_count = 0
        contracts = []
        for a in queryset.filter(
            state__in=["funded", "accepted", "approved"], contracts__isnull=True
        ):
            c = models.Contract.create_from_application(application=a)
            if c:
                contracts.append(c)
            contract_count += 1
        if contracts:
            links = ", ".join(
                f"""<a
            href="{reverse('admin:portal_contract_change', kwargs={"object_id": c.pk})}"
            target="_blank">
            {c.number}</a>"""
                for c in contracts
            )
            messages.success(
                request, mark_safe(f"{len(contracts)} contracts were created: {links}.")
            )

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj=obj, change=change, **kwargs)
        form.base_fields["priorities"].widget = autocomplete.TaggitSelect2(
            url="research-priority-autocomplete",
            forward=[
                dal.forward.Field("round", "round"),
                dal.forward.Const("application", "model"),
            ],
        )
        return form

    actions = [
        "approve",
        "accept",
        "initialize_contracts",
        "invite_referees",
        refresh_page_counts,
        "request_resubmission",
        "send_identity_verification_reminder",
        archive_objects,
        revert_object_states,
    ]

    # def get_actions(self, request):
    #     actions = super().get_actions(request)
    #     if settings.SITE_ID not in [2, 5] and "invite_referees" in actions:
    #         del actions["invite_referees"]
    #     return actions

    # def save_formset(self, request, form, formset, change):
    #     if isinstance(formset.model, Note):
    #         breakpoint()
    #     super().save_formset(request, form, formset, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        obj = form.instance

        # Addjust shares of FoR:
        total = models.ApplicationFor.where(application=obj).aggregate(total=models.Sum("share"))[
            "total"
        ]
        if total is not None and total != 100:
            records = list(
                models.ApplicationFor.where(application=obj, share__isnull=False).order_by("share")
            )
            if records and len(records) > 1:
                for af in records[:-1]:
                    af.share = round((af.share or 0) * 100 / total)
                records[-1].share = 100 - sum(fa.share for fa in records[:-1])
            else:
                records[0].share = 100
            models.ApplicationFor.objects.bulk_update(records, ["share"])

        # Addjust shares of SEO:
        total = models.ApplicationSeo.where(application=obj).aggregate(total=models.Sum("share"))[
            "total"
        ]
        if total is not None and total != 100:
            records = list(
                models.ApplicationSeo.where(application=obj, share__isnull=False).order_by("share")
            )
            if records and len(records) > 1:
                for af in records[:-1]:
                    af.share = round((af.share or 0) * 100 / total)
                records[-1].share = 100 - sum(fa.share for fa in records[:-1])
            else:
                records[0].share = 100
            models.ApplicationSeo.objects.bulk_update(records, ["share"])

    @admin.action(description="Remind to verify identities")
    def send_identity_verification_reminder(self, request, queryset):
        recipients = []
        for a in queryset.filter(
            Q(submitted_by__is_identity_verified=False)
            | Q(submitted_by__is_identity_verified__isnull=True)
        ):
            for iv in models.IdentityVerification.where(
                ~Q(state="accepted"), application=a, file__isnull=False
            ):
                iv.send(request)
                recipients.append(iv.user or a.submitted_by)

        if recipients:
            messages.success(
                request,
                "Successfully sent reminders to verify %d applicants: %s"
                % (len(recipients), ", ".join(u.full_name_with_email for u in recipients)),
            )
        else:
            messages.success(
                request,
                "No reminder sent, there is either no user requiring "
                "verification or ID has not been submitted",
            )

    @admin.action(description="Request resubmission")
    def request_resubmission(self, request, queryset):
        if "do_action" in request.POST:
            resolution = request.POST.get("resolution")
            for o in queryset.filter(state="submitted"):
                o.request_resubmission(request, resolution=resolution)
                o.save()
            return

        return render(
            request,
            "action_request_resubmission.html",
            {
                "title": "Specify Reason for Resubmission",
                "objects": queryset,
            },
        )

    def save_model(self, request, obj, form, change):

        super().save_model(request, obj, form, change)
        if change and "round" in form.changed_data:
            old_number = obj.number
            obj.number = models.default_application_number(obj)
            obj.save(update_fields=["number"])
            models.ApplicationNumber.get_or_create(application=obj, number=old_number)

        r = form.cleaned_data["round"]
        if r.survey_id:
            count = r.sync_referee_surveys(request=request)
            if count > 0:
                messages.success(request, f"{count} new referee survey invitation(s) sent")

        if change and "file" in form.changed_data and obj.file:
            try:
                if cf := obj.update_converted_file():
                    obj.save()
                    messages.success(
                        request,
                        format_html(
                            (
                                "The attachment was converted into PDF file. "
                                "Please review the converted file version <a href='%s'>%s</a>."
                            )
                            % (cf.file.url, os.path.basename(cf.file.name))
                        ),
                    )

            except:
                messages.error(
                    request,
                    (
                        "Failed to convert the attachment form into PDF. "
                        "Please save your attachment  into PDF format and try to upload it again."
                    ),
                )
                raise


@admin.register(models.ApplicationDocument)
class ApplicationDocumentAdmin(StaffPermsMixin, HistoryAdmin):
    view_on_site = False
    save_on_top = True
    list_display = [
        "application__number",
        "required_document",
        "file",
        # "state",
        "created_at",
        "updated_at",
        "converted_file__created_at",
        "converted_file_url",
    ]
    list_display_links = ["file", "application__number"]
    list_filter = [
        "created_at",
        "updated_at",
        # "state",
        ("application", admin.RelatedOnlyFieldListFilter),
        # ("required_document", admin.RelatedOnlyFieldListFilter),
    ]
    search_fields = ["file", "application__number"]
    date_hierarchy = "created_at"
    # autocomplete_fields = ["contract", "converted_file", "required_document"]
    autocomplete_fields = ["application", "converted_file"]
    # exclude = ["converted_file"]
    exclude = ["document_type"]

    @admin.display(empty_value="-")
    def converted_file_url(self, obj):
        if obj.converted_file and (f := obj.converted_file.file):
            return mark_safe(f'<a href={f.url}">{f.name}</a>')


@admin.register(models.Award)
class AwardAdmin(admin.ModelAdmin):
    save_on_top = True
    view_on_site = False


@admin.register(models.ConvertedFile)
class ConvertedFileAdmin(admin.ModelAdmin):
    save_on_top = True
    search_fields = [
        "applications__number",
        "application_documents__application__number",
        "members__application__number",
        "nominations__application__number",
        "testimonials__referee__application__number",
        "contract_documents__contract__number",
        "change_requests__number",
        "change_requests__contract__number",
        "change_requests__derivative__number",
        "reports__contract__number",
        "file",
    ]

    def file_size_kb(self, obj):
        try:
            if size := obj.file_size:
                return round(size / 1000, 2)
        except:
            return

    file_size_kb.short_description = "file size (KB)"
    exclude = [
        "site",
    ]

    view_on_site = False
    list_display = ["file", "page_count", "file_size_kb"]


@admin.register(models.CurriculumVitae)
class CurriculumVitaeAdmin(UnaccentMixin, admin.ModelAdmin):
    save_on_top = True
    list_display = ["person", "owner", "title", "file"]
    autocomplete_fields = ["person", "owner"]
    # list_filter = ["owner"]
    search_fields = [
        "owner__first_name",
        "owner__last_name",
        "owner__username",
        "owner__email",
        "file",
        "title",
        "applications__number",
        "members__application__number",
    ]
    date_hierarchy = "created_at"
    view_on_site = False


@admin.register(models.ScoreSheet)
class ScoreSheetAdmin(StaffPermsMixin, admin.ModelAdmin):
    save_on_top = True
    list_display = ["panellist", "round", "file"]
    list_filter = ["round"]
    date_hierarchy = "created_at"

    def view_on_site(self, obj):
        return reverse("evaluation", kwargs={"pk": obj.id})


@admin.register(models.Referee)
class RefereeAdmin(
    KeepSelectedMixin, UnaccentMixin, StaffPermsMixin, FSMTransitionMixin, HistoryAdmin
):

    save_on_top = True
    limesurvey_admin_url = (
        f"{settings.DEBUG and settings.LIMESURVEY_SERVER_URL or '/limesurvey/'}admin/"
    )

    # def get_search_results(self, request, queryset, search_term):
    #     return super().get_search_results(request, queryset, search_term)

    @admin.display(description="State", empty_value="N/A")
    def STATE(self, obj):
        if obj.state:
            sca = obj.state_changed_at.strftime("%d-%m-%Y %H:%m")
            return mark_safe(
                f"""<b title="State changed at {sca}">{obj.get_state_display().upper()} </b> ({sca})"""
            )

    @admin.display(description="survey participant", ordering="survey_token")
    def participant_link(self, obj):
        if (token_id := obj.survey_token_id) and (survey_id := obj.application.round.survey_id):
            url = f"{self.limesurvey_admin_url}tokens/sa/edit/iSurveyId/{survey_id}/iTokenId/{token_id}"
            return mark_safe(
                f'<a href="{url}" target="_blank">{obj.survey_token or obj.email}</a>'
            )
        return "-"

    list_display = [
        "email",
        "has_testified",
        "application_number",
        "full_name",
        "state",
        "org",
        "testified_at",
        # "survey_completed_at",
    ]
    search_fields = [
        "survey_token",
        "first_name",
        "last_name",
        "email",
        "application__number",
        "application__application_title",
    ]
    list_filter = [
        "created_at",
        "survey_completed_at",
        "testified_at",
        "state",
        "testimonial__state",
        "application__state",
        ("application__round", admin.RelatedOnlyFieldListFilter),
        ("org", admin.RelatedOnlyFieldListFilter),
    ]
    date_hierarchy = "testified_at"
    autocomplete_fields = ["user", "application", "org"]
    readonly_fields = [
        "STATE",
        # "application",
        # "state",
        "state_changed_at",
        "has_testified",
        "testified_at",
        "invitation_link",
        "testimonial_link",
    ]
    inlines = [StateLogInline]

    def get_list_display(self, request):
        if request.site_id in [2, 5]:
            return [
                "email",
                "has_testified",
                "application_number",
                "full_name",
                "state",
                "org",
                "testified_at",
                "participant_link",
                "survey_completed_at",
            ]
        return super().get_list_display(request)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if "q" not in request.GET:
            return qs.filter(application__round__scheme__current_round=F("application__round"))
        return qs

    @admin.display(description="application", ordering="application__number")
    def application_number(self, obj):
        return obj.application.number

    @admin.display(description="invitation")
    def invitation_link(self, obj):
        if obj.invitation:
            return mark_safe(
                '<a href="{}?_popup=1" target="_blank">{}</a>'.format(
                    reverse("admin:portal_invitation_change", args=(obj.invitation.pk,)),
                    obj.invitation,
                )
            )

    @admin.display(description="testimonial")
    def testimonial_link(self, obj):
        if t := models.Testimonial.where(referee=obj).order_by("-pk").first():
            return mark_safe(
                '<a href="{}?_popup=1" target="_blank">{}</a>'.format(
                    reverse("admin:portal_testimonial_change", args=(t.pk,)),
                    obj.invitation,
                )
            )
        return "-"

    def has_testified(self, obj):
        return obj.state == "testified"

    has_testified.boolean = True

    def view_on_site(self, obj):
        return reverse("application", kwargs={"pk": obj.application_id})

    actions = ["send_invitations", "invite_to_survey", "sync_referee_surveys", "set_organisation"]

    @admin.action(description="Sync with the LimeSurvey surveys")
    def sync_referee_surveys(self, request, queryset):
        count = 0
        rounds = models.Round.where(
            survey_id__isnull=False, pk__in=queryset.values_list("application__round").distinct()
        )
        for r in rounds:
            count += r.sync_referee_surveys(
                request=request, referees=queryset.filter(application__round=r)
            )
        if not count:
            messages.warning(request, "All referees were already synced.")
        if rounds.count() > 1:
            messages.info(request, f"In total synced {count} referee(s)")

    @admin.action(description="Send the referee invitations")
    def send_invitations(self, request, queryset):
        count = models.Referee.invite_referees(request, by=request.user, referees=queryset)
        messages.success(request, f"Successfully sent invitation(-s) to {count} referee(-s)")

    @admin.action(description="Assign Organisations to the referees")
    def set_organisation(self, request, queryset):
        models.Referee.set_organisation(request, by=request.user, queryset=queryset)

    @admin.action(description="Send invitations to the referees for the survey")
    def invite_to_survey(self, request, queryset):
        count = 0
        for r in queryset:
            if (
                not (r.survey_token_id and r.survey_token and r.survey_invitation_sent_at)
                and not r.survey_completed_at
            ):
                r.invite_to_survey(request=request)
                count += 1
        messages.success(request, f"Successfully sent invitation(-s) to {count} referee(-s)")

    @admin.action(description="Invite members")
    def invite_members(self, request, queryset, *args, **kwargs):
        applications = models.Application.where(members__in=queryset)
        for a in applications:
            count = a.invite_team_members(request)
            if count > 0:
                messages.success(
                    request,
                    f"{count} invitation(s) to join the application ({a}) team have been sent.",
                )

    actions = ["invite_members"]


@admin.register(models.ContractMember)
class ContractMemberAdmin(UnaccentMixin, StaffPermsMixin, HistoryAdmin):
    save_on_top = True
    list_display = [
        "email",
        "full_name",
        "role",
        "contract",
        "updated_at",
    ]
    search_fields = [
        "email",
        "first_name",
        "last_name",
        "contract__number",
        "contract__project_title",
        "application__number",
        "application__application_title",
    ]
    list_filter = [
        "role",
        "created_at",
        "updated_at",
        ("contract__org", admin.RelatedOnlyFieldListFilter),
        ("contract__application__round", admin.RelatedOnlyFieldListFilter),
    ]
    date_hierarchy = "created_at"
    # readonly_fields = ["contract", "address"]
    readonly_fields = ["contract"]
    autocomplete_fields = ["user", "contract", "address"]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if (site_id := request.site_id) != 0:
            return qs.filter(contract__site_id=site_id)
        return qs

    def view_on_site(self, obj):
        return reverse("contract-detail", kwargs={"number": obj.contract.number})

    class EffortInline(admin.TabularInline):
        model = models.ContractMemberEffort
        extra = 0
        view_on_site = False

    inlines = [EffortInline]


@admin.register(models.Panellist)
class PanellistAdmin(UnaccentMixin, StaffPermsMixin, FSMTransitionMixin, admin.ModelAdmin):
    save_on_top = True
    list_display = ["full_name_with_email", "round", "state"]
    search_fields = ["first_name", "last_name", "email"]
    list_filter = ["round", "created_at", "updated_at", "state"]
    date_hierarchy = "created_at"
    exclude = ["site"]
    inlines = [StateLogInline]
    readonly_fields = ["state"]

    actions = ["resend_invitations"]

    @admin.action(description="Resend the invitations")
    def resend_invitations(self, request, queryset):
        for p in queryset:
            i, created = p.get_or_create_invitation()
            if not created:
                i.sent_at = None
                i.save()

        recipients = []
        invitations = list(
            models.Invitation.where(~Q(state="accepted"), panellist__in=queryset, type="P")
        )
        for i in invitations:
            i.resend(request)
            i.save()
            recipients.append(i.panellist)

        messages.success(
            request,
            "Successfully sent invitation(-s) to %d panellist(-s): %s"
            % (len(recipients), ", ".join(r.full_name_with_email for r in recipients)),
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj and obj.state != "bounced":
            i, _ = obj.get_or_create_invitation()
            if i.state not in ["sent", "bounced"]:
                i.send(request)
                i.save()

                messages.success(
                    request, "Successfully sent invitation to %s" % i.panellist.full_email_address
                )

    def view_on_site(self, obj):
        return reverse("panellist-invite", kwargs={"round": obj.round_id})


@admin.register(models.IdentityVerification)
class IdentityVerificationAdmin(UnaccentMixin, StaffPermsMixin, FSMTransitionMixin, HistoryAdmin):
    save_on_top = True
    list_display = ["user", "is_accepted", "application"]
    search_fields = ["user__first_name", "user__last_name", "application__application_title"]
    list_filter = ["application__round", "created_at", "updated_at", "state"]
    date_hierarchy = "created_at"
    readonly_fields = ["state"]
    inlines = [StateLogInline]
    autocomplete_fields = ["user", "application"]

    def is_accepted(self, obj):
        return obj.state == "accepted"

    is_accepted.boolean = True
    is_accepted.short_description = _("Verified")

    def view_on_site(self, obj):
        app = (
            obj.application
            or models.Application.where(email=obj.user.email).order_by("id").first()
        )
        if app:
            return reverse("round-coi-list", kwargs={"round": app.round_id})


@admin.register(models.ConflictOfInterest)
class ConflictOfInterestAdmin(UnaccentMixin, StaffPermsMixin, admin.ModelAdmin):
    save_on_top = True
    list_display = ["panellist", "application", "has_conflict"]
    readonly_fields = [
        "application",
        "created_at",
        "panellist",
        "updated_at",
        # "comment",
        # "has_conflict",
    ]
    list_filter = ["has_conflict", "application__round", "created_at", "updated_at"]
    search_fields = [
        "panellist__first_name",
        "panellist__last_name",
        "panellist__email",
        "application__number",
    ]
    date_hierarchy = "created_at"
    autocomplete_fields = ["panellist", "application"]

    def view_on_site(self, obj):
        return reverse("round-coi-list", kwargs={"round": obj.application.round_id})


@admin.register(models.MailLog)
class MailLogAdmin(StaffPermsMixin, admin.ModelAdmin):
    save_on_top = True
    view_on_site = False
    list_display = [
        "token",
        "was_sent_successfully",
        "sent_at",
        "recipient",
        "subject",
    ]
    readonly_fields = ["thread_index", "thread_topic", "message", "html_message_content"]
    autocomplete_fields = ["user", "invitation"]
    search_fields = ["token", "recipient", "subject"]
    exclude = ["site", "html_message"]
    list_filter = ["sent_at", "updated_at", "was_sent_successfully"]
    date_hierarchy = "sent_at"

    class RecipientInline(StaffPermsMixin, admin.TabularInline):
        extra = 0
        model = models.Recipient
        fields = ["type", "recipient"]

    inlines = [RecipientInline]

    def html_message_content(self, obj):
        return mark_safe(obj.html_message or "-")


@admin.register(models.Impersonation)
class ImpersonationAdmin(admin.ModelAdmin):
    save_on_top = True
    view_on_site = False
    list_display = [
        "user",
        "impersonated",
        "impersonated_at",
    ]
    readonly_fields = ["user", "impersonated", "impersonated_at"]
    autocomplete_fields = ["user", "impersonated"]
    search_fields = ["user__username", "user__email"]
    list_filter = ["impersonated_at"]
    date_hierarchy = "impersonated_at"


@admin.register(models.Nomination)
class NominationAdmin(UnaccentMixin, PdfFileAdminMixin, FSMTransitionMixin, HistoryAdmin):
    save_on_top = True

    def nominator_name(self, obj):
        return obj.nominator.full_name_with_email or obj.nominator

    def nominee_name(self, obj):
        return obj.full_name_with_email

    nominee_name.short_description = "nominee"
    nominee_name.admin_order_field = "first_name"

    nominator_name.short_description = "nominator"
    nominator_name.admin_order_field = "nominator__first_name"

    list_display = [
        "round",
        "nominee_name",
        "nominator_name",
        "application_link",
        "invitation_url",
    ]
    date_hierarchy = "created_at"
    list_filter = [
        "created_at",
        "updated_at",
        "round",
        "state",
        ("org", admin.RelatedOnlyFieldListFilter),
    ]
    search_fields = [
        "email",
        "first_name",
        "last_name",
        "round__title",
        "application__number",
        "nominator__email",
        "nominator__first_name",
        "nominator__last_name",
        "nominator__username",
    ]
    # summernote_fields = ["summary"]
    exclude = [
        "summary",
        "site",
    ]
    autocomplete_fields = ["application", "user", "round", "nominator", "cv", "org"]
    actions = ["resend_invitations", archive_objects]
    inlines = [StateLogInline]

    @admin.display(description="invitation")
    def invitation_url(self, obj):
        return (
            ", ".join(
                (i.url or reverse("onboard-with-token", kwargs={"token": i.token}))
                for i in obj.invitations.all()
            )
            or ""
        )

    @admin.display(description="application")
    def application_link(self, obj):
        if a := obj.application:
            return mark_safe(f'<a href="{a.admin_url}" target="_blank">{a.number}</a>')

    @admin.action(description="Resend the invitations")
    def resend_invitations(self, request, queryset):
        recipients = []
        for o in queryset.filter(state__in=["submitted", "bounced"]):
            o.send_invitation(request, resend=True)
            recipients.append(o)

        messages.success(
            request,
            "Successfully sent invitation(-s) to apply to %d nominees: %s"
            % (len(recipients), ", ".join(r.full_name_with_email for r in recipients)),
        )

    def view_on_site(self, obj):
        return reverse("nomination-detail", kwargs={"pk": obj.id})


class OrganisationResource(ModelResource):
    identifier_type = fields.Field(
        column_name="identifier_type",
        attribute="identifier_type",
        widget=ForeignKeyWidget(models.OrgIdentifierType, field="description"),
    )

    class Meta:
        model = models.Organisation
        fields = ["code", "name", "identifier_type", "identifier"]
        import_id_fields = ["name"]
        export_order = ("code", "name", "identifier_type", "identifier")
        skip_unchanged = True
        report_skipped = True
        raise_errors = False
        name = "Export/Import with identifiers"


class OrganisationWOIdentifierResource(ModelResource):
    class Meta:
        model = models.Organisation
        fields = [
            "code",
            "name",
        ]
        import_id_fields = ["code"]
        export_order = (
            "code",
            "name",
        )
        skip_unchanged = True
        report_skipped = True
        raise_errors = False
        name = "Export/Import without identifiers (only codes and names)"


@admin.register(models.Organisation)
class OrganisationAdmin(StaffPermsMixin, ImportExportMixin, ExportActionMixin, HistoryAdmin):
    save_on_top = True
    view_on_site = False
    list_display = ["code", "name", "is_active", "created_at", "updated_at"]
    list_filter = ["created_at", "updated_at", "applications__round"]
    search_fields = ["name__icontains", "code"]
    date_hierarchy = "created_at"
    resource_classes = [OrganisationResource, OrganisationWOIdentifierResource]
    autocomplete_fields = ["address", "signatory"]
    actions = ["merge_orgs"]

    fieldsets = [
        (
            None,
            {
                "fields": [
                    ("code", "name", "is_active"),
                    ("identifier_type", "identifier"),
                    ("legal_name", "alt_name"),
                ],
            },
        ),
        (
            "Other Identifiers",
            {
                "classes": ("collapse",),
                "fields": [
                    ("grid", "ror", "gst"),
                    ("nzbn", "nz_ris_type"),
                ],
            },
        ),
        (
            "Contact Information",
            {
                # "classes": ("collapse",),
                "fields": [
                    ("address", "website"),
                    "contact",
                    ("email", "contact_phone"),
                    "signatory",
                    ("ro_email", "notify_ro_on_application_submission"),
                    (
                        "application_contact_email",
                        "contract_contact_email",
                        "reporting_contact_email",
                    ),
                ],
            },
        ),
    ]

    def get_fields(self, request, obj):
        fields = super().get_fields(request, obj)
        if obj and obj.replaced_org:
            return ["new_org_link", *fields]
        return fields

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj=obj)
        if obj and obj.replaced_org:
            return [
                (
                    None,
                    {
                        "fields": [
                            "new_org_link",
                            ("code", "name", "is_active"),
                            ("identifier_type", "identifier"),
                            ("legal_name", "alt_name"),
                        ],
                    },
                ),
                *fieldsets[1:],
            ]
        return [
            (
                None,
                {
                    "fields": [
                        ("code", "name", "is_active"),
                        ("identifier_type", "identifier"),
                        ("legal_name", "alt_name"),
                    ],
                },
            ),
            *fieldsets[1:],
        ]

    def get_object(self, request, object_id, from_field=None):
        obj = super().get_object(request=request, object_id=object_id, from_field=from_field)
        if obj and (org := obj.replaced_org):
            url = reverse("admin:portal_organisation_change", kwargs={"object_id": org.pk})
            self.message_user(
                request=request,
                message=mark_safe(
                    f'Organisattion "{obj}" was replaced with:<br><a href="{url}" target="_blank">{org}</a>'
                ),
                level=messages.WARNING,
                fail_silently=True,
            )
        return obj

    def has_change_permission(self, request, obj=None):
        return obj and not obj.replaced_org and super().has_change_permission(request, obj)

    # def get_queryset(self, request):
    #     qs = super().get_queryset(request)
    #     return qs
    @admin.display(description="New Organisation")
    def new_org_link(self, obj):
        if org := obj.replaced_org:
            url = reverse("admin:portal_organisation_change", kwargs={"object_id": org.pk})
            return mark_safe(f'<a style="color:red;"  href="{url}" target="_blank">{org}</a>')
        return

    class ResearchOfficeInline(StaffPermsMixin, admin.TabularInline):
        extra = 0
        model = models.ResearchOffice
        ordering = ["user__name"]
        autocomplete_fields = ["user"]

        view_on_site = False
        can_delete = True

    class NameInline(StaffPermsMixin, admin.TabularInline):
        extra = 0
        model = models.OrgName
        ordering = ["name"]

        view_on_site = False
        can_delete = True
        classes = ["collapse"]

    inlines = [ResearchOfficeInline, NameInline]

    def get_search_fields(self, request):
        if (q := request.GET.get("q")) and (qq := q.strip()) and qq.isupper():
            return ["^code"]
        return super().get_search_fields(request)

    @admin.action(description="Merge Organisations")
    def merge_orgs(self, request, queryset):
        if "do_action" in request.POST:
            u = request.user
            deleted = []
            merged = []
            errors = []
            if target_id := request.POST.get("target"):
                keep = request.POST.get("keep") != "0"
                target = models.Organisation.get(target_id)
                orgs = list(queryset.filter(~Q(id=target_id)))
                org_ids = [o.id for o in orgs]

                try:
                    with transaction.atomic():

                        qs = models.Application.all_objects.filter(
                            ~Q(number__iregex=f"^[A-Z0-9]+-{target.code}-[0-9]{{4}}-"),
                            Q(org_id__in=org_ids) | Q(nomination__org_id__in=org_ids),
                        ).order_by("number")
                        if keep:
                            qs.filter(round__scheme__current_round=F("round"))

                        org_applications = list(qs)

                        qs = models.Nomination.all_objects.filter(org__in=orgs)
                        if keep:
                            qs.filter(round__scheme__current_round=F("round"))
                        nominations = list(qs)

                        for n in nominations:
                            n._change_reason = f"Organisation {n.org} merged into {target} by {u}"
                            n.org = target

                        bulk_update_with_history(
                            nominations,
                            models.Nomination,
                            ["org", "updated_at"],
                            default_user=u,
                            manager=models.Nomination.all_objects,
                        )

                        if org_applications:
                            previous_application_numbers = [
                                models.ApplicationNumber(application=a, number=a.number)
                                for a in org_applications
                            ]
                            for r in previous_application_numbers:
                                r._change_reason = (
                                    f"Organisation {r.application.org} merged into {target} by {u}"
                                )
                            new_numbers = []
                            for a in org_applications:

                                if a.org in orgs:
                                    a.org = target

                                a.number = models.default_application_number(
                                    a, exclude_numbers=new_numbers
                                )
                                new_numbers.append(a.number)
                                a._change_reason = (
                                    f"Organisation {a.org} merged into {target} by {u}"
                                )
                                # a.save(update_fields=["org", "number"])
                            bulk_update_with_history(
                                org_applications,
                                models.Application,
                                ["org", "number", "updated_at"],
                                default_user=u,
                                manager=models.Application.all_objects,
                            )
                            bulk_create_with_history(
                                previous_application_numbers,
                                models.ApplicationNumber,
                                default_user=u,
                                ignore_conflicts=True,
                                # manager=models.Application.all_objects,
                            )

                        for model, field, objects in (
                            (
                                model,
                                field,
                                [
                                    setattr(
                                        o,
                                        "_change_reason",
                                        f"Organisation {getattr(o, field)} merged into {target} by {u}",
                                    )
                                    or setattr(o, field, target)
                                    or o
                                    for o in (
                                        model.all_objects.filter(**{f"{field}__in": org_ids})
                                        if hasattr(model, "all_objects")
                                        else model.where(**{f"{field}__in": org_ids})
                                    )
                                ],
                            )
                            for (model, field) in (
                                (rel.related_model, rel.remote_field.name)
                                for rel in get_candidate_relations_to_delete(
                                    models.Organisation._meta
                                )
                                if not issubclass(rel.related_model, HistoricalChanges)
                            )
                        ):
                            if model is models.Nomination:
                                continue
                            if hasattr(model, "history"):
                                bulk_update_with_history(
                                    objects,
                                    model,
                                    [field],
                                    default_user=u,
                                    manager=getattr(model, "all_objects", model._default_manager),
                                )
                            else:
                                manager = getattr(model, "all_objects", model._default_manager)
                                manager.bulk_update(objects, [field])

                        for o in orgs:
                            if not target.alternative_names.filter(name=o.name).exists():
                                models.OrgName.create(org=target, name=o.name)
                        if keep:
                            for o in orgs:
                                o.is_active = False
                                o.replaced_org = target
                                o._change_reason = f"Organisation {o} merged into {target} by {u}"
                            bulk_update_with_history(
                                orgs,
                                self.model,
                                ["replaced_org", "is_active", "updated_at"],
                                default_user=u,
                            )
                            merged = [f"{o.code}: {o.name}" for o in orgs]
                        else:
                            for o in orgs:
                                o._change_reason = f"Organisation {o} merged into {target} by {u}"
                                o.delete()
                            deleted = [f"{o.code}: {o.name}" for o in orgs]
                except Exception as ex:
                    capture_exception(ex)
                    errors.append(ex)

            if deleted:
                messages.success(
                    request,
                    f'{len(deleted)} organisation(s) merged and deleted: {", ".join(deleted)}',
                )
            if merged:
                messages.success(
                    request,
                    f'{len(merged)} organisation(s) merged and marked inactive: {", ".join(merged)}',
                )
            if errors:
                for e in errors:
                    messages.error(request, e)

            return

        if target := queryset.filter(is_active=True).first():

            context = {
                **self.admin_site.each_context(request),
                "title": "Choose target organisation",
                "subtitle": None,
                "object_name": str(self.opts.verbose_name),
                "object": None,
                "deleted_objects": queryset,
                "model_count": queryset.count(),
                # "perms_lacking": perms_needed,
                # "protected": protected,
                "opts": self.opts,
                "app_label": self.opts.app_label,
                "preserved_filters": self.get_preserved_filters(request),
                "is_popup": admin.options.IS_POPUP_VAR in request.POST
                or admin.options.IS_POPUP_VAR in request.GET,
                # "to_field": to_field,
                "objects": queryset,
                "target": target,
            }

            return render(
                request,
                "action_merge_orgs.html",
                context,
            )
        messages.error(
            request,
            "Please select at least one active organisation "
            "to be used as the target to merge other selected organisations into.",
        )


@admin.register(models.Invitation)
class InvitationAdmin(StaffPermsMixin, FSMTransitionMixin, ImportExportMixin, HistoryAdmin):

    @admin.action(description="Resend invitations")
    def resend(self, request, queryset):
        recipients = []
        for o in queryset:
            o.resend(request)
            o.save()
            recipients.append(o)

        messages.success(
            request,
            "Successfully resent invitation(-s) to %d recipients: %s"
            % (len(recipients), ", ".join(r.full_name_with_email for r in recipients)),
        )

    @admin.display(description="invitee", ordering="email")
    def full_name_with_email(self, obj):
        return obj.full_name_with_email

    save_on_top = True
    view_on_site = False
    exclude = [
        "site",
    ]
    list_display = [
        "token",
        "type",
        "state",
        "full_name_with_email",
        "created_at",
        "sent_at",
        "updated_at",
        # "invitation_url",
        "url",
    ]
    autocomplete_fields = [
        "inviter",
        "application",
        "nomination",
        "member",
        "referee",
        "panellist",
        "org",
    ]

    list_filter = [
        ("org", admin.RelatedOnlyFieldListFilter),
        "type",
        "state",
        "created_at",
        "updated_at",
    ]
    search_fields = ["first_name", "last_name", "email", "token", "application__number"]
    date_hierarchy = "created_at"
    readonly_fields = ["submitted_at", "accepted_at", "expired_at", "token", "url"]
    ordering = ["-id"]
    actions = ["resend"]

    @admin.display(description="URL", ordering="URL")
    def invitation_url(self, obj):
        if obj.url:
            return obj.url
        if obj.token:
            url = reverse("onboard-with-token", kwargs={"token": obj.token})
            return f"https://{obj.site.domain}/{url}"

    class MailLogInline(StaffPermsMixin, admin.TabularInline):
        classes = ["collapse"]
        extra = 0
        model = models.MailLog
        ordering = ["-id"]
        fields = [
            "token_link",
            "recipient",
            "thread_index",
            "thread_topic",
            "sent_at",
            "was_sent_successfully",
            "user",
            "sender",
            "subject",
        ]
        readonly_fields = ["sent_at"]

        @admin.display(description="token", ordering="token")
        def token_link(self, obj):
            return mark_safe(f'<a href="{self.view_on_site(obj)}">{obj.token}</a>')

        @cache
        def view_on_site(self, obj):
            return reverse("admin:portal_maillog_change", kwargs={"object_id": obj.pk})

        can_delete = False

        def has_add_permission(self, request, obj=None):
            return False

        def has_change_permission(self, request, obj=None):
            return True

        def get_readonly_fields(self, request, obj=None):
            return self.get_fields(request, obj)

    inlines = [MailLogInline, StateLogInline]


@admin.register(models.Testimonial)
class TestimonialAdmin(
    UnaccentMixin, PdfFileAdminMixin, StaffPermsMixin, FSMTransitionMixin, HistoryAdmin
):
    # summernote_fields = ["summary"]

    @admin.display(description="State", empty_value="N/A")
    def STATE(self, obj):
        if obj.state:
            sca = obj.state_changed_at.strftime("%d-%m-%Y %H:%m")
            return mark_safe(
                f"""<b title="State changed at {sca}">{obj.get_state_display().upper()} </b> ({sca})"""
            )

    autocomplete_fields = ["cv", "referee"]
    date_hierarchy = "created_at"
    exclude = ["summary", "site", "converted_file"]
    inlines = [StateLogInline]
    list_display = ["referee", "application_url", "state"]
    list_filter = [
        "created_at",
        "state",
        "referee__state",
        ("referee__application__round", admin.RelatedOnlyFieldListFilter),
        ("referee__application", admin.RelatedOnlyFieldListFilter),
        "referee__survey_completed_at",
    ]
    readonly_fields = ["STATE"]
    save_on_top = True
    search_fields = [
        "referee__first_name",
        "referee__last_name",
        "referee__email",
        "referee__application__number",
    ]

    @admin.display(description="application", ordering="referee__application__number")
    def application_url(self, obj):
        return mark_safe(
            '<a href="%s">%s</a>'
            % (
                reverse(
                    "admin:portal_application_change",
                    kwargs={"object_id": obj.referee.application_id},
                ),
                obj.referee.application.number,
            )
        )

    # application_url.allow_tags = True
    # application_url.short_description = "Application"
    application_url.ordering = "referee__application__number"

    def is_submitted(self, obj):
        return obj.is_active

    is_submitted.boolean = True

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("referee__application", "referee__application__round", "referee__user")
        )

    def view_on_site(self, obj):
        return reverse("application", kwargs={"pk": obj.referee.application_id})

    @admin.action(description="Sync with the LimeSurvey surveys")
    def sync_referee_surveys(self, request, queryset):
        count = 0
        rounds = models.Round.where(
            survey_id__isnull=False,
            pk__in=queryset.values_list("referee__application__round").distinct(),
        )
        for r in rounds:
            count += r.sync_referee_surveys(
                request=request,
                referees=models.Referee.where(
                    pk__in=queryset.filter(referee__application__round=r).values_list("referee_id")
                ),
            )
        if not count:
            messages.warning(request, "All referees and testimonials were already synced.")
        if rounds.count() > 1:
            messages.info(request, f"In total synced {count} referee(s) and testimonial(s)")

    actions = ["sync_referee_surveys", archive_objects]


class SchemeResource(ModelResource):
    class Meta:
        exclude = ["created_at", "updated_at", "groups", "id", "current_round"]
        import_id_fields = ["title"]
        skip_unchanged = True
        report_skipped = True
        raise_errors = False
        model = models.Scheme


@admin.register(models.Scheme)
class SchemeAdmin(
    StaffPermsMixin,
    ExportActionMixin,
    ImportExportMixin,
    TranslationAdmin,
):
    save_on_top = True
    list_display = ["code", "title", "current_round"]
    resource_classes = [SchemeResource]
    exclude = ["groups", "cv_required", "site"]
    actions = ["create_new_round"]
    autocomplete_fields = [
        "fund",
    ]
    # autocomplete_fields = ["fund", "current_round"]

    def get_form(self, request, obj=None, **kwargs):
        # Store the current object instance on the request
        form = super().get_form(request, obj, **kwargs)
        form.base_fields["current_round"].queryset = (
            models.Round.where(scheme=obj).order_by("-pk")[:5]
            if obj
            else models.Round.objects.none()
        )
        return form

    # def formfield_for_foreignkey(self, db_field, request, **kwargs):
    #     # if db_field.name == "document_type":
    #     #     kwargs["queryset"] = models.Application.objects.filter(site_id=settings.SITE_ID)
    #     if db_field.name == "current_round":
    #         if (m := re.search(r"contractdocument/(\d+)/change", request.path)) and (
    #             document_id := m.group(1)
    #         ):
    #             kwargs["queryset"] = models.RequiredContractDocument.where(
    #                 Q(documents__pk=document_id)
    #                 | Q(round__applications__contracts__documents__pk=document_id)
    #             ).distinct()
    #     return super().formfield_for_foreignkey(db_field, request, **kwargs)

    @admin.action(description="Create new round")
    def create_new_round(self, request, queryset):
        new_rounds = []
        with transaction.atomic():
            for r in models.Round.where(scheme__in=queryset, scheme__current__round_id=F("pk")):
                nr = r.clone(copy=True)
                r.scheme.current_round = nr
                r.scheme.save(update_fields=["current_round"])
                new_rounds.append(nr)
        if new_rounds:
            new_rounds = [f"{r}" for r in new_rounds]
            messages.info(request, f"New round(s) created: {', '.join(new_rounds)}")

        # for s in queryset.filter():
        #     r = models.Round(scheme=s)
        #     r.init_from_last_round()
        #     if not r.title:
        #         r.title = s.title
        #     if r.title == s.title and r.opens_on:
        #         r.title = f"{r.title} {r.opens_on.year}"
        #     r.save()
        #     s.current_round = r
        #     s.save(update_fields=["current_round"])

    def view_on_site(self, obj):
        if obj.current_round_id:
            return f"{reverse('applications')}?round={obj.current_round_id}"

    def save_model(self, request, obj, form, change):
        if obj and obj.fund and obj.fund.site != obj.site:
            messages.warning(
                request,
                f"The schema created in a different 'site' form the fund's site: {obj.fund.site}. "
                "You might need to reassing the fund to the current site.",
            )
        super().save_model(request, obj, form, change)

    class RoundInline(StaffPermsMixin, admin.TabularInline):
        extra = 0
        model = models.Round
        ordering = ["-id"]
        fields = [
            "is_active",
            "year",
            "title",
            "opens_on",
            "closes_at",
        ]
        readonly_fields = ["is_active", "year"]

        def is_active(self, obj):
            return obj.is_active

        def year(self, obj):
            return obj.opens_on.year

        is_active.boolean = True

        view_on_site = False
        can_delete = False

    inlines = [RoundInline]


class IsActiveRoundListFilter(admin.SimpleListFilter):
    title = "Is Active"

    parameter_name = "is_active"

    def choices(self, changelist):
        yield {
            "selected": self.value() == "1" or not self.value(),
            "query_string": changelist.get_query_string(remove=[self.parameter_name]),
            "display": _("ACTIVE"),
        }
        yield {
            "selected": self.value() == "0",
            "query_string": changelist.get_query_string({self.parameter_name: "0"}),
            "display": _("Previous"),
        }

    def lookups(self, request, model_admin):
        return (
            (1, _("ACTIVE")),
            (0, _("Previous")),
        )

    def queryset(self, request, queryset):
        if self.value() == "1" or not self.value():
            return queryset.filter(scheme__current_round__id=F("id"))
        if self.value() == "0":
            return queryset.filter(~Q(scheme__current_round__id=F("id")))


@admin.register(models.DocumentType)
class DocumentTypeAdmin(ImportExportMixin, StaffPermsMixin, TranslationAdmin):
    view_on_site = False
    save_on_top = True
    list_display = ["name", "role", "name_en", "name_mi", "format"]
    # exclude = ["site"]
    # list_display = ["email", "name"]
    # list_filter = ["created_at", "updated_at", "is_confirmed"]
    search_fields = ["name_en", "name_mi"]
    list_editable = ["role", "name_en", "name_mi", "format"]
    # date_hierarchy = "created_at"


@admin.register(models.PublicationType)
class PublicationTypeAdmin(ImportExportMixin, StaffPermsMixin, OrderableAdmin, admin.ModelAdmin):
    view_on_site = False
    save_on_top = True
    list_display = [
        "code",
        "code_2",
        "description",
        "ordering",
    ]
    list_display_links = ["code", "code_2"]
    search_fields = ["code", "code_2", "description"]
    ordering_field_hide_input = True
    exclude = ["ordering"]
    list_editable = ["ordering"]


@admin.register(models.RoleType)
class RoleTypeAdmin(ImportExportMixin, StaffPermsMixin, OrderableAdmin, TranslationAdmin):
    view_on_site = False
    save_on_top = True
    list_display = [
        "code",
        "name",
        "for_application",
        "for_contracting",
        "is_key_person",
        "ordering",
    ]
    list_display_links = ["code", "name"]
    search_fields = ["name_en", "name_mi"]
    # list_editable = ["role", "name_en", "name_mi"]
    # date_hierarchy = "created_at"
    list_editable = ["ordering", "for_application", "for_contracting", "is_key_person"]
    ordering_field_hide_input = True
    exclude = ["ordering"]


@admin.register(models.Title)
class TitleAdmin(ExportActionMixin, ImportExportMixin, StaffPermsMixin, TranslationAdmin):
    view_on_site = False
    save_on_top = True
    list_display = ["code", "name_en", "name_mi"]
    # exclude = ["site"]
    # list_display = ["email", "name"]
    # list_filter = ["created_at", "updated_at", "is_confirmed"]
    search_fields = ["name_en", "name_mi"]
    list_editable = ["name_en", "name_mi"]


class RequiredContractDocumentForm(forms.ModelForm):
    # application_required_document = forms.ModelChoiceField(
    #     widget=autocomplete.ModelSelect2(
    #         url="required-document-autocomplete",
    #         forward=[
    #             dal.forward.Field("round", "round"),
    #             # dal.forward.Const("1", "exclude_taken"),
    #         ],
    #     )
    # )
    # def __init__(self, instance=None, **kwargs):
    #     super().__init__(instance=instance, **kwargs)
    #     self.fields["application_required_document"].widget = autocomplete.ModelSelect2(
    #         url="required-document-autocomplete",
    #         forward=[
    #             dal.forward.Field("round", "round"),
    #             # dal.forward.Const("1", "exclude_taken"),
    #         ],
    #     )
    #     # if instance:
    #     #     queryset = self.fields["application_required_document"].queryset.filter(round=instance.round)
    #     #     self.fields["application_required_document"].queryset = queryset
    #     # else:
    #     #     self.fields["application_required_document"].disabled = True
    #     # pass

    class Meta:
        exclude = ["document_type"]
        model = models.RequiredContractDocument


@admin.register(models.Round)
class RoundAdmin(
    SummernoteModelAdminMixin,
    # ExportActionMixin,
    # ImportExportMixin,
    StaffPermsMixin,
    OrderableAdmin,
    TranslationAdmin,
    HistoryAdmin,
):
    summernote_fields = (
        "description_en",
        "description_mi",
        "tac_en",
        "tac_mi",
        "applicant_declaration",
        "agent_declaration",
        "contract_background",
    )
    save_on_top = True
    list_display = [
        "scheme__code",
        "coloured_title",
        # "scheme",
        "opens_on",
        "closes_at",
        "application_count",
        "contract_count",
        "report_count",
        "is_active",
        "ordering",
    ]
    list_editable = ["ordering"]
    ordering_field_hide_input = True
    list_filter = [
        IsActiveRoundListFilter,
        "opens_on",
        "closes_at",
        ("scheme", admin.RelatedOnlyFieldListFilter),
    ]
    date_hierarchy = "opens_on"
    exclude = [
        "site",
    ]
    search_fields = ["title", "scheme__code"]
    actions = [
        "create_new_round",
        "invite_referees",
        "sync_referee_surveys",
        "copy_round",
        "copy_performance_indicators",
        "make_current",
        "export_for_panellists",
    ]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        qs = qs.annotate(
            # contract_count=Count("contracts", filter=Q(contracts__isnull=False)),
            application_count=models.Count("applications", distinct=True),
            contract_count=models.Count("applications__contracts", distinct=True),
            report_count=models.Count(
                "applications__contracts__reporting_schedule__report", distinct=True
            ),
        )
        return qs

    def get_list_display(self, request):
        ld = super().get_list_display(request)[:]
        site_id = request.site_id or settings.SITE_ID
        if site_id == 0:
            ld.insert(ld.index("coloured_title"), "site")
            del ld[ld.index("ordering")]
        if (
            "survey" not in ld
            and (qs := self.get_queryset(request))
            and qs.filter(Q(survey_id__isnull=False), ~Q(survey_id=0)).exists()
        ):
            ld.insert(ld.index("application_count"), "survey")
            # del ld[ld.index("scheme")]

        return ld

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["show_save_and_add_another"] = False
        return super().change_view(
            request,
            object_id,
            form_url,
            extra_context=extra_context,
        )

    def has_change_permission(self, request, obj=None):
        if obj and obj.closes_at and (u := request.user) and not u.is_superuser:
            if obj.closes_at < timezone.now():
                return False  # Prevent editing of the closed round by staff
        return super().has_change_permission(request, obj)

    def get_exclude(self, request, obj=None):
        exclude = super().get_exclude(request, obj)
        site_id = settings.SITE_ID
        if site_id in [2, 4, 5]:
            exclude = exclude and exclude[:] or []
            exclude.extend(
                [
                    # "applicant_cv_required",
                    # "direct_application_allowed",
                    "ethics_statement_required",
                    "letter_of_support_required",
                ]
            )
            if site_id != 2:
                exclude.append("applicant_cv_required")

        return exclude

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj=obj, change=change, **kwargs)
        if obj and obj.pk:
            if obj.get_guidelines():
                if not obj.applicant_guidelines:
                    url = obj.get_applicant_guidelines()
                    form.base_fields["applicant_guidelines"].help_text = mark_safe(
                        f'{form.base_fields["applicant_guidelines"].help_text}<br>(DEFAULT: <a href="{url}">{url}</a>)'
                    )
                if not obj.referee_guidelines:
                    url = obj.get_referee_guidelines()
                    form.base_fields["referee_guidelines"].help_text = mark_safe(
                        f'{form.base_fields["referee_guidelines"].help_text}<br>(DEFAULT: <a href="{url}">{url}</a>)'
                    )
                if not obj.panellist_guidelines:
                    url = obj.get_panellist_guidelines()
                    form.base_fields["panellist_guidelines"].help_text = mark_safe(
                        f'{form.base_fields["panellist_guidelines"].help_text}<br>(DEFAULT: <a href="{url}">{url}</a>)'
                    )
        form.base_fields["priorities"].widget = autocomplete.TaggitSelect2(
            url="research-priority-autocomplete",
            forward=[dal.forward.Const("round", "model")],
        )
        return form

    def get_fieldsets(self, request, obj=None):
        site_id = obj and obj.site_id or settings.SITE_ID
        exclude = self.get_exclude(request)
        fieldsets = [
            (
                None,
                {
                    "fields": [
                        "scheme",
                        ("title_en", "title_mi", "foreground", "background"),
                        (
                            ("opens_on", "closes_at", "testimonial_submission_closes_at")
                            if site_id in [2, 5]
                            else ("opens_on", "closes_at")
                        ),
                        "description_en",
                        "description_mi",
                        "guidelines",
                        "applicant_guidelines",
                        "referee_guidelines",
                        "panellist_guidelines",
                        "contact_email",
                        "limesurvey_server_url",
                        "survey_id",
                    ]
                },
            ),
            (
                "Options",
                {
                    "fields": [
                        "priorities",
                        [
                            f
                            for f in [
                                "applicant_cv_required",
                                "can_nominate",
                                "can_specify_panel",
                                "direct_application_allowed",
                                "ethics_statement_required",
                                "has_ftes",
                                "has_online_scoring",
                                "has_referees",
                                "has_title",
                                "letter_of_support_required",
                                "member_letter_of_support_required",
                                "member_cv_required",
                                "member_research_experience_in_years_required",
                                "nomination_form_required",
                                "nominator_cv_required",
                                "notify_nominator",
                                "pid_required",
                                "presentation_required",
                                "referee_cv_required",
                                "research_experience_in_years_required",
                                "research_summary_required",
                                "team_can_apply",
                                "testimonials_required",
                                # "is_partial_profile_allowed",
                            ]
                            if f not in exclude
                        ],
                        (
                            "required_referees",
                            "is_flexible_number_of_referees",
                            "required_submitted_testimonials",
                        ),
                    ]
                },
            ),
            (
                "Categories",
                {
                    "fields": [
                        "has_fors",
                        "has_keywords",
                        "has_seos",
                        "has_toas",
                        "has_vmts",
                    ]
                },
            ),
            (
                "Terms and Conditions and Declarations",
                {
                    "classes": ("collapse",),
                    "fields": [
                        "tac_en",
                        "tac_mi",
                        "applicant_declaration",
                        "agent_declaration",
                    ],
                },
            ),
            (
                "Contract Options",
                {
                    "classes": ("collapse",),
                    "fields": [
                        ("proposed_start_date_stats_on", "duration"),
                        "awarded_amount",
                        "contract_background",
                        "schedule2",
                        "appendix_a",
                        "appendix_b",
                    ],
                },
            ),
            (
                "Reporting Options",
                {
                    "classes": ("collapse",),
                    "fields": [
                        (
                            "final_report_deferral"
                            if site_id in [2, 4, 5]
                            else ("report_template", "final_report_deferral")
                        ),
                    ],
                },
            ),
            (
                (
                    "Other Templates",
                    {
                        "fields": [
                            "referee_template",
                        ]
                    },
                )
                if site_id in [2, 4, 5]
                else (
                    "Templates",
                    {
                        "fields": [
                            "application_template",
                            "score_sheet_template",
                            "nomination_template",
                            "referee_template",
                            "budget_template",
                        ]
                    },
                )
            ),
        ]
        return fieldsets

    @admin.action(description="Export for the panellists")
    def export_for_panellists(self, request, queryset):
        if queryset.count() > 1:
            for r in queryset:
                r.export(
                    request=request,
                    by=request.user,
                    file_format="7z",
                    sync=False,
                    regenerate=False,
                    for_panellists=True,
                )
            # messages.error(request, "Please select a single round entry.")
            return

        r = queryset.first()
        url = reverse("round-application-export", kwargs={"pk": r.pk})
        url = f"{url}?for_panellists=1&format=7z"
        return redirect(url)

    @admin.action(description="Create new round")
    def create_new_round(self, request, queryset):
        # for r in queryset.filter():
        #     nr = r.clone(copy=True)
        #     r.scheme.current_round = nr
        #     r.scheme.save(update_fields=["current_round"])
        new_rounds = []
        with transaction.atomic():
            for r in queryset:
                nr = r.clone(copy=True)
                r.scheme.current_round = nr
                r.scheme.save(update_fields=["current_round"])
                new_rounds.append(nr)
        if new_rounds:
            new_rounds = [f"{r}" for r in new_rounds]
            messages.info(request, f"New round(s) created: {', '.join(new_rounds)}")

    @admin.action(description="Sync with the LimeSurvey surveys")
    def sync_referee_surveys(self, request, queryset):
        count = 0
        q = queryset.filter(survey_id__isnull=False)
        for r in q:
            count += r.sync_referee_surveys(request=request)
        if not count:
            messages.warning(request, "All referees were already synced.")
        if q.count() > 1:
            messages.info(request, f"In total synced {count} referee(s)")

    @admin.action(description="Invite referees")
    def invite_referees(self, request, queryset):
        if request.site_id not in [2, 5] or "do_action" in request.POST:
            invitation_count = models.invite_referees(
                request=request,
                by=request.user,
                rounds=queryset,
                after_round_closes=("force" not in request.POST)
                or (request.POST.get("force") != "1"),
            )
            messages.success(
                request, f"{invitation_count} referee invitation(s) created and/or dispatched."
            )
            return

        return render(
            request,
            "action_invite_referees.html",
            {
                "title": "Invite referees",
                "objects": queryset,
                "action_label": self.get_action("invite_referees")[-1],
                "rounds": queryset,
            },
        )

    def get_actions(self, request):
        actions = super().get_actions(request)
        if settings.SITE_ID not in [2, 5] and "invite_referees" in actions:
            del actions["invite_referees"]
        return actions

    @admin.action(description="Mark the rounds current")
    def make_current(self, request, queryset):
        schemes = []
        for r in queryset.order_by("-pk"):
            s = r.scheme
            if s.current_round != r:
                if s in schemes:
                    messages.warning(
                        request,
                        f"The scheme {s} is already changes; its current round is {s.current_round} "
                        "(one of the selected rounds)",
                    )
                s.current_round = r
                s._change_reason = f"Round {r} marked as currnt round of {s} by {request.user}"
                schemes.append(s)
        if schemes:
            models.Scheme.all_objects.bulk_update(
                schemes,
                ["current_round"],
            )
            messages.success(
                request, f"The scheme(s) {', '.join(str(s) for s in schemes)} were/was updated."
            )
        else:
            messages.warning(request, "No round was updated...")

    @admin.action(description='Copy performance indicators/flags form another "source" round')
    def copy_performance_indicators(self, request, queryset):
        if "do_action" in request.POST:
            errors = []
            count = 0
            if selected_id := request.POST.get("chosen_object"):
                selected_object = self.model.get(selected_id)

                try:
                    with transaction.atomic():

                        field_names = ["name", "value_choices", "is_optional"]
                        for r in queryset.filter(~Q(id=selected_id)):

                            flags = [
                                f
                                for f in selected_object.performance_flags.all().values(
                                    *field_names
                                )
                                if f not in r.performance_flags.all().values(*field_names)
                            ]
                            if len(flags):
                                count += len(flags)
                                flags = [models.PerformanceFlag(round=r, **f) for f in flags]
                                for pf in flags:
                                    pf._change_reason = (
                                        "Performance flag copied from the round "
                                        f"{selected_object} by {request.user}"
                                    )
                                selected_object.performance_flags.model.objects.bulk_create(flags)

                except Exception as ex:
                    capture_exception(ex)
                    errors.append(ex)

            if count > 1:
                messages.success(
                    request,
                    f"{count} performance indicators/flags copied to the selected rounds",
                )

            if errors:
                for e in errors:
                    messages.error(request, e)

            return

        # Get the code object from the frame and then the name
        return render(
            request,
            "action_select_item.html",
            {
                "title": "Choose source round to copy performance indicators/flags from",
                "item_label": "Choose source round to copy performance indicators/flags from",
                "objects": queryset,
                "objects_with_labels": [
                    (r, f"{r} ({r.flag_count})")
                    for r in queryset.annotate(flag_count=models.Count("performance_flags"))
                ],
                "action_name": inspect.currentframe().f_code.co_name,
                "first_item": queryset.filter(performance_flags__isnull=False).first()
                or queryset.first(),
                # "schemes": models.Scheme.objects.order_by("code", "title").all(),
            },
        )

    @admin.action(description="Copy and link to another scheme")
    def copy_round(self, request, queryset):

        if "do_action" in request.POST:
            errors = []
            if target_id := request.POST.get("target"):
                target = models.Scheme.get(target_id)
                rounds = list(queryset.filter(~Q(scheme_id=target_id)))
                new_rounds = []

                try:
                    with transaction.atomic():

                        for r in rounds:
                            nr = r.clone(scheme=target, copy=True)
                            new_rounds.append(nr)
                            target.current_round = nr
                            target.save(update_fields=["current_round", "updated_at"])

                except Exception as ex:
                    capture_exception(ex)
                    errors.append(ex)

            if len(new_rounds) == 1:
                messages.success(
                    request,
                    f"Round {new_rounds[0]} copied and linked to the scheme {target}",
                )
            else:
                messages.success(
                    request,
                    f'{len(new_rounds)} rounds copied and linked to the scheme {target}: {", ".join(new_rounds)}',
                )

            if errors:
                for e in errors:
                    messages.error(request, e)

            return

        return render(
            request,
            "action_copy_round.html",
            {
                "title": "Choose target scheme",
                "objects": queryset,
                "first_round": queryset.first(),
                "schemes": models.Scheme.objects.order_by("code", "title").all(),
            },
        )

    @admin.display(description=_("applications"), ordering="application_count")
    def application_count(self, obj):
        if obj.application_count:
            return mark_safe(
                f'<a href="{reverse("admin:portal_application_changelist")}'
                f'?round__id__exact={obj.pk}" target="_blank">{obj.application_count or 0}</a>'
            )

    @admin.display(description=_("contracts"), ordering="contract_count")
    def contract_count(self, obj):
        if obj.contract_count:
            return mark_safe(
                f'<a href="{reverse("admin:portal_contract_changelist")}'
                f'?application__round__id__exact={obj.pk}" target="_blank">{obj.contract_count}</a>'
            )

    @admin.display(description=_("reports"), ordering="report_count")
    def report_count(self, obj):
        if obj.report_count:
            return mark_safe(
                f'<a href="{reverse("admin:portal_report_changelist")}'
                f'?schedule_entry__contract__application__round__id__exact={obj.pk}" target="_blank">{obj.report_count or 0}</a>'
            )

    @cache
    def is_active(self, obj):
        return obj.is_active

    is_active.boolean = True

    @admin.display(description=_("survey"), ordering="survey_id")
    def survey(self, obj):
        if (survey_id := obj.survey_id) and (server_url := obj.survey_server_url):
            return mark_safe(
                f'<a href="{server_url}/surveyAdministration/view?iSurveyID={survey_id}&allowRedirect=1" '
                f'target="_bland">{survey_id}</a>'
            )

    @admin.display(description=_("tittle"), ordering="title")
    def coloured_title(self, obj):
        title = obj.title or obj.scheme.title
        if obj.background or obj.foreground and obj.foreground != "colour":
            if obj.foreground and obj.background:
                return format_html(
                    '<span style="background-color: {}; color: {};">{}</span>',
                    obj.background,
                    obj.foreground,
                    title,
                )
            elif obj.foreground and obj.foreground != "colour":
                return format_html(
                    '<span color: {};">{}</span>',
                    obj.foreground,
                    title,
                )
            else:
                return format_html(
                    # '<span style="background-color: {}; color: white;">{}</span>',
                    '<span style="background-color: {};">{}</span>',
                    obj.background,
                    title,
                )
        return title

    def view_on_site(self, obj):
        return f"{reverse('applications')}?round={obj.id}"

    class ApplicationFormTemplateInline(StaffPermsMixin, admin.TabularInline):
        extra = 0
        model = models.ApplicationFormTemplate
        view_on_site = False

    class CurriculumVitaeTemplateInline(StaffPermsMixin, admin.TabularInline):
        extra = 0
        model = models.CurriculumVitaeTemplate
        view_on_site = False

    class RequiredDocumentInline(
        StaffPermsMixin, OrderableAdmin, modeltranslation.admin.TranslationTabularInline
    ):
        extra = 0
        model = models.RequiredDocument
        exclude = ["document_type"]
        # autocomplete_fields = ["document_type"]
        view_on_site = False
        ordering_field_hide_input = True

    class TemplateInline(StaffPermsMixin, admin.TabularInline):
        extra = 0
        model = models.RoundDocumentTemplate
        # autocomplete_fields = ["document_type"]
        view_on_site = False
        exclude = ["document_type"]

    class PanellistInline(StaffPermsMixin, admin.TabularInline):
        extra = 0
        model = models.Panellist
        exclude = [
            "site",
        ]

        def view_on_site(self, obj):
            return reverse("panellist-invite", kwargs={"round": obj.round_id})

    class CriterionInline(StaffPermsMixin, modeltranslation.admin.TranslationStackedInline):
        extra = 0
        model = models.Criterion

        def view_on_site(self, obj):
            return reverse("scores-list", kwargs={"round": obj.round_id})

    class RequiredContractDocumentInline(
        StaffPermsMixin, OrderableAdmin, modeltranslation.admin.TranslationTabularInline
    ):
        extra = 0
        model = models.RequiredContractDocument
        form = RequiredContractDocumentForm
        # autocomplete_fields = ["document_type"]
        view_on_site = False
        ordering_field_hide_input = True
        classes = ["collapse"]

    class RoundContractClauseInline(
        SummernoteModelAdminMixin, StaffPermsMixin, OrderableAdmin, admin.TabularInline
    ):
        extra = 0
        model = models.RoundContractClause
        # autocomplete_fields = ["document_type"]
        view_on_site = False
        ordering_field_hide_input = True
        classes = ["collapse"]

    class PerformanceFlagInline(StaffPermsMixin, OrderableAdmin, admin.TabularInline):
        extra = 0
        model = models.PerformanceFlag
        view_on_site = False
        ordering_field_hide_input = True
        classes = ["collapse"]

    class ReportTemplateInline(StaffPermsMixin, OrderableAdmin, admin.TabularInline):
        extra = 0
        model = models.ReportTemplate
        view_on_site = False
        ordering_field_hide_input = True

    def get_inlines(self, request, obj):
        if (site_id := obj and obj.site_id or settings.SITE_ID) and site_id in [2, 4, 5]:
            return [
                self.RequiredDocumentInline,
                self.TemplateInline,
                # self.CurriculumVitaeTemplateInline,
                self.CriterionInline,
                self.PanellistInline,
                self.RequiredContractDocumentInline,
                self.RoundContractClauseInline,
                self.PerformanceFlagInline,
                self.ReportTemplateInline,
            ]

        return [
            self.ApplicationFormTemplateInline,
            self.CurriculumVitaeTemplateInline,
            self.CriterionInline,
            self.PanellistInline,
            self.RequiredContractDocumentInline,
            self.RoundContractClauseInline,
            self.PerformanceFlagInline,
            self.ReportTemplateInline,
        ]


class IsActiveRoundEvaluationListFilter(admin.SimpleListFilter):
    title = "Is Active Round"

    parameter_name = "is_active_round"

    def get_facet_counts(self, pk_attname, filtered_qs):

        return {
            "ACTIVE__c": models.Count(
                pk_attname,
                filter=Q(application__round__scheme__current_round__id=F("application__round_id")),
            ),
            "PREVIOUS__c": models.Count(
                pk_attname,
                filter=~Q(
                    application__round__scheme__current_round__id=F("application__round_id")
                ),
            ),
            "All__c": models.Count(pk_attname),
        }

    def choices(self, changelist):

        add_facets = changelist.add_facets
        facet_counts = self.get_facet_queryset(changelist) if add_facets else None

        yield {
            "selected": self.value() == "ACTIVE" or self.value() is None,
            "query_string": changelist.get_query_string(remove=[self.parameter_name]),
            "display": f"ACTIVE ({facet_counts['ACTIVE__c']})" if add_facets else "ACTIVE",
        }
        for lookup, title in self.lookup_choices:
            v = self.value()
            c = facet_counts and facet_counts.get(f"{lookup}__c", 0)
            yield {
                "selected": v == str(lookup),
                "query_string": changelist.get_query_string({self.parameter_name: lookup}),
                "display": f"{title} ({c})" if add_facets else title,
            }

    def lookups(self, request, model_admin):
        return (
            ("PREVIOUS", _("Previous")),
            ("All", _("All")),
        )

    def queryset(self, request, queryset):
        if self.value() == "ACTIVE" or self.value() is None:
            return queryset.filter(
                application__round__scheme__current_round__id=F("application__round_id")
            )
        if self.value() == "PREVIOUS":
            return queryset.filter(
                ~Q(application__round__scheme__current_round__id=F("application__round_id"))
            )
        return queryset


@admin.register(models.Evaluation)
class EvaluationAdmin(StaffPermsMixin, FSMTransitionMixin, HistoryAdmin):
    save_on_top = True

    list_filter = [
        IsActiveRoundEvaluationListFilter,
        ("application__round__scheme", admin.RelatedOnlyFieldListFilter),
        "state",
    ]
    search_fields = [
        "application__number",
        "panellist__email",
        "panellist__first_name",
        "panellist__last_name",
        "panellist__user__first_name",
        "panellist__user__last_name",
    ]

    date_hierarchy = "updated_at"

    list_display = (
        "application__number",
        "panellist",
        "application_url",
        "state",
        "updated_at",
    )
    # list_display_links = ["appliation__number", "panellist", ]
    autocomplete_fields = ["application"]

    @admin.display(description="application", ordering="application__number")
    def application_url(self, obj):
        a = obj.application
        return mark_safe(
            '<a href="%s" target="_blank">%s</a>'
            % (
                reverse(
                    "admin:portal_application_change",
                    kwargs={"object_id": obj.application_id},
                ),
                f"{a.number}: {a.pi}",
            )
        )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(application__site_id=settings.SITE_ID)

    class ScoreInline(StaffPermsMixin, admin.StackedInline):
        extra = 0
        model = models.Score
        view_on_site = False

        def view_on_site(self, obj):
            return reverse("scores-list", kwargs={"round": obj.criterion.round_id})

    inlines = [ScoreInline, StateLogInline]


class ContractDocumentForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        if self.request and (r := self.instance.round):

            self.fields["author"].initial = self.request.user

    class Meta:
        model = models.ContractDocument
        fields = "__all__"


@admin.register(models.Contract)
class ContractAdmin(
    UnaccentMixin, StaffPermsMixin, SummernoteModelAdminMixin, FSMTransitionMixin, HistoryAdmin
):
    summernote_fields = (
        "abstract",
        # "notes",
    )
    save_on_top = True
    show_close_button = True

    list_display = (
        "number",
        "application_link",
        # "category",
        "fund",
        "project_title",
        "state",
    )

    list_filter = (
        ("fund", admin.RelatedOnlyFieldListFilter),
        ("application__round", admin.RelatedOnlyFieldListFilter),
        "state",
    )
    # list_filter = [
    #     IsActiveRoundApplicationListFilter,
    #     ("org", admin.RelatedOnlyFieldListFilter),
    #     ("panel", admin.RelatedOnlyFieldListFilter),
    #     "state",
    #     "created_at",
    #     "updated_at",
    # ]
    search_fields = [
        "number",
        "application__number",
        "project_title",
        "members__email",
        "members__first_name",
        "members__last_name",
    ]
    autocomplete_fields = [
        # "principal",
        # "coordinator",
        "fund",
        "panels",
        "application",
        # "source",
        # "supervisor",
        "rccs",
        "seos",
        # "seo_keywords",
        "address",
        "org",
        "priorities",
    ]
    fieldsets = [
        (
            None,
            {
                "fields": [
                    ("state", "completed_on", "is_variation"),
                    ("number", "refcode", "year"),
                    "project_title",
                    # ("source", "source_code"),
                    ("org", "application", "round_link"),
                    # ("proposal", "proposal_number"),
                    # ("principal", "principal_code"),
                    # ("coordinator", "coordinator_code"),
                    # ("supervisor", "supervisor_code"),
                    ("start_date", "end_date", "duration"),
                    # "category",
                    # ("fund", "fund_code"),
                    ("fund", "awarded_amount"),
                    ("fin_received", "fin_supp"),
                    # "code",
                ],
            },
        ),
        (
            "Contact Information",
            {
                "classes": ("collapse",),
                "fields": [
                    "address",
                    "contact",
                    "contact_phone",
                    "host_contact_email",
                ],
            },
        ),
        (
            "Compliance",
            {
                "classes": ("collapse",),
                "fields": [
                    "ethics_statement_link",
                    "has_animal_use",
                    "is_signatory_to_oa",
                    "involves_children",
                    "has_child_protection",
                    "requires_approval",
                ],
            },
        ),
        (
            "Additional Information",
            {
                "classes": ("collapse",),
                "fields": [
                    # "panel_code",
                    "panel",
                    # ("total_amount", "actual_amount", "currency"),
                    "url",
                    "abstract",
                    # "notes",
                    # "mf_round_yr",
                    # "seo_list",
                    # "keyword_list",
                    # "seo_keyword_list",
                ],
            },
        ),
        (
            "Categories",
            {
                "classes": ("collapse",),
                "fields": [
                    ("keywords", "priorities"),
                ],
            },
        ),
        (
            "Vision Mātauranga",
            {
                "classes": ("collapse",),
                "fields": [
                    "vm_ecs",
                    "vm_ens",
                    "vm_hsw",
                    "vm_ink",
                    # "is_vm_na",
                    # "vm_rationale",
                ],
            },
        ),
        (
            "Type of Activity",
            {
                "classes": ("collapse",),
                "fields": [
                    "toa_applied",
                    "toa_basic",
                    "toa_strategic",
                    "toa_experimental",
                ],
            },
        ),
    ]
    readonly_fields = ["ethics_statement_link", "round_link"]

    @admin.display(description="ethics statement")
    def ethics_statement_link(self, obj):
        if es := obj.parts.filter(document_type__role="E").last():
            return mark_safe(
                es.file and f'<a href="{es.file.url}">{os.path.basename(es.file.name)}</a>' or "-"
            )
        return "-"

    @admin.display(description="application", ordering="application__number")
    def application_link(self, obj):
        a = obj.application
        return mark_safe(
            a
            and f"""<a href="{reverse('admin:portal_application_change', kwargs={"object_id": a.pk})}?_popup=1" target="_blank">
            {a.number}
            </a>"""
            or "-"
        )

    @admin.display(description="round")
    def round_link(self, obj):
        return mark_safe(
            '<a href="{}?_popup=1" target="_blank">{}</a>'.format(
                reverse("admin:portal_round_change", args=(obj.application.round_id,)),
                obj.application.round,
            )
        )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("fund", "application")

    # class TeamInline(admin.StackedInline):
    #     model = models.ContractTeam
    #     extra = 0
    #     view_on_site = False
    #     autocomplete_fields = ["person", "country"]
    #     exclude = ["contract_number"]
    #     classes = ["collapse"]

    # class ReportingInline(admin.StackedInline):
    #     model = models.ContractReporting
    #     exclude = ["contract_number"]
    #     extra = 0
    #     view_on_site = False
    #     classes = ["collapse"]

    class EthicsStatementInline(StaffPermsMixin, admin.StackedInline):
        model = models.ContractEthicsStatement
        # exclude = ["contract_number"]
        extra = 0
        view_on_site = False
        # classes = ["collapse"]

    class ContractDocumentInline(StaffPermsMixin, admin.TabularInline):
        model = models.ContractDocument
        # form = ContractDocumentForm
        exclude = ["converted_file", "document_type"]
        extra = 0
        view_on_site = False
        classes = ["collapse"]

        def formfield_for_foreignkey(self, db_field, request, **kwargs):
            # if db_field.name == "document_type":
            #     kwargs["queryset"] = models.Application.objects.filter(site_id=settings.SITE_ID)
            if db_field.name == "required_document":
                if (m := re.search(r"contract/(\d+)/change", request.path)) and (
                    contract_id := m.group(1)
                ):
                    kwargs["queryset"] = models.RequiredContractDocument.where(
                        Q(documents__contract_id=contract_id)
                        | Q(round__applications__contracts=contract_id)
                    ).distinct()
            return super().formfield_for_foreignkey(db_field, request, **kwargs)

    class ReportingScheduleEntryInline(StaffPermsMixin, admin.TabularInline):
        model = models.ReportingScheduleEntry
        extra = 0
        view_on_site = False
        classes = ["collapse"]

    class ContractClauseInline(
        SummernoteModelAdminMixin, StaffPermsMixin, OrderableAdmin, admin.TabularInline
    ):
        extra = 0
        model = models.ContractClause
        # autocomplete_fields = ["document_type"]
        view_on_site = False
        ordering_field_hide_input = True
        classes = ["collapse"]

    class CommentInline(StaffPermsMixin, admin.TabularInline):
        model = models.ContractComment
        extra = 0
        can_delete = True
        view_on_site = False
        fields = ["created_at", "submitted_by", "html_comment", "attachment_link"]
        readonly_fields = ["created_at", "html_comment", "submitted_by", "attachment_link"]
        classes = ["collapse"]

        def has_change_permission(self, request, obj):
            return False

        def has_add_permission(self, request, obj):
            return False

        @admin.display(description=_("comment"))
        def html_comment(self, obj):
            return mark_safe(obj.comment or "-")

        @admin.display(description=_("attachment"))
        def attachment_link(self, obj):
            return mark_safe(
                obj.attachment
                and f'<a href="{obj.attachment.url}">{os.path.basename(obj.attachment.name)}</a>'
                or "-"
            )

    # class PanelAllocationInline(admin.StackedInline):
    #     model = models.ContractPanelAllocation
    #     extra = 0
    #     view_on_site = False
    #     autocomplete_fields = ["panel"]
    #     classes = ["collapse"]

    # class VisitInline(admin.StackedInline):
    #     model = models.ContractVisit
    #     extra = 0
    #     view_on_site = False
    #     classes = ["collapse"]

    # class ExchangeInline(admin.StackedInline):
    #     model = models.ContractExchange
    #     extra = 0
    #     view_on_site = False
    #     autocomplete_fields = ["country"]
    #     exclude = ["contract_number"]
    #     classes = ["collapse"]

    # class EventInline(admin.StackedInline):
    #     model = models.ContractEvent
    #     extra = 0
    #     view_on_site = False
    #     autocomplete_fields = ["from_country", "to_country"]
    #     exclude = ["contract_number"]
    #     classes = ["collapse"]

    # class LogInline(admin.TabularInline):
    #     model = models.ContractLog
    #     extra = 0
    #     view_on_site = False
    #     # autocomplete_fields = ["from_country", "to_country"]
    #     readonly_fields = ["contract_number", "logged_by", "logged_on"]
    #     exclude = ["contract_number"]
    #     classes = ["collapse"]

    class AllocationInline(StaffPermsMixin, admin.TabularInline):
        model = models.Allocation
        extra = 0
        view_on_site = False
        classes = ["collapse"]

    class ForInline(StaffPermsMixin, admin.TabularInline):
        model = models.ContractFor
        extra = 0
        view_on_site = False
        autocomplete_fields = ["code"]
        classes = ["collapse"]

    class SeoInline(StaffPermsMixin, admin.TabularInline):
        model = models.ContractSeo
        autocomplete_fields = ["code"]
        extra = 0
        view_on_site = False
        classes = ["collapse"]

    # class KeywordInline(StaffPermsMixin, admin.TabularInline):
    #     model = models.ContractKeyword
    #     autocomplete_fields = ["keyword"]
    #     extra = 0
    #     view_on_site = False
    #     classes = ["collapse"]

    class MemberInline(StaffPermsMixin, admin.TabularInline):
        extra = 0
        model = models.ContractMember
        autocomplete_fields = ["user", "address"]
        fields = ["view_on_site_link", "email", "first_name", "last_name", "role", "is_funded"]

        readonly_fields = ("view_on_site_link",)

        # view_on_site = False
        def view_on_site_link(self, obj):
            if obj.pk:
                url = reverse("admin:portal_contractmember_change", kwargs={"object_id": obj.pk})
                return format_html('<a href="{}?is_popup=1" target="_blank">Edit</a>', url)
            return "-"

        view_on_site_link.short_description = "Edit"

    inlines = [
        MemberInline,
        EthicsStatementInline,
        ContractDocumentInline,
        ReportingScheduleEntryInline,
        AllocationInline,
        SeoInline,
        ForInline,
        # KeywordInline,
        # TeamInline,
        # AllocationInline,
        # ReportingInline,
        # VisitInline,
        # ExchangeInline,
        # EventInline,
        # LogInline,
        CommentInline,
        ContractClauseInline,
        StateLogInline,
    ]

    @admin.action(description="Link Documents (copy missing documents from the application)")
    def link_documents(self, request, queryset, *args, **kwargs):
        missing_documents = (
            models.ApplicationDocument.where(
                application__contracts__in=queryset,
                required_document__contract_required_documents__isnull=False,
                required_document__contract_required_documents__documents__isnull=True,
                application__contracts__isnull=False,
            )
            .annotate(
                contract=F("application__contracts"),
                contract_required_document=F("required_document__contract_required_documents"),
            )
            .order_by("contract")
        )
        documents = [
            models.ContractDocument(
                contract_id=d.contract,
                page_count=d.page_count or d.update_page_count(),
                document_type=d.document_type
                or d.document_type
                or d.required_document.document_type,
                required_document_id=d.contract_required_document,
                file=d.file,
                converted_file=d.converted_file,
                state="draft",
            )
            for d in missing_documents
        ]
        documents = bulk_create_with_history(
            documents,
            models.ContractDocument,
            ignore_conflicts=True,
            default_user=request.user,
            default_change_reason=f"{request.user} re-linked/copied the missing contract documents from the contract applications",
        )
        contracts = set(d.contract for d in documents)

        if not len(documents):
            messages.warning(
                request,
                "No documents were linked; make sure the contract required documents are linked to the application required documents.",
            )
            return
        messages.info(
            request,
            mark_safe(
                f"{len(documents)} documents linked; updated contract(s): "
                + ", ".join(f'<a href="{c.update_url}" target="_blank">{c}</a>' for c in contracts)
            ),
        )

    @admin.action(description="Start Reporting")
    def start_reporting(self, request, queryset, *args, **kwargs):
        reports = list(
            self.model.start_reporting(request=request, queryset=queryset, *args, **kwargs)
        )
        if not reports:
            messages.warning(request, "No report was initiated.")
            return
        messages.info(
            request,
            mark_safe(
                f"New report(s) initiated: "
                + ", ".join(f'<a href="{r.update_url}" target="_blank">{r}</a>' for r in reports)
            ),
        )

    actions = [
        start_reporting,
        refresh_page_counts,
        link_documents,
        archive_objects,
        revert_object_states,
    ]

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj=obj, change=change, **kwargs)
        form.base_fields["priorities"].widget = autocomplete.TaggitSelect2(
            url="research-priority-autocomplete",
            forward=[
                dal.forward.Const(obj and obj.application.round_id, "round"),
                dal.forward.Const("contract", "model"),
            ],
        )
        form.base_fields["keywords"].widget = widget = (
            autocomplete.ModelSelect2Multiple(  # autocomplete.TaggitSelect2(
                url="keyword-autocomplete",
                # forward=[
                #     dal.forward.Const(obj and obj.application.round_id, "round"),
                #     dal.forward.Const("contract", "model"),
                # ],
            )
        )
        return form


@admin.register(models.Publication)
class PublicationAdmin(StaffPermsMixin, HistoryAdmin):
    save_on_top = True
    show_close_button = True

    list_display = (
        # "number",
        # "category",
        # "fund",
        "title",
        "status",
        # "application",
    )

    class AuthorInline(admin.StackedInline):
        # model = models.Report.publications.through
        model = models.PublicationAuthor
        # exclude = ["contract_number"]
        extra = 0
        view_on_site = False
        classes = ["collapse"]

    class LinkInline(admin.StackedInline):
        # model = models.Report.publications.through
        model = models.PublicationLink
        # exclude = ["contract_number"]
        extra = 0
        view_on_site = False
        classes = ["collapse"]

    inlines = [AuthorInline, LinkInline]

    list_filter = [
        ("type", admin.RelatedOnlyFieldListFilter),
        ("status", admin.RelatedOnlyFieldListFilter),
    ]


@admin.register(models.Report)
class ReportAdmin(StaffPermsMixin, FSMTransitionMixin, PdfFileAdminMixin, HistoryAdmin):
    save_on_top = True
    show_close_button = True
    date_hierarchy = "created_at"

    actions = [archive_objects, revert_object_states, "assign_yourself"]

    @admin.action(description="Assign yourself")
    def assign_yourself(self, request, queryset, *args, **kwargs):
        u = request.user
        assigned_reports = list(queryset.filter(assessor__isnull=True, state="acknowledged"))
        if assigned_reports:
            for r in assigned_reports:
                r.assign_assessor(request=request, by=u, assessor=u)
            bulk_update_with_history(
                assigned_reports,
                self.model,
                ["state", "state_changed_at", "updated_at", "assessor"],
                default_user=u,
                default_change_reason=f"User {u} assigned themselves...",
                manager=self.model.objects,
            )

    list_display = (
        # "number",
        # "category",
        # "fund",
        "contract",
        "type",
        "period",
        "reported_at",
        # "application",
        "state",
        "assessor",
    )

    list_filter = [
        "state",
        "type",
        # "schedule_entry__contract__application__round",
        ("schedule_entry__contract__application__round", admin.RelatedOnlyFieldListFilter),
    ]
    # list_filter = (
    #     ("state", admin.RelatedOnlyFieldListFilter),
    #     ("type", admin.RelatedOnlyFieldListFilter),
    # )
    search_fields = [
        "contract__project_title",
        "contract__number",
        "contract__application__number",
    ]
    autocomplete_fields = [
        "assessor",
        "contract",
        # "schedule_entry",
        # "principal",
        # "coordinator",
        # "fund",
        # "panels",
        # "application",
        # "source",
        # "supervisor",
        "fors",
        # "rccs",
        # "seos",
        # "seo_keywords",
    ]
    fieldsets = [
        (
            None,
            {
                "fields": [
                    (
                        "STATE",
                        # "type",
                        "contract",
                        # "period",
                        "schedule_entry",
                    ),
                    "assessor",
                    # ("number", "refcode", "year"),
                    # "project_title",
                    # "host_contact_email",
                    # ("source", "source_code"),
                    # ("org", "contract"),
                    # ("proposal", "proposal_number"),
                    # ("principal", "principal_code"),
                    # ("coordinator", "coordinator_code"),
                    # ("supervisor", "supervisor_code"),
                    # ("start_date", "end_date", "duration"),
                    # "category",
                    # ("fund", "fund_code"),
                    # "fund",
                    # ("fin_received", "fin_supp"),
                    # "code",
                ],
            },
        ),
        # (
        #     "Compliance",
        #     {
        #         "classes": ("collapse",),
        #         "fields": [
        #             "ethics_statement_link",
        #             "has_animal_use",
        #             "is_signatory_to_oa",
        #             "involves_children",
        #             "has_child_protection",
        #         ],
        #     },
        # ),
        (
            "Categories",
            {
                "classes": ("collapse",),
                "fields": [
                    ("keywords", "priorities"),
                ],
            },
        ),
        (
            "Vision Mātauranga",
            {
                "classes": ("collapse",),
                "fields": [
                    "vm_ecs",
                    "vm_ens",
                    "vm_hsw",
                    "vm_ink",
                    # "is_vm_na",
                    # "vm_rationale",
                ],
            },
        ),
        (
            "Type of Activity",
            {
                "classes": ("collapse",),
                "fields": [
                    "toa_applied",
                    "toa_basic",
                    "toa_strategic",
                    "toa_experimental",
                ],
            },
        ),
    ]
    readonly_fields = ["STATE", "contract"]

    # @admin.display(description="ethics statement")
    # def ethics_statement_link(self, obj):
    #     if es := obj.parts.filter(document_type__role="E").last():
    #         return mark_safe(
    #             es.file and f'<a href="{es.file.url}">{os.path.basename(es.file.name)}</a>' or "-"
    #         )
    #     return "-"

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("contract").select_related("contract__application__round")

    class PublicationInline(admin.StackedInline):
        # model = models.Report.publications.through
        model = models.Report.publications.through
        # exclude = ["contract_number"]
        extra = 0
        view_on_site = False
        classes = ["collapse"]

    class ReportedEffortInline(admin.StackedInline):
        model = models.ReportedEffort
        extra = 0
        view_on_site = False
        autocomplete_fields = ["person"]
        classes = ["collapse"]

    class ReportedFundingInline(admin.StackedInline):
        model = models.ReportedFunding
        extra = 0
        view_on_site = False
        autocomplete_fields = ["agency"]
        classes = ["collapse"]

    # class ReportingInline(admin.StackedInline):
    #     model = models.ContractReporting
    #     exclude = ["contract_number"]
    #     extra = 0
    #     view_on_site = False
    #     classes = ["collapse"]

    # class EthicsStatementInline(admin.StackedInline):
    #     model = models.ContractEthicsStatement
    #     # exclude = ["contract_number"]
    #     extra = 0
    #     view_on_site = False
    #     # classes = ["collapse"]

    # class ContractDocumentInline(admin.TabularInline):
    #     model = models.ContractDocument
    #     # exclude = ["contract_number"]
    #     extra = 0
    #     view_on_site = False
    #     classes = ["collapse"]

    # class ReportingScheduleEntryInline(admin.TabularInline):
    #     model = models.ReportingScheduleEntry
    #     extra = 0
    #     view_on_site = False
    #     classes = ["collapse"]

    # class CommentInline(admin.TabularInline):
    #     model = models.ContractComment
    #     extra = 0
    #     can_delete = False
    #     view_on_site = False
    #     fields = ["created_at", "submitted_by", "html_comment", "attachment_link"]
    #     readonly_fields = ["created_at", "html_comment", "submitted_by", "attachment_link"]
    #     classes = ["collapse"]

    #     def has_change_permission(self, request, obj):
    #         return False

    #     def has_add_permission(self, request, obj):
    #         return False

    #     @admin.display(description=_("comment"))
    #     def html_comment(self, obj):
    #         return mark_safe(obj.comment or "-")

    #     @admin.display(description=_("attachment"))
    #     def attachment_link(self, obj):
    #         return mark_safe(
    #             obj.attachment
    #             and f'<a href="{obj.attachment.url}">{os.path.basename(obj.attachment.name)}</a>'
    #             or "-"
    #         )

    # class PanelAllocationInline(admin.StackedInline):
    # class PanelAllocationInline(admin.StackedInline):
    #     model = models.ContractPanelAllocation
    #     extra = 0
    #     view_on_site = False
    #     autocomplete_fields = ["panel"]
    #     classes = ["collapse"]

    # class VisitInline(admin.StackedInline):
    #     model = models.ContractVisit
    #     extra = 0
    #     view_on_site = False
    #     classes = ["collapse"]

    # class ExchangeInline(admin.StackedInline):
    #     model = models.ContractExchange
    #     extra = 0
    #     view_on_site = False
    #     autocomplete_fields = ["country"]
    #     exclude = ["contract_number"]
    #     classes = ["collapse"]

    # class EventInline(admin.StackedInline):
    #     model = models.ContractEvent
    #     extra = 0
    #     view_on_site = False
    #     autocomplete_fields = ["from_country", "to_country"]
    #     exclude = ["contract_number"]
    #     classes = ["collapse"]

    # class LogInline(admin.TabularInline):
    #     model = models.ContractLog
    #     extra = 0
    #     view_on_site = False
    #     # autocomplete_fields = ["from_country", "to_country"]
    #     readonly_fields = ["contract_number", "logged_by", "logged_on"]
    #     exclude = ["contract_number"]
    #     classes = ["collapse"]

    # class AllocationInline(admin.TabularInline):
    #     model = models.Allocation
    #     extra = 0
    #     view_on_site = False
    #     classes = ["collapse"]

    class ForInline(StaffPermsMixin, admin.TabularInline):
        model = models.ReportFor
        extra = 0
        view_on_site = False
        autocomplete_fields = ["code"]
        classes = ["collapse"]

    class SeoInline(StaffPermsMixin, admin.TabularInline):
        model = models.ReportSeo
        autocomplete_fields = ["code"]
        extra = 0
        view_on_site = False
        classes = ["collapse"]

    inlines = [
        # EthicsStatementInline,
        # ContractDocumentInline,
        # ReportingScheduleEntryInline,
        # AllocationInline,
        ForInline,
        SeoInline,
        PublicationInline,
        ReportedEffortInline,
        ReportedFundingInline,
        # TeamInline,
        # AllocationInline,
        # ReportingInline,
        # VisitInline,
        # ExchangeInline,
        # EventInline,
        # LogInline,
        # CommentInline,
        StateLogInline,
    ]

    def save_model(self, request, obj, form, change):
        if obj.schedule_entry:
            if not obj.type:
                obj.type = obj.schedule_entry.type
            if not obj.period:
                obj.period = obj.schedule_entry.period
        super().save_model(request, obj, form, change)

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj=obj, change=change, **kwargs)
        form.base_fields["priorities"].widget = autocomplete.TaggitSelect2(
            url="research-priority-autocomplete",
            forward=[
                dal.forward.Const(obj and obj.contract.application.round_id, "round"),
                dal.forward.Const("report", "model"),
            ],
        )
        form.base_fields["keywords"].widget = widget = autocomplete.ModelSelect2Multiple(
            url="keyword-autocomplete",
        )
        return form


@admin.register(models.ChangeRequest)
class ChangeRequestAdmin(
    StaffPermsMixin, SummernoteModelAdminMixin, FSMTransitionMixin, HistoryAdmin
):
    summernote_fields = ("description",)
    save_on_top = True
    show_close_button = True
    # autocomplete_fields = ["new_host", "types"]
    autocomplete_fields = [
        "new_host",
        "contract",
        "derivative",
        "submitted_by",
        "converted_file",
    ]

    def view_on_site(self, obj):
        return obj.get_absolute_url()

    list_display = (
        "contract__number",
        "state",
    )


# vim:set ft=python.django:
