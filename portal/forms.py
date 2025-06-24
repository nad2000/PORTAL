import os
from functools import partial
from django.utils import timezone

from crispy_forms.bootstrap import (
    InlineField,
    InlineCheckboxes,
    InlineRadios,
    PrependedText,
    Tab,
    TabHolder,
)
from crispy_forms.helper import FormHelper
from crispy_forms.layout import (
    HTML,
    TEMPLATE_PACK,
    BaseInput,
    Button,
    ButtonHolder,
    Column,
    Div,
    Field,
    Fieldset,
    Hidden,
    Layout,
    LayoutObject,
    Row,
)
from dateutil.relativedelta import relativedelta
from dal import autocomplete, forward
from django import forms
from django.conf import settings

# from crispy_forms.bootstrap import Modal
from django.core.files.base import File
from django.forms import FileField, IntegerField, HiddenInput, Widget, inlineformset_factory
from django.forms.models import BaseInlineFormSet, modelformset_factory
from django.forms.widgets import NullBooleanSelect, NumberInput, Select, TextInput
from django.shortcuts import reverse
from django.template.loader import render_to_string
from django.utils.functional import cached_property
from django.utils.safestring import mark_safe
from django.utils.translation import get_language
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django_summernote.widgets import SummernoteInplaceWidget
from sentry_sdk import capture_message

from . import models
from .models import DOCUMENT_ROLES, Q

# DateInput = partial(
#     forms.DateInput,
#     attrs={
#         "class": "form-control datepicker",
#         "type": "text",
#         "data-date-start-date": "-100y",
#         "data-date-end-date": "-6y",
#     },
# )


class DateInput(forms.DateInput):
    template_name = "portal/widgets/date.html"

    def __init__(self, attrs=None, format=None, start_date=None, end_date=None):
        if not format:
            format = "%Y-%m-%d"

        if not attrs:
            attrs = {}

        if "class" not in attrs:
            attrs["class"] = "form-control datepicker"
        if "type" not in attrs:
            attrs["type"] = "text"
        if "data-date-start-date" not in attrs:
            attrs["data-date-start-date"] = start_date or "-80y"
        if "data-date-end-date" not in attrs:
            attrs["data-date-end-date"] = end_date or "+5y"
        # if "data-date-format" not in attrs:
        #     attrs["data-date-format"] = "yyyy-mm-dd"

        super().__init__(attrs=attrs, format=format)


YearInput = partial(
    DateInput,
    attrs={
        "class": "form-control yearpicker",
        "type": "text",
        "data-date-format": "yyyy",
        "data-date-view-mode": "years",
        "data-date-min-view-mode": "years",
    },
)
# FileInput = partial(FileInput, attrs={"class": "custom-file-input", "type": "file"})
# FileInput = partial(FileInput, attrs={"class": "custom-file-input"})


class InvitationStateInput(Widget):
    # def __init__(self, attrs=None):
    #     super().__init__(attrs)
    #     pass

    template_name = "invitation_state.html"


class OppositeBooleanField(forms.BooleanField):
    def prepare_value(self, value):
        return not value  # toggle the value when loaded from the model

    def to_python(self, value):
        value = super(OppositeBooleanField, self).to_python(value)
        return not value  # toggle the incoming value from form submission


class Submit(BaseInput):
    """Submit button."""

    input_type = "submit"

    def __init__(self, *args, **kwargs):
        self.field_classes = "btn" if "css_class" in kwargs else "btn btn-primary"
        super().__init__(*args, **kwargs)
        self.attrs.update(kwargs)


class TelInput(TextInput):
    input_type = "tel"


class ModelForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        self.site_id = kwargs.pop("site_id", 0) or int(settings.SITE_ID)
        super().__init__(*args, **kwargs)


class ReadOnlyFieldsMixin:
    def get_readonly_fields(self):
        meta = getattr(self, "Meta", None)
        return (
            getattr(self, "readonly_fields", None)
            or meta
            and getattr(meta, "readonly_fields", None)
            or ()
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if readonly_fields := self.get_readonly_fields():
            for field in (field for name, field in self.fields.items() if name in readonly_fields):
                field.widget.attrs["disabled"] = "true"
                field.widget.attrs["readonly"] = "true"
                field.required = False
                field.disabled = True

    # def clean(self):
    #     if readonly_fields := self.get_readonly_fields():
    #         for f in readonly_fields:
    #             self.cleaned_data.pop(f, None)
    #     return super().clean()


class FormWithCommentMixin:
    pass


class CommentForm(FormWithCommentMixin, ModelForm):

    comment = forms.CharField(
        label="",
        required=False,
        widget=SummernoteInplaceWidget(attrs={"summernote": {"width": "100%", "height": "200px"}}),
    )
    attachment = FileField(
        required=False,
        label="",
        widget=forms.ClearableFileInput(
            attrs={
                "accept": (
                    ".xls,.xlw,.xlt,.xml,.xlsx,.xlsm,.xltx,.xltm,.xlsb,.csv,.ctv"
                    ".pdf,.odt,.ott,.oth,.odm,.doc,.docx,.docm,.docb"
                )
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        instance = kwargs.pop("instance", None)
        super().__init__(*args, **kwargs)
        has_contact_email = instance and hasattr(instance, "host_contact_email")
        if has_contact_email:
            self.fields.insert(0, form.TextInput())
        helper = getattr(self, "helper", None) or FormHelper(self)
        # helper.include_media = False
        # helper.form_tag = False
        helper.layout = Layout(
            Field("host_contact_email"),
            Field("comment"),
            Fieldset(
                None,
                Field("attachment"),
                ButtonHolder(
                    Button(
                        "toggle_message_folding",
                        _("Expand/Collapse All"),
                        css_class="btn-outline-secondary",
                        onclick="toggleMessageFolding(this)",
                    ),
                    Submit(
                        "post_comment",
                        _("Post Comment"),
                        css_class="btn-primary",
                    ),
                    Button(
                        "import_email_file",
                        _("Import Email"),
                        hx_get=reverse("email-import", kwargs={"pk": instance and instance.pk})
                        + "?_modal_dialog=1&model=changerequest",
                        hx_target="#form-dialog",
                        hx_params="none",
                        data_toggle="tooltip",
                        title=_("Import an email file as a comment ..."),
                        css_class="btn-outline-primary",
                    ),
                    css_class="float-right",
                ),
            ),
        )
        self.helper = helper


class FormWithStateFieldMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if instance := self.instance:
            attrs = self.fields["state"].widget.attrs
            invitation = getattr(instance, "invitation", None)
            changed_at = (
                invitation
                and invitation.state_changed_at
                or instance.state_changed_at
                or instance.updated_at
            )
            attrs["invitation"] = invitation
            state = invitation and invitation.state or instance.state
            if (
                state == "accepted"
                and instance
                and instance.state
                and instance.state != "new"
                and (state != instance.state or instance.state_changed_at > changed_at)
            ):
                state = instance.state
                changed_at = instance.state_changed_at
            attrs["changed_at"] = changed_at
            attrs["state"] = state
            if state in ["bounced", "autoreplied"] and (error_message := instance.mail_log_error):
                attrs["error_message"] = error_message


class FTEMixin:
    def __init__(self, *args, **kwargs):
        duration = kwargs.pop("duration", None)
        super().__init__(*args, **kwargs)
        if not duration:
            instance = kwargs.get("instance")
            contract = instance and getattr(instance, "contract", None)
            duration = contract and contract.duration
        if duration:
            for i in range(1, duration + 1):
                self.fields[f"fte_{i}"] = forms.DecimalField(
                    required=False,
                    label=f"FTE{i}",
                    max_value=1,
                    min_value=0,
                    max_digits=3,
                    decimal_places=2,
                    initial=self.instance
                    and self.instance.pk
                    and getattr(self.instance, f"fte_{i}", None),
                )

    def save(self, commit=True):
        super().save(commit=commit)
        m = self.instance
        Effort = m.efforts.model
        Effort.objects.bulk_create(
            [
                Effort(member=m, period=int(i), fte=self.cleaned_data[f])
                for (f, (_, i)) in [
                    (f, f.split("_"))
                    for f in self.fields.keys()
                    if f.startswith("fte_") and self.cleaned_data[f]
                ]
            ],
            update_conflicts=True,
            update_fields=["fte"],
            unique_fields=["member", "period"],
        )
        m.efforts.filter(
            period__in=[
                i
                for (_, i) in [
                    f.split("_")
                    for f in self.fields.keys()
                    if f.startswith("fte_") and not self.cleaned_data[f]
                ]
            ]
        ).delete()


class TableInlineFormset(LayoutObject):
    template = "portal/table_inline_formset.html"

    def __init__(self, formset_name_in_context, template=None, *args, **kwargs):
        self.formset_name_in_context = formset_name_in_context
        self.form_id = formset_name_in_context
        self.fields = []
        if template:
            self.template = template

    def render(self, form, form_style, context, template_pack=TEMPLATE_PACK):
        formset = context[self.formset_name_in_context]
        return render_to_string(
            self.template,
            {"formset": formset, "form_id": self.form_id, "use_custom_control": True},
        )


class SubForm(LayoutObject):
    template = "portal/subform.html"

    def __init__(self, form_name_in_context, template=None, *args, **kwargs):
        self.form_name_in_context = form_name_in_context
        self.form_id = form_name_in_context
        self.fields = []
        if template:
            self.template = template

    def render(self, form, form_style, context, template_pack=TEMPLATE_PACK):
        if form := context.get(self.form_name_in_context):
            return render_to_string(self.template, {"form": form})
        return ""


def make_help_text(document_type=None, templates=[], required_document=None):
    if required_document and not templates:
        if isinstance(required_document, int):
            required_document = models.RequiredDocument.get(required_document)
        templates = [
            r.file
            for r in required_document.round.templates.filter(
                document_type=required_document.document_type
            )
        ]

    if not document_type and required_document:
        document_type = (
            f"{required_document.document_type.name}"
            if required_document.document_type
            else f"{required_document.get_role_display()}"
        )

    if not templates:
        if document_type:
            help_text = _(f"Please upload {document_type}")
        else:
            help_text = _("Please upload completed application form")
    if len(templates) > 0:
        if document_type:
            help_text = _(f"You can download the {document_type} template(s) at ")
        else:
            help_text = _("You can download the application form template(s) at ")

    if len(templates) > 1:
        help_text += ", ".join(
            '<strong><a href="%s">%s</a></strong>' % (t.url, os.path.basename(t.name))
            for t in templates[:-1]
        )
        if len(templates) > 2:
            help_text += ","
        help_text += (_(" or ") + '<strong><a href="%s">%s</a></strong>') % (
            templates[-1].url,
            os.path.basename(templates[-1].name),
        )
    elif len(templates) > 0:
        help_text += '<strong><a href="%s">%s</a></strong>' % (
            templates[0].url,
            os.path.basename(templates[0].name),
        )
    return help_text


class DocumentInlineFormset(TableInlineFormset):
    template = "portal/document_formset.html"

    def render(self, form, form_style, context, template_pack=TEMPLATE_PACK):
        formset = context[self.formset_name_in_context]
        round = context["round"]
        required_documents = context["required_documents"] or {
            rd.pk: rd
            for rd in (
                round.required_documents
                if form._meta.model is models.Application
                else round.required_contract_documents
            ).order_by("ordering")
        }
        ordering = {d.id: d.ordering for d in required_documents.values()}
        formset.forms.sort(key=lambda f: ordering.get(f.initial.get("required_document"), 0))
        help_texts = {
            rd.pk: make_help_text(required_document=rd) for rd in required_documents.values()
        }
        for f in formset.forms:
            rd_id = f.initial.get("required_document", 0)
            if rd_id:
                rd = required_documents.get(rd_id, None)
                if not isinstance(rd_id, int):
                    rd_id = rd_id.pk
                # if (
                #     f.instance
                #     and f.instance.pk
                #     and not f.instance.file
                #     and f.instance.file.strip != ""
                # ):
                f.fields["file"].help_text = help_texts.get(rd_id)
                label = f"{rd}" if rd else _("Document")
                state = f.instance and getattr(f.instance, "state", None)
                if state:
                    label += f' (<strong style="text-transform: uppercase;">{state}</strong>)'
                f.form_label = f.fields["file"].label = label
                if rd:
                    if rd.is_optional:
                        f.fields["file"].widget.attrs["data-required"] = 0
                    dtf = rd.format or rd.document_type.format
                    if dtf == "S":
                        f.fields["file"].widget.attrs[
                            "accept"
                        ] = ".xls,.xlw,.xlt,.xml,.xlsx,.xlsm,.xltx,.xltm,.xlsb,.csv,.ctv"
                    elif dtf == "I":
                        f.fields["file"].widget.attrs["accept"] = ".pdf,.jpg,.png,.jpeg"
                    else:
                        f.fields["file"].widget.attrs[
                            "accept"
                        ] = ".pdf,.odt,.ott,.oth,.odm,.doc,.docx,.docm,.docb,.rtf,.tex"
        context = context.flatten()
        context.update(
            {
                "formset": formset,
                "form_id": self.form_id,
                "required_documents": required_documents,
            },
        )
        return render_to_string(self.template, context)


class InlineSubform(LayoutObject):
    # template = "mycollections/formset.html"
    template = "portal/sub_form.html"

    def __init__(self, form_name_in_context, template=None):
        self.subform_name_in_context = form_name_in_context
        self.fields = []
        if template:
            self.template = template

    def render(self, form, form_style, context, template_pack=TEMPLATE_PACK):
        form = context[self.subform_name_in_context]
        return render_to_string(self.template, {"form": form})


class SubscriptionForm(ModelForm):
    class Meta:
        model = models.Subscription
        exclude = [
            "site",
        ]


class UserForm(ModelForm):
    class Meta:
        model = models.User
        fields = ["title", "first_name", "middle_names", "last_name"]
        widgets = {
            "title": autocomplete.ModelSelect2(
                "title-autocomplete",
                attrs={"data-placeholder": _("Choose your title or create a new one ...")},
            ),
        }


class ProfileForm(ModelForm):
    def clean_is_accepted(self):
        """Allow only 'True'"""
        if not self.cleaned_data["is_accepted"]:
            raise forms.ValidationError(_("Please read and consent to the Privacy Policy"))
        return True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.include_media = False
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Row(Column("date_of_birth"), Column("gender")),
            Row(Column("ethnicities"), Column("iwi_groups")),
            "primary_language_spoken",
            Row(Column("education_level"), Column("employment_status")),
            "is_accepted",
        )

    class Meta:
        model = models.Person
        fields = [
            "date_of_birth",
            "gender",
            "ethnicities",
            "education_level",
            "employment_status",
            "primary_language_spoken",
            "iwi_groups",
            "is_accepted",
        ]
        widgets = dict(
            gender=forms.RadioSelect(attrs={"style": "display: inline-block"}),
            date_of_birth=DateInput(start_date="-100y", end_date="-8y"),
            ethnicities=autocomplete.ModelSelect2Multiple(
                url="ethnicity-autocomplete",
                attrs={
                    "data-placeholder": _(
                        "Please start typing your ethnicity. You can select multiple ethnicities..."
                    ),
                },
            ),
            # ethnicities=ModelSelect2MultipleWidget(
            #     model=models.Ethnicity,
            #     search_fields=["description__icontains"],
            # ),
            sex=forms.RadioSelect,
            # languages_spoken=ModelSelect2MultipleWidget(
            #     model=models.Language,
            #     search_fields=["description__icontains"],
            # ),
            # iwi_groups=ModelSelect2MultipleWidget(
            #     model=models.IwiGroup,
            #     search_fields=["description__icontains"],
            # ),
            iwi_groups=autocomplete.ModelSelect2Multiple(
                url="iwi-group-autocomplete",
                attrs={
                    "data-placeholder": _(
                        "Please start typing your iwi group. You can select multiple groups..."
                    ),
                },
            ),
            # protection_pattern_expires_on=DateInput(),
            is_accepted=forms.CheckboxInput(),
        )
        labels = dict(
            is_accepted=gettext_lazy(
                "I have read and agreed to the "
                "<a href='#' data-toggle='modal' data-target='#privacy-statement'>Privacy Statement</a>"
            )
        )


class AdminFileWidget(forms.FileInput):
    """
    A FileField Widget that shows its current value if it has one.
    """

    def __init__(self, attrs={}):
        super(AdminFileWidget, self).__init__(attrs)

    def render(self, name, value, attrs=None, renderer=None):
        output = []
        if value and hasattr(value, "url"):
            output.append(
                '%s <a target="_blank" href="%s">%s</a> <br />%s '
                % (_("Currently:"), value.url, os.path.basename(value.name), _("Change:"))
            )
        output.append(super().render(name, value, attrs, renderer))
        return mark_safe("".join(output))


class ModelSelect2NoPK(autocomplete.ModelSelect2):
    def filter_choices_to_render(self, selected_choices):
        """Filter out un-selected choices if choices is a QuerySet."""
        if isinstance(self.choices, list):
            if selected_choices:
                if not self.choices:
                    self.choices = [(v, v) for v in selected_choices]
                else:
                    self.choices = [
                        (v, v) for v in self.choices if [sc for sc in selected_choices if sc in v]
                    ]
        else:
            super().filter_choices_to_render(selected_choices)


def apnumber(value):
    """
    For numbers 1-9, return the number spelled out. Otherwise, return the
    number. This follows Associated Press style.
    """
    try:
        value = int(value)
    except (TypeError, ValueError):
        return value
    if not 0 < value < 10:
        return value
    return (
        _("one"),
        _("two"),
        _("three"),
        _("four"),
        _("five"),
        _("six"),
        _("seven"),
        _("eight"),
        _("nine"),
    )[value - 1]


class ApplicationForm(ModelForm):

    nomination = None

    @property
    def round(self):
        return (
            models.Round.get(self.initial["round"])
            if "round" in self.initial
            else self.instance.round
        )

    letter_of_support_file = FileField(
        required=False,
        widget=forms.ClearableFileInput(
            attrs={"accept": ".pdf,.odt,.ott,.oth,.odm,.doc,.docx,.docm,.docb"}
        ),
    )
    cv_file = FileField(
        required=False,
        label=_("Curriculum Vitae"),
        widget=forms.ClearableFileInput(
            attrs={
                "accept": ".pdf,.odt,.ott,.oth,.odm,.doc,.docx,.docm,.docb,.rtf,.tex",
                "data-required": 1,
                "oninvalid": "this.setCustomValidity('%s')"
                % _("Need to attach a CV before submitting the application."),
                "oninput": "this.setCustomValidity('')",
            }
        ),
    )
    photo_identity = FileField(
        required=False,
        label=_("Photo Identity"),
        widget=forms.ClearableFileInput(
            attrs={
                "accept": ".pdf,.jpg,.png,.jpeg",
                "data-required": 1,
                "oninvalid": "this.setCustomValidity('%s')"
                % _(
                    "Your identity has not been verified. Please upload a scan of a document proving your identity."
                ),
                "oninput": "this.setCustomValidity('')",
            }
        ),
    )
    file = FileField(
        required=False,
        widget=forms.ClearableFileInput(
            attrs={
                "accept": ".pdf,.odt,.ott,.oth,.odm,.doc,.docx,.docm,.docb",
                "data-required": 1,
                "oninvalid": "this.setCustomValidity('%s')" % _("Application form is required"),
                "oninput": "this.setCustomValidity('')",
            }
        ),
    )
    budget = FileField(
        required=False,
        widget=forms.ClearableFileInput(
            attrs={
                "accept": ".xls,.xlw,.xlt,.xml,.xlsx,.xlsm,.xltx,.xltm,.xlsb,.csv,.ctv",
                "data-required": 1,
                "oninvalid": "this.setCustomValidity('%s')" % _("Budget is required"),
                "oninput": "this.setCustomValidity('')",
            }
        ),
    )

    @cached_property
    def was_submitted(self):
        return "submit" in self.data

    def clean(self):
        if self.instance and self.update_only_referees:
            self.cleaned_data = {}
            self.changed_data = []

        cleaned_data = super().clean()
        if self.was_submitted and (round := self.round):
            if (
                round.research_experience_in_years_required
                and cleaned_data.get("research_experience_in_years", None) is None
            ):
                self.add_error(
                    "research_experience_in_years", _("Research experience in years required")
                )
        return cleaned_data

    def clean_letter_of_support_file(self):
        # super().clean()

        if self.was_submitted and (round := self.round):
            if round.letter_of_support_required and not (
                self.cleaned_data.get("letter_of_support_file") or self.instance.letter_of_support
            ):
                raise forms.ValidationError(
                    _("Need to attach a letter of support before submitting the application."),
                )

        return self.cleaned_data.get("letter_of_support_file")

    def clean_cv_file(self):
        # super().clean()

        if self.was_submitted and (round := self.round):
            if (
                round.applicant_cv_required
                and round.curriculum_vitae_templates.count() > 0
                and not (self.cleaned_data.get("cv_file") or self.instance.cv)
                and self.site_id not in [2, 4, 5]
            ):
                raise forms.ValidationError(
                    _("Need to attach a CV before submitting the application."),
                )

        return self.cleaned_data.get("cv_file")

    def is_valid(self):
        is_valid = super().is_valid()
        if self.instance and self.update_only_referees:
            return True
        return is_valid

    def save(self, *args, **kwargs):

        if self.instance and self.update_only_referees:
            return self.instance

        if (
            self.cleaned_data.get("letter_of_support_file") is False
            and self.instance
            and (los := self.instance.letter_of_support)
        ):
            self.instance.letter_of_support = None
            los.delete()

        if any(f in self.changed_data for f in ["postal_address", "city", "postcode"]):
            address = models.Address.where(
                address=self.cleaned_data["postal_address"],
                postcode=self.cleaned_data["postcode"],
                city=self.cleaned_data["city"],
                country_id="NZ",
            ).last()
            if not address:
                address = models.Address.create(
                    address=self.cleaned_data["postal_address"],
                    postcode=self.cleaned_data["postcode"],
                    city=self.cleaned_data["city"],
                    country_id="NZ",
                )
            self.instance.address = address

        if (
            self.cleaned_data.get("cv_file") is False
            and self.instance
            and self.instance.round
            and self.instance.round.applicant_cv_required
            and self.instance.round.curriculum_vitae_templates.count() > 0
        ):
            self.instance.cv = None
        if (
            self.data.get("applicant_declaration_accepted") == "on"
            and self.instance
            and self.instance.round
            and self.instance.round.applicant_declaration
            and hasattr(self, "initial")
            and (u := self.initial.get("user"))
        ):
            self.instance.applicant_declaration_accepted_by = u
        return super().save(*args, **kwargs)

    def __init__(self, *args, **kwargs):
        instance = kwargs.get("instance", None)
        nomination = (
            kwargs.pop("nomination", None)
            or instance
            and instance.pk
            and models.Nomination.where(application=instance).order_by("-pk").first()
        )
        self.update_only_referees = update_only_referees = kwargs.pop(
            "update_only_referees", False
        )
        super().__init__(*args, **kwargs)
        initial = kwargs.get("initial", {})
        user = initial.get("user")
        if not nomination:
            nomination = initial.get("nomination")
        self.nomination = nomination
        language = get_language()
        site_id = self.site_id

        if site_id in [2, 4, 5]:
            self.fields["application_title"].label = _("Title of proposed research")
            self.fields["application_title_en"].label = f'{_("Title of proposed research")} [en]'
            self.fields["application_title_mi"].label = f'{_("Title of proposed research")} [mi]'

        self.helper = FormHelper(self)
        instance = self.instance or kwargs.get("instance")
        # self.helper.help_text_inline = True
        # self.helper.html5_required = True

        fields = [
            Fieldset(
                (
                    _("Principal investigator")
                    if site_id in [2, 4, 5]
                    else (
                        _("Team representative")
                        if instance and instance.is_team_application
                        else _("Individual applicant")
                    )
                ),
                Field("title", css_class="form-group col-12 mb-0"),
                Row(
                    # Column("title", css_class="form-group col-2 mb-0"),
                    Column("first_name", css_class="form-group col-4 mb-0"),
                    Column("middle_names", css_class="form-group col-4 mb-0"),
                    Column("last_name", css_class="form-group col-4 mb-0"),
                ),
                "email",
                css_id="submitter",
            ),
            Row(
                (
                    Column("organisation", css_class="col-9")
                    if nomination and nomination.org
                    else Column("org", css_class="col-9")
                ),
                Column("position", css_class="col-3"),
            ),
            "postal_address",
            Row(Column("city"), Column("postcode")),
            # Row(Column("daytime_phone"), Column("mobile_phone")),
            Row(
                Column(
                    Field(
                        "daytime_phone",
                        pattern=r"\+?[0123456789 ]+",
                        placeholder="e.g., +64 4 472 7421",
                    )
                ),
                Column(
                    Field(
                        "mobile_phone",
                        pattern=r"\+?[0123456789 ]+",
                        placeholder="e.g., +64 4 472 7421",
                    )
                ),
            ),
            # ButtonHolder(Submit("submit", "Submit", css_class="button white")),
        ]
        if instance.submitted_by and not instance.submitted_by == user:
            fields.append(Field("is_tac_accepted", type="hidden"))

        if nomination and nomination.org:
            del self.fields["org"]
        else:
            del self.fiedls["organisation"]
        if instance and nomination and nomination.org:
            instance.org = nomination.org

        round = (
            models.Round.get(self.initial["round"]) if "round" in self.initial else instance.round
        )
        self.has_required_documents = has_required_documents = round.required_documents.count() > 0
        if round.scheme.team_can_apply:
            fields.extend(
                [
                    Field(
                        "is_team_application", data_toggle="toggle", template="portal/toggle.html"
                    ),
                    Div("team_name", TableInlineFormset("members"), css_id="members"),
                ]
            )

        summary_fields = []
        if round.has_title or round.research_summary_required:
            summary_fields.append(
                Field("is_bilingual", data_toggle="toggle", template="portal/toggle.html")
            )
        guidelines = round and round.get_guidelines()
        if round.has_title:
            summary_fields.extend(
                [
                    Field("application_title"),
                    Field(f"application_title_{'en' if language=='mi' else 'mi'}"),
                ]
            )

        if site_id in [2, 5]:
            summary_fields.append(
                Row(
                    Column("proposed_start_date", css_class="col-2"),
                    Column(
                        Field(
                            "requested_amount",
                            style="text-align: right; width: 70%;",
                            max="9999999",
                        ),
                        css_class="d-flex justify-content-start gap-3",
                    ),
                )
            )

        if not has_required_documents:
            application_form_templates = (
                [round.application_template] if round.application_template else []
            )
            for t in round.application_form_templates.all():
                application_form_templates.append(t.file)

            if application_form_templates:
                help_text = make_help_text(templates=application_form_templates)
                self.fields["file"].help_text = help_text
                summary_fields.append(Field("file", title=help_text))
            else:
                summary_fields.append(
                    Field("file", data_toggle="tooltip", title=self.fields["file"].help_text)
                )
            if round.budget_template and (
                not (instance and instance.submitted_by and instance.submitted_by != user)
                or (instance and (user.is_superuser or user.is_staff))
            ):
                help_text = _(
                    'You can download the budget template at <strong><a href="%s">%s</a></strong>'
                ) % (round.budget_template.url, os.path.basename(round.budget_template.name))
                # fields.append(HTML(f'<div class="alert alert-info" role="alert">{help_text}</div>'))
                summary_fields.append(Field("budget"))
                self.fields["budget"].help_text = help_text

            if round.letter_of_support_required:
                summary_fields.append(
                    Field("letter_of_support_file", label=_("Letter of Support"))
                )
                # self.fields["letter_of_support_file"].help_text = help_text

            if round.applicant_cv_required and (
                cv_templates := [r.file for r in round.curriculum_vitae_templates.all()]
            ):
                help_text = _("You can download the CV form template(s) at ") + ", ".join(
                    '<strong><a href="%s">%s</a></strong>' % (t.url, os.path.basename(t.name))
                    for t in cv_templates[:-1]
                )
                if len(cv_templates) > 2:
                    help_text += ","
                help_text += (_(" or ") + '<strong><a href="%s">%s</a></strong>') % (
                    cv_templates[-1].url,
                    os.path.basename(cv_templates[-1].name),
                )

                self.fields["cv_file"].help_text = help_text
                summary_fields.append(
                    Field(
                        "cv_file",
                        label=_("Curriculum Vitae"),
                        data_toggle="tooltip",
                        title=help_text,
                    )
                )

        if round.research_summary_required:
            summary_fields.extend(
                [
                    Row(Field("summary"), Field(f"summary_{'en' if language=='mi' else 'mi'}")),
                ]
            )
        if round.scheme.presentation_required:
            # self.fields["presentation_url"].required = True
            self.fields["presentation_url"].widget.attrs.update(
                {
                    "placeholder": self.fields["presentation_url"].help_text,
                    "data-required": 1,
                    "oninvalid": "this.setCustomValidity('%s')"
                    % _(self.fields["presentation_url"].help_text),
                    "oninput": "this.setCustomValidity('')",
                }
            )
            summary_fields.insert(
                0,
                Field(
                    "presentation_url",
                    data_toggle="tooltip",
                    title=self.fields["presentation_url"].help_text,
                ),
            )

        if has_required_documents:
            summary_fields.append(
                Div(
                    DocumentInlineFormset("documents"),
                    css_id="documents",
                ),
            )

        tabs = [
            Tab(
                _("Team") if self.instance.is_team_application else _("Applicant"),
                css_id="applicant",
                *fields,
            ),
        ]
        # Category:
        if round.has_categories:
            category_fields = []
            if round.research_experience_in_years_required and round.can_specify_panel:
                self.fields["panel"].queryset = (
                    self.fields["panel"]
                    .queryset.filter(fund__site_id=site_id, state="active")
                    .order_by("code", "-id")
                )
                category_fields = [
                    Row(
                        Column("research_experience_in_years"),
                        Column("panel"),
                    )
                ]
            elif round.research_experience_in_years_required:
                category_fields = [Field("research_experience_in_years")]
            elif round.can_specify_panel:
                category_fields = [Field("panel")]

            if round.has_toas:
                category_fields.append(
                    Fieldset(
                        _("Type of Activities"),
                        # Row('password1', 'password2'),
                        Row(
                            Column("toa_basic", css_class="col-2"),
                            Column("toa_strategic", css_class="col-2"),
                            Column("toa_applied", css_class="col-2"),
                            Column("toa_experimental", css_class="col-2"),
                            HTML(
                                f"""<div class="col-2" style="text-align: right;"><div class="form-group"><label>{ _('Total') }</label><div>
                                 <!-- input type="number" name="toa_experimental" value="0" min="0" class="numberinput form-control" id="id_toa_experimental" autocomplete="off" -->
                                 <span class="rcorners" style="text-align: right; color: gray; font-weight: normal;" id="id_toa_total_share"></span>
                                 <small class="form-text text-muted">{ _('Total (must be 100%)') }</small>
                                 </div></div></div>"""
                            ),
                            css_id="id_toas_row",
                        ),
                    ),
                )
            if round.has_seos:
                category_fields.append(
                    Fieldset(
                        _("Socio-Economic Objectives"),
                        TableInlineFormset(
                            "seos", template="portal/category_table_inline_formset.html"
                        ),
                    )
                )
            if round.has_fors:
                category_fields.append(
                    Fieldset(
                        _("Fields of Research"),
                        TableInlineFormset(
                            "fors", template="portal/category_table_inline_formset.html"
                        ),
                        # Row(Column(HTML( "Total:")), Column(HTML("<span id='fors_total_shares'>0</share>"))),
                    )
                )
            if round.has_vmts:
                category_fields.append(
                    Fieldset(
                        _(" Vision Mātauranga Theme Categories"),
                        # Row('password1', 'password2'),
                        Row(
                            Column("vm_ecs", css_class="col-3"),
                            Column("vm_ens", css_class="col-3"),
                            Column("vm_hsw", css_class="col-3"),
                            Column("vm_ink", css_class="col-3"),
                            css_id="id_toas_row",
                        ),
                        Div(
                            Row(Column("is_vm_na")),
                            Row(Column("vm_rationale")),
                            # Row(Column("rationale_vm_na"), css_id="id_vm_na"),
                            # HTML(
                            #     """<script>
                            # $(document).ready(function() {
                            #     //set initial state.
                            #     if ($('#id_is_vm_na').is(':checked')) {
                            #         $('#id_vm_na').show()
                            #     } else { $('#id_vm_na').hide() };
                            #     $('#id_is_vm_na').change(function() {
                            #         if(this.checked) {
                            #             // var returnVal = confirm("Are you sure?");
                            #             // $(this).prop("checked", returnVal);
                            #             $('#id_vm_na').show();
                            #         } else $('#id_vm_na').hide();
                            #     });
                            # });
                            # </script>"""
                            # ),
                        ),
                    ),
                )
            if round.has_keywords:
                category_fields.append(
                    Fieldset(
                        _("Keywords"),
                        Field("keywords"),
                    )
                )
            if round.priorities.exists():
                category_fields.append(
                    Fieldset(
                        _("Research Priorities"),
                        Field("priorities"),
                    )
                )
                self.fields["priorities"].widget = autocomplete.TaggitSelect2(
                    url="research-priority-autocomplete",
                    forward=[
                        forward.Const(round.pk, "round"),
                        forward.Const("application", "model"),
                    ],
                )

            tabs.append(
                Tab(
                    _("Categories"),
                    HTML(
                        '<div class="alert alert-dark" role="alert"><p>%s</p><p>%s</p></div>'
                        % (
                            _(
                                "The collection of this data is for the purpose of our reporting "
                                "obligations to NZRIS or to allow categorisation of your application "
                                "during the selection process (i.e. to early- or mid-career "
                                "fellowship pool)."
                            ),
                            _("For more information see")
                            + (
                                (': <a href="%s#Categories" target="_blank">%s</a>')
                                % (guidelines, _("Categories"))
                            ),
                        )
                    ),
                    *category_fields,
                    css_id="categories",
                ),
            )
        if site_id == 2:
            tabs.append(
                Tab(
                    _("Summary and Forms"),
                    HTML(
                        '<div class="alert alert-dark" role="alert"><p>%s</p><p>%s</p></div>'
                        % (
                            _(
                                "An application form must be uploaded to enable submission; "
                                "however, the application can be updated at any point before the "
                                '"Submit" button is clicked.'
                            ),
                            _(
                                'To revise the application, click "Browse" and you will be prompted for the new file '
                                'location; and then "Save" to replace the existing file.'
                            ),
                        )
                    ),
                    *summary_fields,
                    css_id="summary",
                ),
            )
        else:
            tabs.append(
                Tab(
                    _("Summary and Forms"),
                    HTML(
                        (
                            '<div class="alert alert-dark" role="alert"><p>%s</p><p>%s</p><p>%s</p></div>'
                            % (
                                _(
                                    "An upload is required for each of the Documents below. These should be prepared "
                                    "on one of the provided templates where available. The limit on space in all "
                                    "sections of the templates should be adhered to and the typeface should be 11 point, "
                                    "Times or similar type font, single spacing (11 point), with margins of 2 cm on the "
                                    "left and 2 cm on the right sides of the page. Instructions in italic may be "
                                    "removed, but not the margins."
                                ),
                                _(
                                    'To revise an uploaded document, click "Browse" and you will be prompted for the '
                                    'new file location; and then "Save" to replace the existing file.'
                                ),
                                _(
                                    'For more information see: <a href="%s#SummaryAndForms" target="_blank">Summary and Forms</a>'
                                )
                                % guidelines,
                            )
                        )
                        if site_id in [2, 4, 5]
                        else (
                            '<div class="alert alert-dark" role="alert"><p>%s</p><p>%s</p></div>'
                            % (
                                _(
                                    "An application form must be uploaded before referees can be invited; "
                                    "however, the form can be updated at any point up until submission."
                                ),
                                _(
                                    'To revise the application, click "Browse" and you will be prompted for the new file '
                                    'location; and then "Save" to replace the existing file.'
                                ),
                            )
                        )
                    ),
                    *summary_fields,
                    css_id="summary",
                ),
            )
        if round.has_referees:
            if site_id in [2, 4, 5]:
                referee_information_text = "\n".join(
                    f"<p>{line}</p>"
                    for line in [
                        (
                            _(
                                "%(number_of_referees)s referees are required to support this application. "
                                "You are able to invite additional referees by clicking the + button. "
                                "Please note that the society will only accept the first "
                                "%(number_of_referees)s reports received."
                            )
                            % {"number_of_referees": apnumber(round.required_referees)}
                        ).capitalize(),
                        _(
                            'For more information see: <a href="%s#Referees" target="_blank">Referees</a>'
                        )
                        % guidelines,
                    ]
                )

            elif round.required_referees and round.required_referees > 1:
                referee_information_lines = [
                    (
                        (
                            _("At least %s referees are required to support this application.")
                            % apnumber(round.required_referees)
                        )
                        if round.is_flexible_number_of_referees
                        else (
                            _("%s referees are required to support this application.")
                            % apnumber(round.required_referees)
                        ).capitalize()
                    ),
                    _(
                        "The Selection Panel at its sole discretion, may request further "
                        "referees or make contact with outside parties."
                    ),
                    _(
                        "The panel also reserves the right to hold interviews to help inform their decision."
                    ),
                ]
                referee_information_text = "".join(
                    f"<p>{line}</p>" for line in referee_information_lines
                )
            else:
                referee_information_text = _(
                    "This Prize requires one referee who has a solid understanding of your interest "
                    "in communication and is able to give expert, current opinion."
                )
            tabs.append(
                Tab(
                    _("Referees"),
                    HTML(
                        f'<div class="alert alert-dark" role="alert">{referee_information_text}</div>'
                    ),
                    Div(TableInlineFormset("referees")),
                    css_id="referees",
                ),
            )
        # if user and not user.is_identity_verified:
        if (
            round.pid_required
            and not user.is_identity_verified
            and (
                not (instance and instance.id)
                or (not instance.submitted_by_id or instance.submitted_by == user)
            )
        ):
            tabs.append(
                Tab(
                    _("Identity Verification"),
                    Field(
                        "photo_identity",
                        data_toggle="tooltip",
                    ),
                    # InlineSubform("identity_verification"),
                    css_id="id-verification",
                ),
            )

        if round.ethics_statement_required:
            tabs.append(
                Tab(
                    _("Ethics"),
                    HTML(
                        '<div class="alert alert-dark" role="alert"><p>%s</p></div>'
                        % (
                            _(
                                "Please provide an ethics form.  If this is not applicable to your application, click "
                                '"Not Applicable" and state why in the comment.'
                            ),
                        )
                    ),
                    InlineSubform("ethics_statement"),
                    css_id="ethics-statement",
                ),
            )

        if not instance.submitted_by or instance.submitted_by == user:
            if not (tac_text := round.tac):
                if site_id in [2, 4, 5]:
                    tac_text = "\n".join(
                        f"<p>{l}</p>"
                        for l in [
                            _(
                                "The information you provide in your application is used by the Royal Society Te Apārangi "
                                "to evaluate your application. Your contact details may also be used to communicate with "
                                "you about other Royal Society Te Apārangi activities."
                            ),
                            _(
                                "Your information is stored in a secure environment with access limited to authorised "
                                "staff, external panel members and reviewers in order for your application to be evaluated."
                            ),
                            _(
                                "We may notify other funding agencies of your funding application to ensure that "
                                "there is no duplication of funding."
                            ),
                            _(
                                "Application information may be subject to release under the Official Information Act "
                                "1982, as it is deemed to be held by MBIE who engage the Royal Society Te Apārangi to "
                                "administer Ngā Puanga Pūtaiao Fellowships."
                            ),
                            _(
                                "If your application is successful, Royal Society Te Apārangi will publish your name, "
                                "a description of the project, and the amount of funding, and may, with your permission, "
                                "summarise your application for use in publicity such as press releases or published articles."
                            ),
                            _(
                                "Unless required by law, your information will not be disclosed to any other party."
                            ),
                            _(
                                "You have the right to access your information and ask for it to be updated or corrected."
                            ),
                            _(
                                "We will keep information we hold about you indefinitely unless you request otherwise."
                            ),
                            _(
                                "As the applicant, you take full responsibility for the content of the application, "
                                "including the suitability and validity of cited sources and originality of content."
                            ),
                            _(
                                "Any questions or concerns please email the "
                                '<a href="mailto:%22Privacy%20Officer%22%3cprivacy.officer@'
                                'royalsociety.org.nz%3e" target="_blank">Privacy Officer</a>.'
                            ),
                        ]
                    )
                elif site_id == 2:
                    tac_text = _(
                        "I affirm that I fulfil the eligibility requirements for this scheme "
                        "and that my application abides by any rules as laid out in the scheme's guidelines. <br><br> "
                        "I affirm that all information provided in this application is "
                        "to the best of my knowledge true and correct."
                    )
                else:
                    tac_text = _(
                        "<p>As the authorized applicant I have read the eligibility criteria and other information in "
                        "the Prize Guidelines and all the information provided in this application I believe to be "
                        "true and correct."
                        "<p>I affirm that if successful, I (and where relevant, my team) will participate in "
                        "publicity and that the content of "
                        "this application can be used in promotion of the Prizes.</p>"
                        "<p>If the Prize comes with conditions on use, I affirm that any Prize money will be used in "
                        "accordance with the Prize’s guidelines, and in accord with any plan "
                        "submitted as part of the Prize.</p>"
                    )
            tabs.append(
                Tab(
                    _("Terms and Conditions"),
                    HTML(f'<div class="alert alert-dark" role="alert">{tac_text}</div>'),
                    Field(
                        "is_tac_accepted",
                        data_required=1,
                        oninput="this.setCustomValidity('')",
                        oninvalid="this.setCustomValidity('%s')"
                        % _(
                            "You have to accept the Terms and Conditions before submitting the application"
                        ),
                    ),
                    css_id="tac",
                ),
            )

        submission_disabled = (
            not instance.is_tac_accepted
            and instance.submitted_by
            and instance.submitted_by != user
        )
        # send_out_to_referees = site_id in [2, 5] and instance.state in ["new", "draft", "in_review"]
        is_ro = (
            instance
            and instance.pk
            and (site_id in [2, 5])
            and (
                models.Nomination.where(
                    Q(nominator=user) | Q(org__research_offices__user=user), application=instance
                ).exists()
            )
        )

        submit_button_kwargs = dict(
            css_id="submit-id-submit",
            data_tooltip="tooltip",
            title=(
                _("Only the main applicant or the applicant team can submit the application")
                if is_ro
                else (
                    _("Save the referee list and invited new ones if any new has been added")
                    if update_only_referees
                    else (
                        _(
                            "Your team leader must accept the Terms and Conditions before the submission can happen"
                        )
                        if submission_disabled
                        else (
                            ("Submit the application to the Research Office")
                            if site_id in [2, 4, 5]
                            else ("Submit the application")
                        )
                        # else (
                        #     _("Submit the application to referees for reviewing it")
                        #     if send_out_to_referees
                        #     else _("Submit the application")
                        # )
                    )
                )
            ),
            css_class="btn-outline-primary",
            disabled=submission_disabled or is_ro,
        )
        # if round.applicant_declaration and instance and instance.state in ["new", "draft"]:
        #     submit_button_kwargs.update(
        #         {"data_toggle": "modal", "data_target": "#id_applicant_declaration_modal"}
        #     )

        submit_button = Submit(
            "submit",
            # "submit_to_referees" if send_out_to_referees else "submit",
            # _("Submit to referees") if send_out_to_referees else _("Submit"),
            _("Submit"),
            # disabled=not instance.is_tac_accepted,  # and instance.submitted_by != user,
            **submit_button_kwargs,
        )
        self.helper.layout = Layout(
            TabHolder(*tabs),
            ButtonHolder(
                Button("previous", "« " + _("Previous"), css_class="btn-outline-primary"),
                Div(
                    Submit(
                        "save_draft",
                        _("Save"),
                        css_class="btn-primary",
                        data_toggle="tooltip",
                        title=(
                            _(
                                "Save the referee list and invited new ones if any new has been added"
                            )
                            if update_only_referees
                            else (
                                _("Save draft application")
                                if not instance or instance.state in ["new", "draft"]
                                else _("Save application updates")
                            )
                        ),
                    ),
                    submit_button,
                    HTML(
                        """<a href="{{ view.get_success_url }}"
                        type="button"
                        role="button"
                        class="btn btn-secondary"
                        id="cancel">
                            %s
                        </a>"""
                        % _("Cancel")
                    ),
                    Button("next", _("Next") + " »", css_class="btn-primary"),
                    css_class="float-right",
                ),
                css_class="mb-5",
            ),
        )
        self.helper.include_media = False

    class Meta:
        model = models.Application
        exclude = [
            "converted_file",
            "cv",
            "documents",
            "fors",
            "letter_of_support",
            "number",
            "round",
            "seos",
            "site",
            "state",
            "submitted_by",
            "state_changed_at",
            "tac_accepted_at",
            "awarded_amount",
            "agent_declaration_accepted_by",
            "agent_declaration_accepted_at",
            "applicant_declaration_accepted_by",
            "tags",
        ]
        widgets = dict(
            proposed_start_date=DateInput(end_date="+3y", start_date="+6m"),
            keywords=autocomplete.ModelSelect2Multiple(
                url="keyword-autocomplete",
                attrs={
                    "data-placeholder": _("Choose a keyword or create a new one ..."),
                },
            ),
            org=autocomplete.ModelSelect2(
                "org-autocomplete",
                attrs={"data-placeholder": _("Choose an organisation or create a new one ...")},
            ),
            organisation=ModelSelect2NoPK(
                "org-name-autocomplete",
                attrs={"data-placeholder": _("Choose an organisation or create a new one ...")},
            ),
            title=autocomplete.ModelSelect2(
                "title-autocomplete",
                attrs={"data-placeholder": _("Choose your title or create a new one ...")},
            ),
            postal_address=forms.Textarea(attrs={"rows": "3"}),
            # summary=SummernoteWidget(),
            daytime_phone=TelInput(),
            mobile_phone=TelInput(),
            # file=FileInput(),
            position=TextInput(
                attrs={"placeholder": _("student, postdoc, etc.")},
            ),
            summary=SummernoteInplaceWidget(attrs={"summernote": {"width": "100%"}}),
            summary_en=SummernoteInplaceWidget(attrs={"summernote": {"width": "100%"}}),
            summary_mi=SummernoteInplaceWidget(attrs={"summernote": {"width": "100%"}}),
            ethics_statement__comment=SummernoteInplaceWidget(
                attrs={"summernote": {"width": "100%"}}
            ),
            # round=HiddenInput(),
            letter_of_support_file=forms.ClearableFileInput(
                attrs={"accept": ".pdf,.odt,.ott,.oth,.odm,.doc,.docx,.docm,.docb"}
            ),
            research_experience_in_years=NumberInput(
                attrs={
                    "placeholder": _("Research experience in years"),
                    "data-required": 1,
                    "oninvalid": "this.setCustomValidity('%s')"
                    % _("Research experience in years is required"),
                    "oninput": "this.setCustomValidity('')",
                }
            ),
        )
        labels = {
            "keywords": "",
            "priorities": "",
            "is_tac_accepted": _("I have read and accept the Terms and Conditions"),
        }
        help_texts = {
            "vm_ecs": None,
            "vm_ens": None,
            "vm_hsw": None,
            "vm_ink": None,
        }


class ContractMemberForm(FTEMixin, ModelForm):

    role = forms.ModelChoiceField(
        queryset=models.RoleType.where(for_application=True).order_by(
            models.Coalesce("name", "code")
        )
    )

    class Meta:
        model = models.ContractMember
        exclude = ["address", "middle_names"]
        disabled = ["state"]
        widgets = dict(user=HiddenInput(), state=InvitationStateInput(attrs={"readonly": True}))


class AllocationForm(ModelForm):

    def __init__(self, *args, **kwargs):
        is_ro = kwargs.pop("is_ro", False)
        super().__init__(*args, **kwargs)
        if is_ro:
            self.fields["purpose"].disabled = True
            # self.fields["purpose"].widget.attrs = {"readonly": 1}
            self.fields["details"].disabled = True

    class Meta:
        model = models.Allocation
        fields = ["period", "allocation", "purpose", "details"]
        # widgets = {
        #     "period": TextInput(attrs={"readonly": "readonly", "style": "text-align: right;"}),
        #     "allocation": TextInput(attrs={"style": "text-align: right;"}),
        #     "purpose": forms.Textarea(attrs={"rows": 3}),
        #     "details": forms.Textarea(attrs={"rows": 3}),
        # }


class AddressForm(ModelForm):

    address = forms.CharField(label=_("Address"), widget=forms.Textarea, required=False)

    def save(self, commit=True):

        if self.changed_data:
            if self.errors:
                raise ValueError(
                    "The %s could not be %s because the data didn't validate."
                    % (
                        self.instance._meta.object_name,
                        "created" if self.instance._state.adding else "changed",
                    )
                )
            a = (
                self.instance
                and self.instance.pk
                and self._meta.model.where(
                    address=self.instance.address,
                    city=self.instance.city,
                    postcode=self.instance.postcode,
                    country=self.instance.country,
                ).last()
            )
            if not a and self.instance and self.instance.pk:
                self.instance.pk = None
            elif a:
                self.instance = a
            if commit:
                self.instance.save()
        return self.instance

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.include_media = False
        self.helper.form_tag = False
        self.helper.layout = Layout(
            "address",
            Row(
                Column("city", css_class="form-group col-lg-4 mb-0"),
                Column("postcode", css_class="form-group col-4 mb-0"),
                Column("country", css_class="form-group col-md-4 mb-0"),
            ),
        )

    class Meta:
        model = models.Address
        fields = ["address", "postcode", "city", "country"]
        widgets = {
            "country": autocomplete.ModelSelect2(
                "country-autocomplete",
                # attrs={"data-placeholder": _("Choose your title or create a new one ...")},
            ),
            "city": ModelSelect2NoPK(
                "city-autocomplete",
                forward=["country"],
                # attrs={
                #     "data-placeholder": _(
                #         "Choose the organisation you can nominate a researcher for..."
                #     )
                # },
            ),
        }


class ContractForm(ModelForm):
    # fund = forms.ModelChoiceField(queryset=models.Fund.objects.order_by("code"))
    # Documents that has to be presented on separate tabs from the main document tab.
    part_fields = (
        # ("research_aims", DOCUMENT_ROLES.AIMS),
        # ("project_timeline", DOCUMENT_ROLES.PT),
        # ("proposal_budget", DOCUMENT_ROLES.PB),
        # ("award_budget", DOCUMENT_ROLES.AB),
        ("budget", DOCUMENT_ROLES.B),
        ("ethics_statement", DOCUMENT_ROLES.E),
    )
    # not_applicable = forms.BooleanField(label=_("Not Applicable"), required=False)
    # not_applicable_comment = forms.CharField(
    #     label=_("Comment"), widget=forms.Textarea, required=False
    # )
    requires_approval_comment = forms.CharField(
        label=_("Comment"), widget=forms.Textarea(attrs={"rows": "5"}), required=False
    )
    # requires_approval = forms.ChoiceField(
    #     choices=[(True, _("Yes")), (False, _("No"))],
    #     # required=True,
    #     label=gettext_lazy("Does your research require ethical and regulatory approval?"),
    # )
    has_animal_use = forms.ChoiceField(
        # choices=[(True, _("Yes")), (False, _("No")), ("", _("N/A"))],
        choices=[(True, _("Yes")), (False, _("No"))],
        widget=forms.RadioSelect,
        required=False,
        label=gettext_lazy("Does the proposed research use animals for research or teaching?"),
    )
    is_signatory_to_oa = forms.ChoiceField(
        choices=[(True, _("Yes")), (False, _("No")), ("", _("N/A"))],
        widget=forms.RadioSelect,
        required=False,
        label=gettext_lazy("Is your institution a signatory to the ANZCCART Openness Agreement?"),
    )
    involves_children = forms.ChoiceField(
        # choices=[(True, _("Yes")), (False, _("No")), ("", _("N/A"))],
        choices=[(True, _("Yes")), (False, _("No"))],
        widget=forms.RadioSelect,
        required=False,
        label=gettext_lazy(
            "Does the research involve and will therefore be subject to Section 19 "
            "of the Vulnerable Children Act 2014?"
        ),
    )
    has_child_protection = forms.ChoiceField(
        choices=[(True, _("Yes")), (False, _("No")), ("", _("N/A"))],
        widget=forms.RadioSelect,
        required=False,
        label=gettext_lazy("If yes, does your institution have a child protection policy?"),
    )

    # research_aims = FileField(
    #     required=False,
    #     widget=forms.ClearableFileInput(
    #         attrs={"accept": ".pdf,.odt,.ott,.oth,.odm,.doc,.docx,.docm,.docb"},
    #     ),
    # )

    # project_timeline = FileField(
    #     required=False,
    #     widget=forms.ClearableFileInput(
    #         attrs={"accept": ".xls,.xlw,.xlt,.xml,.xlsx,.xlsm,.xltx,.xltm,.xlsb,.csv,.ctv"}
    #     ),
    # )

    # proposal_budget = FileField(
    #     required=False,
    #     widget=forms.ClearableFileInput(
    #         attrs={"accept": ".xls,.xlw,.xlt,.xml,.xlsx,.xlsm,.xltx,.xltm,.xlsb,.csv,.ctv"}
    #     ),
    # )

    # award_budget = FileField(
    #     required=False,
    #     widget=forms.ClearableFileInput(
    #         attrs={"accept": ".xls,.xlw,.xlt,.xml,.xlsx,.xlsm,.xltx,.xltm,.xlsb,.csv,.ctv"}
    #     ),
    # )

    budget = FileField(
        required=False,
        widget=forms.ClearableFileInput(
            attrs={"accept": ".xls,.xlw,.xlt,.xml,.xlsx,.xlsm,.xltx,.xltm,.xlsb,.csv,.ctv"}
        ),
    )

    ethics_statement = FileField(
        required=False,
        widget=forms.ClearableFileInput(
            attrs={"accept": ".pdf,.odt,.ott,.oth,.odm,.doc,.docx,.docm,.docb"},
        ),
    )

    attachment = FileField(
        required=False,
        label="",
        widget=forms.ClearableFileInput(
            attrs={
                "accept": (
                    ".xls,.xlw,.xlt,.xml,.xlsx,.xlsm,.xltx,.xltm,.xlsb,.csv,.ctv"
                    ".pdf,.odt,.ott,.oth,.odm,.doc,.docx,.docm,.docb"
                )
            }
        ),
    )
    comment = forms.CharField(
        label="",
        required=False,
        widget=SummernoteInplaceWidget(attrs={"summernote": {"width": "100%", "height": "200px"}}),
    )

    # change_request_reply = forms.CharField(
    #     label="Reply to the change request",
    #     required=False,
    #     widget=SummernoteInplaceWidget(attrs={"summernote": {"width": "100%", "height": "200px"}}),
    # )

    def __init__(self, *args, **kwargs):
        initial = kwargs.get("initial", {})
        if initial:
            kwargs["initial"] = initial
        user = kwargs.pop("user", None) or initial.get("user")

        if instance := kwargs.get("instance"):
            for fn, dr in self.part_fields:
                part = instance.documents.filter(document_type__role=dr).last()
                if part:
                    initial[fn] = part.file
        super().__init__(*args, **kwargs)
        instance = self.instance or instance
        if instance and self.data.get("requires_approval") == "on":
            instance.requires_approval = True
        application = instance.application or initial.get("application")
        is_ro = (
            application
            and application.org.research_offices.filter(user=user).exists()
            and not (user.is_superuser or user.is_site_staff)
        )
        is_staff = user and (user.is_superuser or user.is_staff or user.is_site_staff)
        if not (instance and is_staff):
            for f in [
                "awarded_amount",
                "cover",
                "duration",
                "start_date",
                "end_date",
                "file",
                "preamble",
                "schedule1",
                "schedule2",
            ]:
                if f in self.fields:
                    self.fields.pop(f, None)

        # language = get_language()
        site_id = self.site_id
        if site_id in [2, 4, 5]:
            self.fields["project_title"].label = _("Title of proposed research project")
            # self.fields["application_title_en"].label = f'{_("Title of proposed research")} [en]'
            # self.fields["application_title_mi"].label = f'{_("Title of proposed research")} [mi]'

        # r = self.instance.application.round
        # parts = dict((v, v) for f, v in self.part_fields)
        parts = (
            {
                p.document_type.role if p.document_type else p.required_document.role: p
                for p in instance.documents.prefetch_related("document_type")
            }
            if instance.pk
            else {}
        )

        submission_disabled = (
            not instance
            or (instance.submitted_by and instance.submitted_by != user and not is_ro)
            or instance.documents.filter(
                ~Q(state__in=["released", "approved", "accepted"]),
                ~Q(required_document__role="EC"),
            ).exists()
            or instance.state not in ["new", "draft"]
        )
        is_pi = instance and (
            application
            and application.submitted_by == user
            or (instance.pk and instance.members.filter(user=user, role__code="PI").exists())
        )
        submit_button = Submit(
            "submit_contract",  # NB! Never call a button 'submit'!
            _("Release"),
            # disabled=not instance.is_tac_accepted,  # and instance.submitted_by != user,
            data_toggle="tooltip",
            title=(
                _("Contract was already submitted")
                if instance.state not in ["new", "draft"]
                else (
                    _("Only R.O. can submit the contract")
                    if not (is_pi or is_ro)
                    else (
                        _(
                            # "Not all the parts/appendices of the contract were approved and/or accepted"
                            "Not all the parts/appendices of the contract were approved and/or released"
                        )
                        if submission_disabled
                        else _("Release the contract")
                    )
                )
            ),
            css_class="btn-outline-primary",
            disabled=submission_disabled or not (is_pi or is_ro),
        )
        # if is_pi or is_ro:
        #     pass
        # else:
        #     # romove compliance:
        #     list(map(self.fields.pop, ["ethics_statement"]))
        compliance_fields = (
            [
                HTML(
                    """<div class="alert alert-dark" role="alert">%s</div>"""
                    % _(
                        "Indicate if ethical or regulatory approval is "
                        "required to undertake the proposed research."
                    )
                ),
            ]
            if is_pi or is_ro
            else []
        )
        disabled_compliance = not (
            is_pi
            or is_ro
            or is_staff
            # enable 'Complience' tab if the settings were changed
            or self.data
            and any(
                (f in self.changed_data)
                for f in [
                    "requires_approval",
                    "has_animal_use",
                    "is_signatory_to_oa",
                    "involves_children",
                    "has_child_protection",
                ]
            )
        )
        compliance_fields.extend(
            [
                # Field("ethics_statement", label=_("Ethics Statement")),
                Field(
                    "requires_approval",
                    data_toggle="toggle",
                    template="portal/toggle.html",
                    data_on=_("Yes"),
                    data_off=_("No"),
                    data_onstyle="success",
                    data_offstyle="warning",
                    *({"disabled": 1} if disabled_compliance else {}),
                ),
                # "not_applicable",
                # "not_applicable_comment",
                # not disabled_compliance
                # and HTML(
                #     '<p id="id_requires_approval_comment_help" class="text-warning">%s</p>'
                #     % (
                #         (
                #             _(
                #                 "Please indicate if you already have, or when you expect to receive, "
                #                 "ethical and regulatory approval to conduct the proposed research."
                #             )
                #             if instance.requires_approval
                #             or self.data.get("requires_approval") == "on"
                #             else _(
                #                 "Please provide brief reason why ethical or regulatory approval is not required."
                #             )
                #         )
                #         if instance and instance.pk
                #         else _(
                #             "If YES, please provide numbers of relevant approval(s) needed to undertake the proposed research has been obtained. "
                #             "(Please provide serial number, type of approval and date received) "
                #             "if NOT, please provide brief reason why ethical or regulatory approval is not required."
                #         )
                #     )
                # ),
                "requires_approval_comment",
            ]
        )
        if not disabled_compliance:
            compliance_fields.append(
                HTML(
                    '<p class="text-warning">%s</p>'
                    % _(
                        "Royal Society Te Apārangi and other institutions are signatories to the ANZCCART Openness Agreement "
                        "on Animal Research and Teaching in New Zealand "
                        "<a href='https://anzccart.org.nz/openness-agreement/' target='_blank'>[link]</a>."
                    )
                )
            )
        compliance_fields.extend(
            [
                InlineRadios("has_animal_use"),
                InlineRadios("is_signatory_to_oa"),
            ]
        )
        if not disabled_compliance:
            compliance_fields.append(
                HTML(
                    '{%% load static %%}<p class="text-warning">%s</p><p class="text-warning">%s</p>'
                    % (
                        _(
                            "It is necessary for the Researcher to notify if children are involved in the research and therefore "
                            "subject to Section 19 of the Vulnerable Children’s Act 2014. All people involved in delivery of the service "
                            "will be safety checked in accordance with Part 3 of the Act. If your organisation has a Child Protection Policy, "
                            "this will cover the requirements of the Act. However, if your organisation does not have a child protection policy, "
                            "then the Contractor (your organisation) agrees to comply with the child protection policy of the Royal Society Te Apārangi."
                        ),
                        _(
                            "If your organisation does not have one, The Royal Society Te Apārangi child protection policy will "
                            "be appended to your contract. This document can be viewed at "
                            """<a href="{% static 'Child-Protection-Policy.pdf' %}" target='_blank'>Child Protection Policy</a>"""
                        ),
                    )
                )
            )
        compliance_fields.extend(
            [
                InlineRadios("involves_children"),
                InlineRadios("has_child_protection"),
            ]
        )
        # if instance and instance.pk:
        #     es = models.ContractEthicsStatement.where(contract=instance).last()
        #     if es and es.not_relevant:
        #         self.fields["not_applicable_comment"].required = True

        if disabled_compliance:
            self.fields["ethics_statement"].disabled = True
            self.fields["has_animal_use"].disabled = True
            self.fields["is_signatory_to_oa"].disabled = True
            self.fields["involves_children"].disabled = True
            self.fields["has_child_protection"].disabled = True
            self.fields["requires_approval"].disabled = True
            self.fields["requires_approval_comment"].disabled = True
            self.fields["requires_approval_comment"].required = False
            # self.fields["not_applicable"].disabled = True
            # self.fields["not_applicable_comment"].disabled = True
            compliance_fields.append(
                Fieldset(
                    None,
                    Submit(
                        "approve_compliance",
                        _("Approve"),
                        data_document_role="E",
                        data_toggle="tooltip",
                        data_enabled_title=_("Approve contract compliance"),
                        data_disabled_title=_(
                            "The compliance has been already approved or haven't been uploaded yet"
                        ),
                        title=_("Approve contract compliance"),
                        # title=(
                        #     _("Approve research aims")
                        #     if "AIMS" in parts
                        #     else _("Please upload research aims before approving it")
                        # ),
                        css_class="btn-primary float-right",
                        # css_class="btn-outline-primary",
                        disabled=("E" not in parts and "ethics_statement" not in self.initial),
                        css_id="id_approve_compliance",
                    ),
                    css_id="id_approve_copliance",
                )
            )
        else:
            pass
            # self.fields["has_animal_use"].help_text = gettext_lazy(
            #     "Does the proposed research use animals for research or teaching? AAA"
            # )
            # self.fields["has_animal_use"].disabled = True
            # self.fields["is_signatory_to_oa"].disabled = True
            # self.fields["involves_childeren"].disabled = True
            # self.fields["has_child_protection"].disabled = True

        budget = instance.documents.filter(document_type__role="B").last()
        if budget:
            self.fields["budget"].label = _(
                f'Budget (<strong style="text-transform: uppercase;">{budget.state}</strong>)'
            )
        proposal_budget_file = (
            pb.file
            if application and (pb := application.documents.filter(document_type__role="B").last())
            else initial.get("proposal_budget")
        )
        self.helper = FormHelper(self)
        tabs = [
            # Tab(
            #     "Playgroud",
            #     Modal(
            #         # email.help_text was set during the initalization of the django form field
            #         Field("email", placeholder="Email", wrapper_class="mb-0"),
            #         Button(
            #             "submit",
            #             "Send Reset Email",
            #             id="email_reset",
            #             css_class="btn-primary mt-3",
            #             onClick="someJavasciptFunction()",  # used to submit the form
            #         ),
            #         css_id="my_modal_id",
            #         title="This is my modal",
            #         title_class="w-100 text-center",
            #     ),
            # ),
            Tab(
                mark_safe(f'<i class="fas fa-yin-yang"></i> {_("Summary")}'),
                *(
                    [
                        HTML("{% load tags %}{% contract_summary %}"),
                        # Field("start_date", type="hidden", css_class="hidden"),
                        # Field("end_date", type="hidden", css_class="hidden"),
                    ]
                    if self.instance
                    and self.instance.id
                    and not (user.is_superuser or user.is_site_staff)
                    else [
                        HTML(
                            """<div class="alert alert-dark" role="alert">
                        Enter the total funding allocation and/or duration and Save. The amount is not allocated over the years.
                        </div>"""
                        ),
                        Div(
                            Field("start_date"),
                            Field("end_date"),
                            Field("duration", style="text-align: right;", max="10"),
                            Field(
                                "awarded_amount",
                                style="text-align: right; width: 70%;",
                                max="9999999",
                            ),
                            css_class="d-flex justify-content-start gap-3",
                            style="gap: 1rem;",
                        ),
                        # Row(
                        #     Column("start_date", css_class="col-1"),
                        #     Column("end_date", css_class="col-1"),
                        #     Column(
                        #         Field("duration", style="text-align: right; width: 70%;"),
                        #         css_class="col-1",
                        #     ),
                        #     Column(
                        #         PrependedText(
                        #             Field(
                        #                 "awarded_amount",
                        #                 style="text-align: right; width: 70%;",
                        #                 max="9999999",
                        #             ),
                        #             "$",
                        #             placeholder="Awarded amount",
                        #         ),
                        #         css_class="col-2",
                        #     ),
                        # ),
                    ]
                ),
                css_id="summary",
            ),
            Tab(
                mark_safe(
                    '<span data-toggle="tooltip" title="Contact Information">'
                    f'<i class="far fa-address-book"></i> {_("Contact")}</span>'
                ),
                Div(
                    Field("contact"),
                    Field("contact_phone"),
                    Field("host_contact_email"),
                    SubForm("address_form"),
                ),
                css_id="contacts",
            ),
            Tab(
                _("Research"),
                Field("project_title"),
                # Fieldset(
                #     None,
                #     Field("research_aims", label=""),
                #     Submit(
                #         "approve_research_aims",
                #         _("Approve"),
                #         data_toggle="tooltip",
                #         data_enabled_title=_("Approve research aims"),
                #         data_disabled_title=_("Please upload research aims before approving it"),
                #         data_document_role="AIMS",
                #         title=(
                #             _("Approve research aims")
                #             if "AIMS" in parts
                #             else _("Please upload research aims before approving it")
                #         ),
                #         css_class="btn-primary float-right",
                #         # css_class="btn-outline-primary",
                #         disabled=("AIMS" not in parts and "research_aims" not in self.initial),
                #         css_id="id_approve_research_aims",
                #     ),
                #     css_id="research_aims_fieldset",
                # ),
                # Fieldset(
                #     None,
                #     Field("project_timeline", label=""),
                #     Submit(
                #         "approve_project_timeline",
                #         _("Approve"),
                #         data_document_role="PT",
                #         data_toggle="tooltip",
                #         data_enabled_title=_("Submit the application"),
                #         data_disabled_title=_(
                #             "Please upload project timeline before approving it"
                #         ),
                #         title=(
                #             _("Approve project timeline")
                #             if "PT" in parts
                #             else _("Please upload project timeline before approving it")
                #         ),
                #         css_class="btn-primary float-right",
                #         # css_class="btn-outline-primary",
                #         disabled=("PT" not in parts and "project_timeline" not in self.initial),
                #     ),
                #     css_id="project_timeline_fieldset",
                # ),
                Field("abstract"),
                # Field("notes"),
                css_id="research",
            ),
            Tab(
                _("Personnel"),
                TableInlineFormset("personnel"),
                css_id="personnel",
            ),
            Tab(
                _("Proposal"),
                HTML('{% include "snippets/application_detail_table.html" with a=application %}'),
                css_id="proposal",
            ),
            Tab(
                _("Reporting"),
                Fieldset(
                    _("Reporting Schedule"),
                    (
                        HTML(
                            "<div>{% load tags %}{% jinja 'partials/contract_reporting.html' %}<div>"
                        )
                        if is_ro
                        else TableInlineFormset("reporting_schedule")
                    ),
                    css_id="reporting_schedule",
                ),
                css_id="reporting",
            ),
            Tab(
                _("Compliance"),
                *compliance_fields,
                css_id="compliance",
            ),
            Tab(
                mark_safe(f'<i class="fas fa-dollar-sign"></i> {_("Finances")}'),
                HTML(
                    """{% load i18n %}<div class="alert alert-dark" role="alert">
                    {% blocktrans %}
                    Funding has been allocated over the award period.
                    You can distribute it differently, but may not exceed
                    the total award. All amounts are exclusive of GST.
                    {% endblocktrans %}
                    </div>"""
                ),
                Fieldset(
                    _("Budget Allocation"),
                    (
                        # HTML(
                        #     "<div>{% load tags %}{% jinja 'partials/contract_allocations.html' %}<div>"
                        # )
                        # if is_ro
                        # else
                        TableInlineFormset(
                            "allocations", template="portal/allocations_table_inline_formset.html"
                        )
                    ),
                    css_id="allocations",
                ),
                (
                    # Field("proposal_budget"),
                    Fieldset(
                        None,
                        HTML(
                            f"""<div class="input-group mb-2">
                        <div class="input-group-prepend">
                            <span class="input-group-text">{_("Proposal Budget")}</span>
                        </div>
                        <div class="form-control d-flex h-auto">
                            <span class="text-break" style="flex-grow:1;min-width:0">
                            <a href="{proposal_budget_file.url}">
                                {os.path.basename(proposal_budget_file.name)}
                            </a>
                            </span>
                        </div>
                    </div>"""
                        ),
                        # Submit(
                        #     "copy_proposal_budget",
                        #     _("Copy"),
                        #     css_class="btn-primary float-right",
                        #     data_document_action="copy_proposal_budget",
                        #     # data_document_role="PB",
                        #     data_document_role="PB",
                        # ),
                    )
                    if proposal_budget_file
                    else None
                ),
                (
                    Field("budget", label="")
                    if is_pi and not is_ro and not is_staff
                    else Fieldset(
                        None,
                        # Field("award_budget", label=""),
                        Field("budget", label=""),
                        (
                            Submit(
                                "approve_budget",
                                _("Release") if is_ro else _("Accept"),
                                css_class="btn-secondary float-right",
                                data_document_action=("release" if is_ro or is_pi else "accept"),
                                # data_document_role="AB",
                                data_document_role="B",
                                disabled=not budget
                                or budget.state in ["released", "approved", "accepted"],
                                data_tooltip="tooltip",
                                title=(
                                    "Upload and release the budget"
                                    if not budget
                                    else (
                                        "Release the budget"
                                        if budget.state not in ["released", "approved", "accepted"]
                                        else "Budget was already released or approved"
                                    )
                                ),
                            )
                            if is_ro
                            else ButtonHolder(
                                Submit(
                                    "request_budget_correction",
                                    _("Request Correction"),
                                    css_class="btn-primary",
                                    data_document_action="request_correction",
                                    # data_document_role="PB",
                                    data_document_role="B",
                                ),
                                Submit(
                                    "approve_budget",
                                    _("Release") if is_ro else _("Accept"),
                                    css_class="btn-secondary",
                                    data_document_action=(
                                        "release" if is_ro or is_pi else "accept"
                                    ),
                                    # data_document_role="AB",
                                    data_document_role="B",
                                ),
                                css_class="float-right",
                            )
                        ),
                    )
                ),
                css_id="finances",
            ),
            Tab(
                mark_safe(f'<i class="far fa-file"></i> {_("Appendices")}'),
                Div(
                    DocumentInlineFormset("documents"),
                    css_id="documents",
                ),
                css_id="appendices",
            ),
        ]

        if instance and instance.pk:
            tabs.append(
                Tab(
                    mark_safe(f'<i class="fas fa-comments"></i> {_("Correspondence")}'),
                    # Field("host_contact_email"),
                    Field("comment"),
                    Fieldset(
                        None,
                        Field("attachment"),
                        ButtonHolder(
                            Submit(
                                "post_comment",
                                _("Post Comment"),
                                css_class="btn-primary",
                            ),
                            Button(
                                "import_email_file",
                                _("Import Email"),
                                css_class="btn-outline-primary",
                                hx_get=reverse(
                                    "email-import", kwargs={"pk": instance and instance.pk}
                                )
                                + "?_modal_dialog=1&model=contract",
                                hx_target="#form-dialog",
                                hx_params="none",
                                data_toggle="tooltip",
                                title=_("Import an email file as a comment ..."),
                            ),
                            css_class="float-right",
                        ),
                    ),
                    HTML(
                        '{% include "snippets/comments.html" with comments=object.comments.all %}'
                    ),
                    css_id="correspondence",
                )
            )
            if user.is_superuser or user.is_site_staff:
                self.fields["cover"].label = ""
                self.fields["preamble"].label = ""
                self.fields["schedule1"].label = ""
                self.fields["schedule2"].label = ""
                self.fields["file"].label = ""
                if not instance.schedule2 and (default_schedule2 := instance.default_schedule2):
                    self.fields["schedule2"].help_text = (
                        f"Default: <a href='{ default_schedule2.url }'>{ os.path.basename(default_schedule2.name) }</a>"
                    )
                tabs.append(
                    Tab(
                        mark_safe(f'<i class="far fa-file"></i> {_("Parts")}'),
                        user.is_admin
                        and instance.is_variation
                        and SubForm("change_request_reply_form"),
                        Fieldset(
                            None,
                            Row(
                                Column(
                                    HTML("""<label for="id_cover">Cover page</lable>"""),
                                    css_class="col-12",
                                )
                            ),
                            Row(
                                Column(
                                    HTML(
                                        (
                                            """
<a
    href="{%% url 'contract-export' pk=%(pk)d  %%}?part=cover&for_download=1&format=odt"
    type="button"
    role="button"
    target="_blank"
    class="btn btn-primary float-right ml-1"
    data-toggle="tooltip",
    title="Generate the cover page (ODF format)",
    id="generate_cover_button">ODF</a>
<a
    href="{%% url 'contract-export' pk=%(pk)d  %%}?part=cover&for_download=1&format=html"
    type="button"
    role="button"
    target="_blank"
    class="btn btn-primary float-right ml-1"
    data-toggle="tooltip",
    title="Generate the cover page (HTML format)",
    id="generate_cover_button">HTML</a>
"""
                                            + (
                                                """
<input type="submit" name="delete_cover" value="Delete" class="btn btn-danger float-right ml-1" id="submit-id-delete_cover">
"""
                                                if instance.cover
                                                else ""
                                            )
                                        )
                                        % dict(pk=instance.pk)
                                    ),
                                    css_class="col-2",
                                ),
                                Column(Field("cover"), css_class="col-10"),
                            ),
                            Row(
                                Column(
                                    HTML("""<label for="id_preamble">Preamble</lable>"""),
                                    css_class="col-12",
                                )
                            ),
                            Row(
                                Column(
                                    HTML(
                                        (
                                            """
<a
    href="{%% url 'contract-export' pk=%(pk)d  %%}?part=preambre&for_download=1&format=odt"
    type="button"
    role="button"
    target="_blank"
    class="btn btn-primary float-right ml-1"
    data-toggle="tooltip",
    title="Generate the Contract Preamble (ODF format)",
    id="generate_cover_button">ODF</a>
<a
    href="{%% url 'contract-export' pk=%(pk)d  %%}?part=preambre&for_download=1&format=html"
    type="button"
    role="button"
    target="_blank"
    class="btn btn-primary float-right ml-1"
    data-toggle="tooltip",
    title="Generate the Contract Preamble",
    id="generate_cover_button">HTML</a>
"""
                                            + (
                                                """
<input type="submit" name="delete_preamble" value="Delete" class="btn btn-danger float-right ml-1" id="submit-id-delete_preamble">
"""
                                                if instance.preamble
                                                else ""
                                            )
                                        )
                                        % dict(pk=instance.pk)
                                    ),
                                    css_class="col-2",
                                ),
                                Column(Field("preamble"), css_class="col-10"),
                            ),
                            Row(
                                Column(
                                    HTML("""<label for="id_preamble">Schedule 1</lable>"""),
                                    css_class="col-12",
                                )
                            ),
                            Row(
                                Column(
                                    HTML(
                                        (
                                            """
<a
    href="{%% url 'contract-export' pk=%(pk)d  %%}?part=schedule&for_download=1&format=odt"
    type="button"
    role="button"
    target="_blank"
    class="btn btn-primary float-right ml-1"
    data-toggle="tooltip",
    title="Generate the Schedule 1 (ODF format)",
    id="generate_cover_button">ODF</a>
<a
    href="{%% url 'contract-export' pk=%(pk)d  %%}?part=schedule&for_download=1&format=html"
    type="button"
    role="button"
    target="_blank"
    class="btn btn-primary float-right ml-1"
    data-toggle="tooltip",
    title="Generate the Schedule 1 (HTML format)",
    id="generate_cover_button">HTML</a>
"""
                                            + (
                                                """
<input type="submit" name="delete_schedule1" value="Delete" class="btn btn-danger float-right ml-1" id="submit-id-delete_schedule1">
"""
                                                if instance.schedule1
                                                else ""
                                            )
                                        )
                                        % dict(pk=instance.pk)
                                    ),
                                    css_class="col-2",
                                ),
                                Column(Field("schedule1"), css_class="col-10"),
                            ),
                            Row(
                                Column(
                                    HTML("""<label for="id_preamble"><u>Schedule 2</u></lable>"""),
                                    css_class="col-12",
                                )
                            ),
                            Row(
                                Column(
                                    HTML(
                                        """
<input type="submit" name="delete_schedule2" value="Delete" class="btn btn-danger float-right ml-1" id="submit-id-delete_schedule2">
"""
                                        if instance.schedule2
                                        else ""
                                    ),
                                    css_class="col-1",
                                ),
                                Column(Field("schedule2"), css_class="col-11"),
                            ),
                            Row(
                                Column(
                                    HTML("""<label for="id_file"><u>Contract file</u></lable>"""),
                                    css_class="col-12",
                                )
                            ),
                            Row(
                                Column(
                                    HTML(
                                        """
<input type="submit" name="delete_file" value="Delete" class="btn btn-danger float-right ml-1" id="submit-id-delete_file">
"""
                                        if instance.file
                                        else ""
                                    ),
                                    css_class="col-1",
                                ),
                                Column(Field("file"), css_class="col-11"),
                            ),
                            ButtonHolder(
                                Submit(
                                    "generate_contract",
                                    _("Generate"),
                                    data_toggle="tooltip",
                                    title=(
                                        "Generate or regenerate variation letter"
                                        if instance.is_variation
                                        else "Generate or regenerate contract document and store it in the database"
                                    ),
                                    css_class="btn-primary",
                                ),
                                (
                                    HTML(
                                        f"""
                            <a
                                class="btn btn-primary"
                                href="{reverse("contract-export", kwargs={"pk": instance and instance.pk})}?format=pdf"
                                target="_blank"
                                data-toggle="tooltip"
                                data-html="true"
                                title="First <b>Save</b> and then export it to create an updated version of the variation letter",
                            > {_("Export Variation Letter")} </a>"""
                                    )
                                    if instance.is_variation
                                    else HTML(
                                        f"""
                            <a
                                class="btn btn-primary"
                                href="{reverse("contract-export", kwargs={"pk": instance and instance.pk})}?format=pdf"
                                target="_blank"
                                data-toggle="tooltip"
                                data-html="true"
                                title="First <b>Save</b> and then export it to create an updated version of the contract document",
                            > {_("Export Contract")} </a>"""
                                    )
                                ),
                                # Submit(
                                #     "export_contract",
                                #     _("Export Contract"),
                                #     css_class="btn-primary",
                                # ),
                                # Button(
                                #     "import_email_file",
                                #     _("Import Email"),
                                #     hx_get=reverse(
                                #         "email-import", kwargs={"pk": instance and instance.pk}
                                #     )
                                #     + "?_modal_dialog=1",
                                #     hx_target="#form-dialog",
                                #     hx_params="none",
                                #     data_toggle="tooltip",
                                #     title=_("Import an email file as a comment ..."),
                                #     css_class="btn-outline-primary",
                                # ),
                                css_class="float-right",
                            ),
                        ),
                        css_id="parts",
                    ),
                )
        self.helper.layout = Layout(
            TabHolder(*tabs),
            ButtonHolder(
                Button("previous", "« " + _("Previous"), css_class="btn-outline-primary"),
                Div(
                    Submit(
                        "save",
                        _("Save and continue"),
                        css_class="btn-secondary",
                        data_toggle="tooltip",
                        title=_("Save and continue editing"),
                    ),
                    Submit(
                        "save_draft",
                        _("Save"),
                        css_class="btn-primary",
                        data_toggle="tooltip",
                        title=_("Save draft contract"),
                    ),
                    submit_button,
                    HTML(
                        """<a href="{{ view.get_success_url }}"
                        type="button"
                        role="button"
                        class="btn btn-secondary"
                        id="cancel">
                            %s
                        </a>"""
                        % _("Close")
                    ),
                    Button("next", _("Next") + " »", css_class="btn-primary"),
                    css_class="float-right",
                ),
                css_class="mb-5",
            ),
        )
        self.helper.include_media = False

    def save(self, *args, **kwargs):
        created = not self.instance.pk
        if "duration" in self.changed_data and "end_date" not in self.changed_data:
            self.cleaned_data["end_date"] = self.instance.end_date = (
                self.instance.start_date or self.cleaned_data["start_date"]
            ) + relativedelta(years=self.cleaned_data["duration"], days=-1)

        res = super().save(*args, **kwargs)
        if "duration" in self.changed_data:
            c = self.instance
            duration = c.duration or self.cleaned_data["duration"]
            c.reporting_schedule.filter(period__gt=duration).delete()
            c.allocations.filter(period__gt=duration).delete()
            # if c.reporting_schedule.count() < duration:
            #     pass
            c.reporting_schedule.filter(period=duration).update(type="F")
            models.ContractMemberEffort.where(member__contract=c, period__gt=duration).delete()

        r = self.instance.application.round
        for fn, dr in self.part_fields:
            if created or fn in self.changed_data:
                file = self.cleaned_data.get(fn, None)
                part = self.instance.documents.filter(document_type__role=dr).last()
                if part:
                    if not file:
                        part.delete()
                    else:
                        part.file.save(
                            name=file.name,
                            content=file,
                        )
                    if part.converted_file:
                        part.converted_file = None
                        part.page_count = None
                        part.save()

                elif file:
                    required_document = r.required_contract_documents.filter(
                        document_type__role=dr
                    ).last()
                    if not required_document:
                        dt = models.DocumentType.where(role=dr).last()
                        required_document = models.RequiredContractDocument.create(
                            round=r, document_type=dt
                        )

                    models.ContractDocument.create(
                        contract=self.instance, required_document=required_document, file=file
                    )

        if created or any(
            (fn in self.changed_data)
            for fn in ["not_applicable", "not_applicable_comment", "ethics_statement"]
        ):
            es_part = self.instance.documents.filter(document_type__role="E").last()
            try:
                es = self.instance.ethics_statement
            except models.ContractEthicsStatement.DoesNotExist:
                es = models.ContractEthicsStatement(contract=self.instance)
            es.not_relevant = self.cleaned_data.get("not_applicable", False)
            es.comment = self.cleaned_data.get("not_applicable_comment", None)
            es.file = es_part and es_part.file
            es.save()

        return res

    class Meta:
        model = models.Contract
        exclude = [
            "address",
            "application",
            # "awarded_amount",
            # "duration",
            "fors",
            "fund",
            "host_number",
            "keywords",
            "notes",
            "number",
            "org",
            "rccs",
            "seos",
            "site",
            "state",
            "submitted_by",
            "state_changed_at",
            "is_variation",
        ]
        widgets = dict(
            start_date=DateInput(),
            end_date=DateInput(end_date="+12y", start_date="+1y"),
            keywords=autocomplete.ModelSelect2Multiple(
                url="keyword-autocomplete",
                attrs={
                    "data-placeholder": _("Choose a keyword or create a new one ..."),
                },
            ),
            host_contact_email=ModelSelect2NoPK(
                url="org-email-autocomplete",
                attrs={
                    "data-placeholder": _("Select an email addrss or create a new one ..."),
                },
            ),
            panels=autocomplete.ModelSelect2Multiple(url="panel-autocomplete"),
            panel=autocomplete.ModelSelect2(url="panel-autocomplete"),
            # summary=SummernoteWidget(),
            daytime_phone=TelInput(),
            mobile_phone=TelInput(),
            # file=FileInput(),
            abstract=SummernoteInplaceWidget(attrs={"summernote": {"width": "100%"}}),
            notes=SummernoteInplaceWidget(attrs={"summernote": {"width": "100%"}}),
            summary=SummernoteInplaceWidget(attrs={"summernote": {"width": "100%"}}),
            summary_en=SummernoteInplaceWidget(attrs={"summernote": {"width": "100%"}}),
            summary_mi=SummernoteInplaceWidget(attrs={"summernote": {"width": "100%"}}),
            ethics_statement__comment=SummernoteInplaceWidget(
                attrs={"summernote": {"width": "100%"}}
            ),
            # round=HiddenInput(),
            letter_of_support_file=forms.ClearableFileInput(
                attrs={"accept": ".pdf,.odt,.ott,.oth,.odm,.doc,.docx,.docm,.docb"}
            ),
            cover=forms.ClearableFileInput(
                attrs={
                    "accept": ".html,.htm,.fodt,.pdf,.odt,.ott,.oth,.odm,.doc,.docx,.docm,.docb"
                }
            ),
        )


class MemberForm(FTEMixin, ReadOnlyFieldsMixin, FormWithStateFieldMixin, ModelForm):

    def __init__(self, *args, **kwargs):
        # duration = kwargs.pop("duration", None)
        super().__init__(*args, **kwargs)
        site_id = (
            self.instance
            and self.instance.pk
            and (a := self.instance.application)
            and a.site_id
            or settings.SITE_ID
        )
        if site_id == 2:
            self.fields.pop("middle_names", None)
        else:
            self.fields.pop("org", None)
            self.fields.pop("country", None)

    readonly_fields = ["state"]
    role = forms.ModelChoiceField(
        queryset=models.RoleType.where(for_application=True).order_by(
            models.Coalesce("name", "code")
        ),
        required=False,
    )

    def clean(self):
        cleaned_data = super().clean()
        if member := cleaned_data.get("id"):
            application = member.application
        else:
            application = cleaned_data.get("application")
        email = cleaned_data.get("email")
        if not email:
            raise forms.ValidationError(_("Team member email address is mandatory"))
        if application and application.pk:
            q = application.members.filter(email=email)
            if member:
                q = q.filter(~models.Q(id=member.id))
            if q.exists():
                raise forms.ValidationError(
                    _("Team member with the email address %(email)s was already added"),
                    params={"email": email},
                )
        return cleaned_data

    class Meta:
        model = models.Member
        fields = [
            "state",
            "email",
            "first_name",
            "middle_names",
            "last_name",
            "role",
            "country",
            "org",
        ]
        # fields = ["email", "first_name", "middle_names", "last_name", "role"]
        disabled = ["state"]
        widgets = dict(
            email=forms.EmailInput(
                attrs={
                    "placeholder": _("Email"),
                    "data-required": 1,
                    "oninvalid": "this.setCustomValidity('%s')" % _("Email is required"),
                    "oninput": "this.setCustomValidity('')",
                }
            ),
            # has_authorized=NullBooleanSelect(attrs=dict(readonly=True)),
            state=InvitationStateInput(attrs={"readonly": True}),
            country=autocomplete.ModelSelect2("country-autocomplete"),
            org=autocomplete.ModelSelect2("org-autocomplete"),
        )


class MemberFormSet(
    inlineformset_factory(
        models.Application, models.Member, form=MemberForm, extra=1, can_delete=True
    )
):
    def delete_existing(self, obj, commit=True):
        if commit:
            for i in models.Invitation.where(member=obj):
                i.revoke()
                i.save()
            obj.delete()

    def clean(self):
        super().clean()
        emails = [f.cleaned_data.get("email") for f in self.forms]
        emails = [v.strip().lower() for v in emails if v and v.strip()]
        for i, v in enumerate(emails[:-1]):
            if v in emails[i + 1 :]:
                raise forms.ValidationError(_("You have entered email address {v} twice."))


class RefereeForm(ReadOnlyFieldsMixin, FormWithStateFieldMixin, ModelForm):
    readonly_fields = ["state"]

    def save(self, commit=True):
        """Prevent 'state' getting overwritten"""
        if self.errors:
            for e in self.errors:
                capture_message(f"{e}")
            raise ValueError(
                "The %s could not be %s because the data didn't validate."
                % (
                    self.instance._meta.object_name,
                    "created" if self.instance._state.adding else "changed",
                )
            )
        if commit:
            if self.instance.id:
                if "email" in self.changed_data:
                    r = self.instance
                    for i in models.Invitation.where(referee=self.instance):
                        i._change_reason = f"Email changed from {self.instance.email} to ..."
                        i.revoke(description=i._change_reason)
                        i.referee = None
                        i.save()
                    self.instance = models.Referee.create(
                        application=r.application,
                        email=r.email,
                        first_name=r.first_name,
                        middle_names=r.middle_names,
                        last_name=r.last_name,
                    )
                    r.delete()
                else:
                    self.instance.save(update_fields=["first_name", "middle_names", "last_name"])
            else:
                self.instance.save()
            self._save_m2m()
        else:
            self.save_m2m = self._save_m2m
        return self.instance

    def full_clean(self):
        if (referee_id := self["id"].data) and not (self["email"].data or "").strip():
            self.cleaned_data = {
                forms.formsets.DELETION_FIELD_NAME: True,
                "id": models.Referee.get(referee_id),
            }
            return self.cleaned_data
        return super().full_clean()

    def clean(self):
        cleaned_data = super().clean()
        if referee := cleaned_data.get("id"):
            application = referee.application
        else:
            application = cleaned_data.get("application")
        email = cleaned_data.get("email")
        if not email:
            raise forms.ValidationError(_("Referee email address is mandatory"))
        if application and application.pk:
            q = application.referees.filter(email=email)
            if referee:
                q = q.filter(~models.Q(id=referee.id))
            if q.exists():
                raise forms.ValidationError(
                    _("Referee with the email address %(email)s was already added"),
                    params={"email": email},
                )
        return cleaned_data

    class Meta:
        model = models.Referee
        fields = ["state", "email", "first_name", "middle_names", "last_name", "org"]
        widgets = dict(
            email=forms.EmailInput(
                attrs={
                    "placeholder": _("Email"),
                    "data-required": 1,
                    "oninvalid": "this.setCustomValidity('%s')" % _("Email is required"),
                    "oninput": "this.setCustomValidity('')",
                }
            ),
            has_testiefed=NullBooleanSelect(attrs=dict(readonly=True)),
            state=InvitationStateInput(attrs={"readonly": True}),
            org=autocomplete.ModelSelect2(
                "org-autocomplete",
                # forward=["nominator"],
                attrs={"data-placeholder": _("Choose the organisation of the referee...")},
            ),
        )


class MandatoryApplicationFormInlineFormSet(BaseInlineFormSet):
    def delete_existing(self, obj, commit=True):
        if commit:
            for i in models.Invitation.where(referee=obj):
                i.revoke()
                i.save()
            obj.delete()

    def add_fields(self, form, index):
        # workaround:
        super().add_fields(
            form, index=index if (self.can_delete_extra or index is not None) else 9999
        )

    def clean(self):
        pass


class ProfileCareerStageForm(ModelForm):
    class Meta:
        exclude = ()
        model = models.PersonCareerStage


ProfileCareerStageFormSet = modelformset_factory(
    models.PersonCareerStage,
    # form=ProfileCareerStageForm,
    # fields=["profile", "year_achieved", "career_stage"],
    exclude=(),
    can_delete=True,
    widgets=dict(
        person=HiddenInput(),
        year_achieved=YearInput(attrs={"min": "-60y", "max": "+3y"}),
        career_stage=Select(
            attrs={
                # "required": True,
                "data-placeholder": _("Choose a career stage ..."),
                "placeholder": _("Choose a career stage ..."),
                "data-required": 1,
                "oninvalid": "this.setCustomValidity('%s')" % _("Career stage is required"),
                "oninput": "this.setCustomValidity('')",
            }
        ),
    ),
)


ProfilePersonIdentifierFormSet = modelformset_factory(
    models.PersonPersonIdentifier,
    # form=ProfileCareerStageForm,
    # fields=["profile", "year_achieved", "career_stage"],
    exclude=(),
    can_delete=True,
    widgets=dict(profile=HiddenInput()),
)


class ProfilePersonIdentifierForm(ModelForm):
    def clean(self):
        data = super().clean()

        if not data.get("code"):
            raise forms.ValidationError(_("Invalid identifier type. Please select a valid type."))

        if not data.get("value"):
            raise forms.ValidationError(_("Invalid identifier value. Please enter a valid value."))

        if getattr(data.get("code"), "code") == "02" and (orcid := data.get("value")):
            p = data.get("person")
            u = p.user
            if (
                not (u.orcid and u.orcid.endswith(orcid))
                or not u.socialaccount_set.all().filter(provider="orcid", uid=orcid).exists()
            ):
                raise forms.ValidationError(
                    _(
                        "Invalid ORCID iD value: %(value)s. "
                        "The ID should be authenticated either by linking your account to ORCID or TUAKIRI. "
                        "Click <a href='%(url)s'>here to link your account with ORCID or TUAKIRI</a>."
                    ),
                    code="invalid",
                    params={"value": orcid, "url": reverse("socialaccount_connections")},
                )

        return data

    class Meta:
        exclude = ()
        model = models.PersonPersonIdentifier


class MemberFormSetHelper(FormHelper):
    template = "portal/table_inline_formset.html"

    # def __init__(self, previous_step=None, next_step=None, *args, **kwargs):
    #     super().__init__(*args, **kwargs)
    #     add_more_button = Button(
    #         "add_more", _("Add More"), css_class="btn btn-outline-warning", css_id="add_more"
    #     )
    #     # if previous_step or next_step:
    #     #     previous_button = Button(
    #     #         "previous", "« " + _("Previous"), css_class="btn btn-outline-primary"
    #     #     )
    #     #     previous_button.input_type = "submit"
    #     #     self.add_input(previous_button)
    #     #     self.add_input(add_more_button)
    #     #     if next_step:
    #     #         next_button = Button(
    #     #             "next", _("Next") + " »", css_class="btn btn-primary float-right"
    #     #         )
    #     #         next_button.input_type = "submit"
    #     #         self.add_input(next_button)
    #     #     else:
    #     #         self.add_input(Submit("save", _("Save"), css_class="float-right"))
    #     # else:
    #     #     self.add_input(add_more_button)
    #     #     self.add_input(Submit("save", _("Save")))
    #     #     self.add_input(Button("cancel", _("Cancel"), css_class="btn btn-danger"))
    #     self.add_input(add_more_button)


class ProfileSectionFormSetHelper(FormHelper):
    template = "portal/table_inline_formset.html"

    def __init__(
        self, person=None, previous_step=None, next_step=None, wizard=False, *args, **kwargs
    ):
        super().__init__(*args, **kwargs)
        # add_more_button = Button(
        #     "add_more", _("Add More"), css_class="btn btn-outline-warning", css_id="add_more"
        # )
        if previous_step or next_step:
            previous_button = Button(
                "previous", "« " + _("Previous"), css_class="btn-outline-primary"
            )
            previous_button.input_type = "submit"
            self.add_input(previous_button)
            complete_button = Button(
                "complete",
                _("Skip and Complete"),
                data_toggle="tooltip",
                title=_("Skip the rest of the profile sections and complete the profile now"),
                css_class="btn-outline-secondary",
            )
            complete_button.input_type = "submit"
            self.add_input(complete_button)
            # self.add_input(add_more_button)
            if next_step:
                next_button = Button("next", _("Next") + " »", css_class="btn-primary float-right")
                next_button.input_type = "submit"
                self.add_input(next_button)
            else:
                self.add_input(
                    Submit(
                        "save",
                        _("Finish and Save") if wizard else _("Save"),
                        css_class="btn-primary float-right",
                    )
                )
        else:
            # self.add_input(add_more_button)
            self.add_input(Submit("save", _("Save")))
            self.add_input(Button("cancel", _("Cancel"), css_class="btn-danger"))


class NominationForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        initial = getattr(self, "initial", None) or kwargs.get("initial") or dict()

        n = self.instance
        r = n and n.pk and n.round or initial and initial.get("round")
        if isinstance(r, int):
            r = models.Round.get(r)
        site_id = n and n.pk and n.site_id or r and r.site_id or settings.SITE_ID
        nominator = n and n.pk and n.nominator or initial and initial.get("nominator") or None
        org_id = n and n.pk and n.org and n.org.pk or initial.get("org")
        is_single_org_ro = False
        if nominator:
            if (
                is_single_org_ro := (
                    site_id in [2, 4, 5] and nominator.research_offices.count() == 1
                )
            ) and (ro_org := models.Organisation.where(research_offices__user=nominator).last()):
                org_id = initial["org"] = ro_org.pk
            elif site_id in [2, 4, 5] and (
                nominator_org := models.Organisation.where(research_offices__user=nominator).last()
            ):
                org_id = initial["org"] = nominator_org.pk
            elif (
                nominator_affiliation := models.Organisation.where(
                    affiliations__person__user=nominator, affiliations__end_date__isnull=True
                )
                .distinct()
                .order_by("affiliations__start_date")
                .last()
            ):
                org_id = initial["org"] = nominator_affiliation.pk
        if not initial.get("org") and org_id:
            initial["org"] = org_id

        self.helper = FormHelper(self)
        self.helper.include_media = False
        self.helper.form_id = "nomination-form"
        fields = [
            # "round",
            "nominator",
            Fieldset(
                (
                    _(
                        "Nominee - details of the person you are nominating to apply for the round of the scheme"
                    )
                    if site_id in [2, 4, 5]
                    else _(
                        "Nominee - details of the person you are nominating to receive this award"
                    )
                ),
                Field("title", css_class="form-group col-12 mb-0"),
                Row(
                    # Column("title", css_class="form-group col-2 mb-0"),
                    Column("first_name", css_class="form-group col-3 mb-0"),
                    Column("middle_names", css_class="form-group col-4 mb-0"),
                    Column("last_name", css_class="form-group col-5 mb-0"),
                ),
                "email",
                css_id="nominee",
            ),
            Row(
                # Column("org", css_class="col-9"),
                Column(
                    (
                        HTML(
                            f"""
                <div id="div_id_org" class="form-group">
                    <label for="id_org" data-toggle="tooltip" data-html="true" title="{_('Organisation of the nominee')}">
                        {_('Organisation of the nominee')}
                    </label>
                    <div class="">
                        <input type="hidden" name="org" value="{ro_org.pk}" id="id_org" readonly>
                        <input type="text" name="org_name" value="{ro_org}" class="textinput textInput form-control" id="id_name_org" readonly>
                        <small id="hint_id_position" class="form-text text-muted">{ _('Organisation of the nominee') }</small>
                    </div>
                </div>"""
                        )
                        if is_single_org_ro
                        else "org"
                    ),
                    css_class="col-9",
                ),
                Column("position", css_class="col-3"),
            ),
            HTML(
                """
            <div id="div_id_nominator" class="form-group">
            <label for="id_nominator" class=" requiredField">%s</label>
                <div class="">
                    <input
                        value="{{ nominator.full_name_with_email }}"
                        disabled="" class="input form-control">
                </div>
            </div>
            """
                % _("Nominator")
            ),
            Field(
                "contact_phone",
                pattern=r"\+?[0123456789 ]+",
                placeholder="e.g., +64 4 472 7421",
            ),
        ]
        if site_id in [2, 5]:
            self.fields["contact_phone"].help_text = _("The Research Office contact phone number")
        else:
            self.fields["contact_phone"].help_text = _("Your (nominator) contact phone number")

        if r.nominator_cv_required:

            if nominator_cv := models.CurriculumVitae.last_user_cv(nominator):
                initial["cv_file"] = nominator_cv.file

            self.fields["cv_file"] = FileField(
                label=_("Curriculum Vitae"),
                required=False,
                widget=forms.ClearableFileInput(
                    attrs={"accept": ".pdf,.odt,.ott,.oth,.odm,.doc,.docx,.docm,.docb,.rtf,.tex"}
                ),
                help_text=_("Please upload your (nominator) curriculum vitae"),
            )
            fields.append("cv_file")

        if r.nomination_form_required or r.nomination_form_required is None:
            if r and r.nomination_template:
                help_text = _(
                    'You can download the nomination form template at <strong><a href="%s">%s</a></strong>'
                ) % (r.nomination_template.url, os.path.basename(r.nomination_template.name))
                fields.append(
                    HTML(
                        '<div class="alert alert-dark" role="alert">%s</div>'
                        % (
                            _(
                                'Please download the <strong><a href="%s">%s</a></strong>, '
                                "complete then upload below."
                            )
                            % (
                                r.nomination_template.url,
                                os.path.basename(r.nomination_template.name),
                            )
                        )
                    )
                )
                fields.append(Field("file", label=help_text, help_text=help_text))
                self.fields["file"].help_text = help_text
            else:
                fields.append("file")

        # fields.append("summary")
        was_submitted = self.instance and self.instance.id and self.instance.state == "submitted"
        was_accepted = self.instance and self.instance.id and self.instance.state == "accepted"
        self.helper.layout = Layout(
            *fields,
            HTML("""<input type="hidden" name="action">"""),
            ButtonHolder(
                Submit(
                    "save_draft",
                    _("Save"),
                    css_class="btn-primary",
                    data_toggle="tooltip",
                    disabled=was_submitted or was_accepted,
                    title=(
                        _("Nomination was already submitted")
                        if was_submitted
                        else (
                            _("Nomination was already accepted")
                            if was_accepted
                            else _("Save draft nomination")
                        )
                    ),
                ),
                Button(
                    "submit_button",
                    _("Re-submit") if was_submitted else _("Submit"),
                    css_class="btn-outline-primary",
                    # data_toggle="modal",
                    # data_target="#confirm-submit",
                    data_toggle="tooltip",
                    disabled=was_accepted,
                    title=(
                        _("Nomination was already accepted")
                        if was_accepted
                        else _("Submit or re-submit the nomination")
                    ),
                ),
                HTML(
                    """<a href="{{ view.get_close_url }}" class="btn btn-secondary">%s</a>"""
                    % _("Close")
                ),
                css_class="mb-4 float-right",
            ),
        )

        if is_single_org_ro:
            # self.fields["org"].disabled = True
            # self.fields["org"].widget.attrs["disabled"] = "true"
            # self.fields["org"].widget.attrs["readonly"] = "true"
            del self.fields["org"]

    def save(self, commit=True):
        if self.instance.round.nominator_cv_required:
            if "cv_file" in self.changed_data:
                cv = models.CurriculumVitae(
                    owner=self.instance.nominator,
                    person=self.instance.nominator.person,
                    title=_("Nominator CV"),
                )
                cv_file = self.cleaned_data["cv_file"]
                cv.file.save(cv_file.name, File(cv_file))
                cv.save()
                self.instance.cv = cv

            elif not self.instance.cv:
                self.instance.cv = models.CurriculumVitae.last_user_cv(self.instance.nominator)

        return super().save(commit=commit)

    class Meta:
        model = models.Nomination
        fields = [
            # "round",
            "nominator",
            "contact_phone",
            "title",
            "first_name",
            "middle_names",
            "last_name",
            "email",
            "org",
            "position",
            # "summary",
            "file",
        ]
        widgets = dict(
            org=autocomplete.ModelSelect2(
                "org-autocomplete",
                forward=["nominator"],
                attrs={
                    "data-placeholder": _(
                        "Choose the organisation you can nominate a researcher for..."
                    )
                },
            ),
            title=autocomplete.ModelSelect2(
                "title-autocomplete",
                attrs={"data-placeholder": _("Choose your title or create a new one ...")},
            ),
            nominator=HiddenInput(),
            file=forms.ClearableFileInput(
                attrs={"accept": ".pdf,.odt,.ott,.oth,.odm,.doc,.docx,.docm,.docb,.rtf,.tex"}
            ),
            # round=HiddenInput(),
            # summary=SummernoteInplaceWidget(),
        )


class TestimonialForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.helper = FormHelper(self)
        self.helper.include_media = False
        self.helper.form_id = "entry-form"
        initial = kwargs.get("initial")
        site_id = self.instance.site_id
        round = (
            self.instance.id
            and self.instance.application.round
            or initial
            and initial["application"].round
        )
        referee = initial and initial.get("referee") or self.instance and self.instance.referee
        fields = []
        if round.referee_cv_required:
            if referee:
                user = (
                    referee.user
                    or models.User.where(
                        models.Q(email=referee.email) | models.Q(emailaddress__email=referee.email)
                    ).last()
                )

                if referee and (cv := models.CurriculumVitae.last_user_cv(user)):
                    self.initial["cv_file"] = cv.file

            self.fields["cv_file"] = FileField(
                label=_("Curriculum Vitae"),
                required=False,
                widget=forms.ClearableFileInput(
                    attrs={"accept": ".pdf,.odt,.ott,.oth,.odm,.doc,.docx,.docm,.docb,.rtf,.tex"}
                ),
                help_text=_("Please upload your (referee) curriculum vitae"),
            )
            fields.append("cv_file")
        if round.testimonials_required:
            fields.append(
                Field("file", data_toggle="tooltip", title=self.fields["file"].help_text)
            )
            if site_id in [2, 4, 5]:
                self.fields["file"].label = ""
            if round.referee_template:
                help_text = _(
                    'You can download the application review form template at <strong><a href="%s">%s</a></strong>'
                ) % (round.referee_template.url, os.path.basename(round.referee_template.name))
                # fields.insert(0, HTML(f'<div class="alert alert-info" role="alert">{help_text}</div>'))
                self.fields["file"].help_text = help_text
            self.fields["file"].required = True
        # fields = [
        #     Fieldset(_("Referee Report") if site_id in [2, 4, 5] else _("Testimonial"), *fields),
        # ]

        self.helper.layout = Layout(
            *fields,
            HTML("""<input type="hidden" name="action">"""),
            ButtonHolder(
                Submit(
                    "save_draft",
                    _("Save"),
                    css_class="btn-primary",
                    data_toggle="tooltip",
                    title=_("Save draft testimonial"),
                ),
                Button(
                    "submit_button",
                    _("Submit"),
                    css_class="btn-outline-primary",
                ),
                Submit(
                    "turn_down",
                    (
                        _("I do not wish to provide a report")
                        if site_id in [2, 4, 5]
                        else _("I do not wish to provide a testimonial")
                    ),
                    css_class="btn-outline-danger",
                ),
                HTML(
                    """<a href="{{ view.get_success_url }}" class="btn btn-secondary">%s</a>"""
                    % _("Close")
                ),
                css_class="mb-4 float-right",
            ),
        )

    def save(self, commit=True):

        if self.instance.round.referee_cv_required:
            referee = (
                self.initial
                and self.initial.get("referee")
                or self.instance
                and self.instance.referee
            )
            user = (
                referee.user
                or models.User.where(
                    models.Q(email=referee.email) | models.Q(emailaddress__email=referee.email)
                ).last()
            )

            if "cv_file" in self.changed_data:
                cv = models.CurriculumVitae(
                    owner=user,
                    person=user.person,
                    title=_("Referee CV"),
                )
                cv_file = self.cleaned_data["cv_file"]
                cv.file.save(cv_file.name, File(cv_file))
                cv.save()
                self.instance.cv = cv

            elif not self.instance.cv:
                self.instance.cv = models.CurriculumVitae.last_user_cv(user)
        return super().save(commit=commit)

    def is_valid(self):
        if "turn_down" in self.data:
            self.fields["file"].required = False
        return super().is_valid()

    class Meta:
        model = models.Testimonial
        fields = [
            # "summary",
            "file",
        ]

        widgets = dict(
            # summary=SummernoteInplaceWidget(),
            file=forms.ClearableFileInput(
                attrs={"accept": ".pdf,.odt,.ott,.oth,.odm,.doc,.docx,.docm,.docb,.rtf,.tex"}
            )
        )


class IdentityVerificationForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.helper = FormHelper(self)
        self.helper.include_media = False
        self.helper.layout = Layout(
            Div(
                HTML(
                    """
                    <embed src="{% url 'identity-verification-file' pk=object.id %}"
                        type="application/pdf"
                        frameBorder="0"
                        scrolling="auto"
                        height="100%"
                        width="100%"
                        style="min-height: 30rem; width:100%;">
                    </embed>
                    """
                    if self.instance
                    and self.instance.file
                    and self.instance.file.name.lower().endswith(".pdf")
                    else """
                    <img
                        src="{% url 'identity-verification-file' pk=object.id %}"
                        style="min-height: 20rem; width:100%;"
                        width="100%"
                    >
                    """
                ),
                height="60%",
                css_class="mb-4",
            ),
            ButtonHolder(
                Submit(
                    "accept",
                    _("Accept"),
                    css_class="btn-primary",
                ),
                Submit(
                    "reject",
                    _("Request resubmission"),
                    css_class="btn-outline-danger",
                ),
                HTML(
                    """
                    <a href="{{ view.get_success_url }}"
                    type="button"
                    role="button"
                    class="btn btn-secondary"
                    id="cancel">
                        %s
                    </a>"""
                    % _("Cancel")
                ),
                css_class="mb-4 float-right",
            ),
            Field(
                "resolution",
                data_toggle="tooltip",
                title=_("Please add a comment if you request a resubmission"),
            ),
        )

    class Meta:
        model = models.IdentityVerification
        fields = ["file", "resolution"]


class PanellistForm(ReadOnlyFieldsMixin, FormWithStateFieldMixin, ModelForm):
    readonly_fields = ["state"]
    confirm_deletion = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not (self.instance and self.instance.site_id or self.site_id) in (2, 4, 5):
            self.fields.pop("panel")
            self.fields.pop("role")
            self.fields.pop("is_active")
            self.fields.pop("elected_on")
            self.fields.pop("expires_on")

    @property
    def deletion_confirmation_message(self):
        if p := getattr(self, "instance"):
            cois = p.conflict_of_interests.all()
            evaluations = p.evaluations.all()
            message = _(
                f"<p>Are you sure you want to delete the panellist <b>{p.full_name_with_email}</b>? "
                "All of the following objects and their related items will be deleted:</p>"
                "<h2>Summary</h2><ul>"
                f"<li>Conflicts of interest: {cois.count()}</li>"
                f"<li>Reviews: {evaluations.count()}</li></ul>"
                "<h2>Objects</h2><ul><li>Panellist: "
                f"""<a href='{reverse("admin:portal_panellist_change", kwargs={"object_id": p.pk})}' target="_blank">"""
                f"{p.full_name_with_email}</a></li>"
            )
            if cois or evaluations:
                message += "<ul>"
                if cois:
                    message += "".join(
                        f"""<li>Conflict of interest: <a href='{reverse("admin:portal_conflictofinterest_change",
                            kwargs={"object_id": c.pk})}' target="_blank">
                            {str(c)}</a></li>"""
                        for c in cois
                    )
                if evaluations:
                    message += "".join(
                        f"""<li>Review: <a href='{reverse("admin:portal_evaluation_change",
                            kwargs={"object_id": e.pk})}' target="_blank">
                            {str(e)}</a></li>"""
                        for e in evaluations
                    )
                message += "</ul>"
            message += "<ul>"
            return message

        return _(
            "Do you wish to delete the selected panellist and all linked data entries to this panellist?"
        )

    class Meta:
        model = models.Panellist
        exclude = ("site", "state_changed_at")
        widgets = {
            "state": InvitationStateInput(attrs={"readonly": True}),
            "round": HiddenInput(),
        }


class PanellistFormSet(
    modelformset_factory(
        models.Panellist,
        form=PanellistForm,
        exclude=("site",),
        can_delete=True,
        widgets={
            "round": HiddenInput(),
            # "state": InvitationStateInput(attrs={"readonly": True}),
        },
    )
):
    def delete_existing(self, obj, commit=True):
        if commit:
            for i in models.Invitation.where(panellist=obj):
                i.revoke()
                i.save()
            obj.delete()


class PanellistFormSetHelper(FormHelper):
    template = "portal/table_inline_formset.html"

    def __init__(self, panellist=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_input(
            Submit(
                "send_invite",
                _("Invite"),
                css_class="btn-primary",
            )
        )
        self.add_input(
            Submit(
                "copy",
                _("Copy"),
                css_class="btn-secondary",
                data_toggle="tooltip",
                title=_("Copy from the previous round"),
            ),
        )
        self.add_input(Submit("cancel", _("Cancel"), css_class="btn-danger"))


class ConflictOfInterestForm(ModelForm):
    has_conflict = OppositeBooleanField(label=_("Conflict of Interest"), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.helper = FormHelper(self)
        self.helper.include_media = False
        fields = [
            Field(
                "has_conflict",
                data_toggle="toggle",
                template="portal/toggle.html",
                data_on=_("No"),
                data_off=_("Yes"),
                data_onstyle="success",
                data_offstyle="danger",
            ),
            Field("comment"),
        ]
        self.helper.layout = Layout(
            *fields,
            ButtonHolder(
                Submit(
                    "submit",
                    _("Submit"),
                    css_class="btn-outline-primary",
                ),
                HTML(
                    """<a href="{{ view.get_success_url }}" class="btn btn-secondary">%s</a>"""
                    % _("Close")
                ),
                css_class="mb-4 float-right",
            ),
        )

    class Meta:
        model = models.ConflictOfInterest
        fields = [
            "comment",
            "has_conflict",
        ]

        widgets = dict(
            comment=SummernoteInplaceWidget(
                attrs={"summernote": {"width": "100%", "height": "200px"}}
            )
        )


class CriterionWidget(Widget):
    # input_type = 'radio'
    template_name = "portal/widgets/criterion.html"
    # option_template_name = 'django/forms/widgets/radio_option.html'

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        if value:
            context["value_label"] = self.choices.queryset.filter(id=value).first().definition
        return context


class ReadOnlyApplicationWidget(Widget):
    # input_type = 'radio'
    template_name = "portal/widgets/application.html"
    # option_template_name = 'django/forms/widgets/radio_option.html'

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        if value:
            context["object"] = (
                self.choices.queryset.select_related("round").filter(id=value).first()
            )
        return context


class ScoreForm(ModelForm):
    value = forms.TypedChoiceField(choices=zip(range(1, 10), range(1, 10)))

    def __init__(self, *args, **kwargs):
        self.value = forms.TypedChoiceField(choices=range(10))
        super().__init__(*args, **kwargs)

        self.helper = FormHelper(self)
        self.helper.include_media = False
        self.helper.form_tag = False
        fields = [
            Field("criterion"),
            Field("value"),
        ]
        criterion = (
            self.instance.criterion
            if hasattr(self.instance, "criterion")
            else self.initial.get("criterion")
        )
        self.fields["comment"].widget.attrs = {"rows": 3}
        if criterion:
            self.fields["comment"].required = criterion.comment
            self.comment_required = criterion.comment
            if criterion.comment:
                fields.append(Field("comment", required=True))
                self.fields["comment"].widget.attrs["required"] = True
            else:
                fields.append(Field("comment"))
        self.fields["value"] = forms.TypedChoiceField(
            choices=(
                zip(
                    range(criterion.min_score, criterion.max_score + 1),
                    range(criterion.min_score, criterion.max_score + 1),
                )
                if criterion
                else zip(range(11), range(11))
            )
        )
        self.helper.layout = Layout(*fields)

    class Meta:
        model = models.Score
        fields = [
            "criterion",
            "value",
            "comment",
        ]
        widgets = dict(
            criterion=CriterionWidget(),
        )


class RoundConflictOfInterestForm(ModelForm):
    has_conflict = forms.NullBooleanField(
        label=_("Conflict of Interest"), required=False, widget=forms.HiddenInput()
    )
    # has_conflict = forms.BooleanField(label=_("Conflict of Interest"), required=False)
    # has_conflict = forms.HiddenInput()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # instance = getattr(self, "instance", None)
        # if instance and instance.id:
        #     self.fields["application"]

        self.fields["comment"].widget.attrs = {"rows": 3}

        self.helper = FormHelper(self)
        self.helper.include_media = False
        fields = [
            "application",
            "has_conflict",
            # Field(
            #     "has_conflict",
            #     data_toggle="toggle",
            #     template="portal/toggle.html",
            #     data_on=_("Yes"),
            #     data_off=_("No"),
            #     data_onstyle="danger",
            #     data_offstyle="success",
            # ),
            "comment",
            # Field("comment"),
        ]
        self.helper.layout = Layout(
            *fields,
        )


class ScoreSheetForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)

        instance = kwargs.get("instance")
        r = instance and instance.round or kwargs["initial"].get("round")

        fields = [
            "file",
            Submit(
                "submit", _("Upload the Score Sheet"), css_class="btn-primary mb-5 float-right"
            ),
        ]
        if r.score_sheet_template:
            help_text = _(
                'You can download the round score sheet template at <strong><a href="%s">%s</a></strong>'
            ) % (r.score_sheet_template.url, os.path.basename(r.score_sheet_template.name))
            # fields.append(HTML(f'<div class="alert alert-info" role="alert">{help_text}</div>'))
            self.fields["file"].help_text = help_text

        self.helper.add_layout(Layout(*fields))

    class Meta:
        model = models.ScoreSheet
        fields = ["file"]
        widgets = dict(
            file=forms.ClearableFileInput(
                attrs={"accept": ".xls,.xlw,.xlt,.xml,.xlsx,.xlsm,.xltx,.xltm,.xlsb,.csv,.ctv"}
            )
        )


class AssessedPerformanceForm(ModelForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["comment"].widget.attrs = {"rows": 3}
        if instance := kwargs.get("instance"):
            f = instance.flag
            self.fields["flag"].label = f.name
            self.fields["flag"].help_text = f.name
            self.fields["flag"].widget = forms.HiddenInput()
            if f.value_choices:
                choices = [
                    (e.strip() for e in r.strip().split(":"))
                    for r in f.value_choices.split(";")
                    if r.strip()
                ]
                self.fields["value"] = forms.ChoiceField(
                    choices=choices,
                    required=f.is_optional,
                )
            else:
                # self.fields["value"] = forms.ChoiceField(
                #     choices=[("YES", _("Yes")), ("NO" , _("No")), ("N/A", _("N/A"))] if f.is_optional else [("YES", _("Yes")), ("NO", _("No"))],
                #     required=f.is_optional,
                #     template_name="portal/toggle.html",
                # )
                self.fields["value"] = forms.ChoiceField(
                    required=not f.is_optional,
                    widget=forms.HiddenInput(),
                    initial="NA" if f.is_optional else "N",
                    choices=(
                        [("Y", _("Yes")), ("N", _("No")), ("NA", _("N/A"))]
                        if f.is_optional
                        else [("Y", _("Yes")), ("N", _("No"))]
                    ),
                )
            self.fields["value"].label = False

            # self.helper = FormHelper(self)
            # self.helper.layout = Layout(
            #     Field("flag", template="partials/assessed_performance_flag.html"),
            #     "value" if f.value_choices else Field(
            #         "value",
            #         data_toggle="toggle",
            #         template="portal/toggle.html",
            #         data_on=_("No"),
            #         data_off=_("Yes"),
            #         data_na=_("N/A"),
            #         data_onstyle="success",
            #         data_offstyle="danger",
            #     ),
            #     "comment",
            # )

    class Meta:
        model = models.AssessedPerformance
        exclude = ["created_at", "updated_at", "created_by", "updated_by"]


class ReportedEffortForm(ModelForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)

    role = forms.ModelChoiceField(
        queryset=models.RoleType.where(for_contracting=True).order_by(
            models.Coalesce("name", "code")
        )
    )
    fte_before = forms.DecimalField(widget=forms.HiddenInput(), required=False)

    class Meta:
        model = models.ReportedEffort
        exclude = ["member_effort", "state", "person", "middle_names"]
        widgets = {
            "total_fte": forms.widgets.NumberInput(
                attrs={"step": "0.01"}
                # attrs={"readonly": True, "disabled": True, "step": "0.01"}
            ),
            "person": autocomplete.ModelSelect2(url="person-autocomplete"),
        }


class ReportForm(ModelForm):

    comment = forms.CharField(
        label="",
        required=False,
        widget=SummernoteInplaceWidget(attrs={"summernote": {"width": "100%", "height": "200px"}}),
    )
    attachment = FileField(
        required=False,
        label="",
        widget=forms.ClearableFileInput(
            attrs={
                "accept": (
                    ".xls,.xlw,.xlt,.xml,.xlsx,.xlsm,.xltx,.xltm,.xlsb,.csv,.ctv"
                    ".pdf,.odt,.ott,.oth,.odm,.doc,.docx,.docm,.docb"
                )
            }
        ),
    )
    category = forms.ChoiceField(
        choices=[("R", _("Risk of variation")), ("O", _("Other"))],
        # widget=forms.RadioSelect,
        required=False,
        # label=gettext_lazy("Category"),
        label="",
    )
    alert_date = forms.ChoiceField(
        choices=[("2WK", _("Two weeks")), ("WK", _("A week"))],
        # widget=forms.RadioSelect,
        required=False,
        # label=gettext_lazy("Alert date"),
        label="",
    )

    def __init__(self, *args, **kwargs):
        initial = kwargs.get("initial", {})
        if initial:
            kwargs["initial"] = initial
        user = kwargs.pop("user", None) or initial.get("user")

        if instance := kwargs.get("instance"):
            pass
            # for fn, dr in self.part_fields:
            #     part = instance.documents.filter(document_type__role=dr).last()
            #     if part:
            #         initial[fn] = part.file
            # if es := models.ContractEthicsStatement.where(contract=instance).last():
            #     initial["not_applicable"] = es.not_relevant or False
            #     initial["not_applicable_comment"] = es.comment or ""

        super().__init__(*args, **kwargs)
        # language = get_language()
        instance = self.instance or instance
        contract = instance.contract or initial.get("contract")
        application = contract.application or initial.get("application")
        round = application and application.round or initial.get("round")
        # site_id = self.site_id
        # if site_id in [2, 4, 5]:
        #     self.fields["project_title"].label = _("Title of proposed research project")
        #     # self.fields["application_title_en"].label = f'{_("Title of proposed research")} [en]'
        #     # self.fields["application_title_mi"].label = f'{_("Title of proposed research")} [mi]'

        # # r = self.instance.application.round
        # # parts = dict((v, v) for f, v in self.part_fields)
        # parts = (
        #     {p.document_type.role: p for p in instance.documents.prefetch_related("document_type")}
        #     if instance.pk
        #     else {}
        # )

        is_pi = instance and (
            contract.submitted_by == user
            or (contract.pk and contract.members.filter(user=user, role__code="PI").exists())
            # or application.submitted_by == user
            # or (application.pk and application.members.filter(user=user, role__code="PI").exists())
        )

        is_assessor = instance and user and (instance.assessor == user)
        submission_disabled = not instance or not is_pi
        is_ro = application and application.org.research_offices.filter(user=user).exists()
        if is_assessor:
            submit_button = Submit(
                "assess",
                _("Assess"),
                css_id="submit-id-submit",
                css_class="btn-outline-primary",
            )
        else:
            submit_button = Submit(
                "submit_report",  # NB! Never call a button 'submit'!
                _("Submit"),
                # disabled=not instance.is_tac_accepted,  # and instance.submitted_by != user,
                data_toggle="tooltip",
                css_id="submit-id-submit",
                title=(
                    _("Only PI or RO can submit the report")
                    if not is_pi
                    else (
                        _(
                            "Not all the parts/appendices of the contract were approved and/or accepted"
                        )
                        if submission_disabled
                        else _("Submit the contract")
                    )
                ),
                css_class="btn-outline-primary",
                disabled=submission_disabled or not is_pi,
            )
        # # if is_pi or is_ro:
        # #     pass
        # # else:
        # #     # romove compliance:
        # #     list(map(self.fields.pop, ["ethics_statement"]))
        # compliance_fields = (
        #     [
        #         HTML(
        #             """<div class="alert alert-dark" role="alert">%s</div>"""
        #             % _(
        #                 "Please provide an ethic from. If this is not applicable to your application, "
        #                 'click "Not Applicable" and state why in the comment.'
        #             )
        #         ),
        #     ]
        #     if is_pi or is_ro
        #     else []
        # )
        # disabled_compliance = not (is_pi or is_ro)
        # compliance_fields.extend(
        #     [
        #         # Field("ethics_statement", label=_("Ethics Statement")),
        #         Field(
        #             "requires_approval",
        #             data_toggle="toggle",
        #             template="portal/toggle.html",
        #             data_on=_("Yes"),
        #             data_off=_("No"),
        #             data_onstyle="success",
        #             data_offstyle="warning",
        #         ),
        #         # "not_applicable",
        #         # "not_applicable_comment",
        #         not disabled_compliance
        #         and HTML(
        #             '<p id="id_requires_approval_comment_help" class="text-warning">%s</p>'
        #             % (
        #                 (
        #                     _(
        #                         "Please provide numbers of relevant approval(s) needed to undertake the proposed research has been obtained. "
        #                         "(Please provide serial number, type of approval and date received)"
        #                     )
        #                     if instance.requires_approval
        #                     else _(
        #                         "Please provide brief reason why ethical or regulatory approval is not required."
        #                     )
        #                 )
        #                 if instance and instance.pk
        #                 else _(
        #                     "If YES, please provide numbers of relevant approval(s) needed to undertake the proposed research has been obtained. "
        #                     "(Please provide serial number, type of approval and date received) "
        #                     "if NOT, please provide brief reason why ethical or regulatory approval is not required."
        #                 )
        #             )
        #         ),
        #         "requires_approval_comment",
        #     ]
        # )
        # if not disabled_compliance:
        #     compliance_fields.append(
        #         HTML(
        #             '<p class="text-warning">%s</p>'
        #             % _(
        #                 "Royal Society Te Apārangi and other institutions are signatories to teh ANZCCART "
        #                 "Openness Agreement on Animal Research and Teaching in New Zealand ... TODO:..."
        #             )
        #         )
        #     )
        # compliance_fields.extend(
        #     [
        #         InlineRadios("has_animal_use"),
        #         InlineRadios("is_signatory_to_oa"),
        #     ]
        # )
        # if not disabled_compliance:
        #     compliance_fields.append(
        #         HTML(
        #             '<p class="text-warning">%s</p>'
        #             % _(
        #                 "It is necessary for the Researcher to notify if children "
        #                 "are involved in the research and therefor "
        #                 "subject to Section 19 of the Vulnerable Children's Act 2014. All ... TODO:..."
        #             )
        #         )
        #     )
        # compliance_fields.extend(
        #     [
        #         InlineRadios("involves_childeren"),
        #         InlineRadios("has_child_protection"),
        #     ]
        # )
        # # if instance and instance.pk:
        # #     es = models.ContractEthicsStatement.where(contract=instance).last()
        # #     if es and es.not_relevant:
        # #         self.fields["not_applicable_comment"].required = True

        # if disabled_compliance:
        #     self.fields["ethics_statement"].disabled = True
        #     self.fields["has_animal_use"].disabled = True
        #     self.fields["is_signatory_to_oa"].disabled = True
        #     self.fields["involves_childeren"].disabled = True
        #     self.fields["has_child_protection"].disabled = True
        #     self.fields["requires_approval"].disabled = True
        #     self.fields["requires_approval_comment"].disabled = True
        #     # self.fields["not_applicable"].disabled = True
        #     # self.fields["not_applicable_comment"].disabled = True
        #     compliance_fields.append(
        #         Fieldset(
        #             None,
        #             Submit(
        #                 "approve_compliance",
        #                 _("Approve"),
        #                 data_document_role="E",
        #                 data_toggle="tooltip",
        #                 data_enabled_title=_("Approve contract compliance"),
        #                 data_disabled_title=_(
        #                     "The compliance has been already approved or haven't been uploaded yet"
        #                 ),
        #                 title=_("Approve contract compliance"),
        #                 # title=(
        #                 #     _("Approve research aims")
        #                 #     if "AIMS" in parts
        #                 #     else _("Please upload research aims before approving it")
        #                 # ),
        #                 css_class="btn-primary float-right",
        #                 # css_class="btn-outline-primary",
        #                 disabled=("E" not in parts and "ethics_statement" not in self.initial),
        #                 css_id="id_approve_compliance",
        #             ),
        #             css_id="id_approve_copliance",
        #         )
        #     )
        # else:
        #     pass
        #     # self.fields["has_animal_use"].help_text = gettext_lazy(
        #     #     "Does the proposed research use animals for research or teaching? AAA"
        #     # )
        #     # self.fields["has_animal_use"].disabled = True
        #     # self.fields["is_signatory_to_oa"].disabled = True
        #     # self.fields["involves_childeren"].disabled = True
        #     # self.fields["has_child_protection"].disabled = True
        # Category:
        if round.has_categories:
            category_fields = []
            # if round.research_experience_in_years_required and round.can_specify_panel:
            #     self.fields["panel"].queryset = (
            #         self.fields["panel"]
            #         .queryset.filter(fund__site_id=site_id, state="active")
            #         .order_by("code", "-id")
            #     )
            #     category_fields = [
            #         Row(
            #             Column("research_experience_in_years"),
            #             Column("panel"),
            #         )
            #     ]
            # elif round.research_experience_in_years_required:
            #     category_fields = [Field("research_experience_in_years")]
            # elif round.can_specify_panel:
            #     category_fields = [Field("panel")]

            if round.has_toas:
                category_fields.append(
                    Fieldset(
                        _("Type of Activities"),
                        # Row('password1', 'password2'),
                        Row(
                            Column("toa_basic", css_class="col-2"),
                            Column("toa_strategic", css_class="col-2"),
                            Column("toa_applied", css_class="col-2"),
                            Column("toa_experimental", css_class="col-2"),
                            HTML(
                                f"""<div class="col-2" style="text-align: right;"><div class="form-group"><label>{ _('Total') }</label><div>
                                 <!-- input type="number" name="toa_experimental" value="0" min="0" class="numberinput form-control" id="id_toa_experimental" autocomplete="off" -->
                                 <span class="rcorners" style="text-align: right; color: gray; font-weight: normal;" id="id_toa_total_share"></span>
                                 <small class="form-text text-muted">{ _('Total (must be 100%)') }</small>
                                 </div></div></div>"""
                            ),
                            css_id="id_toas_row",
                        ),
                    ),
                )
            if round.has_seos:
                category_fields.append(
                    Fieldset(
                        _("Socio-Economic Objectives"),
                        TableInlineFormset(
                            "seos", template="portal/category_table_inline_formset.html"
                        ),
                    )
                )
            if round.has_fors:
                category_fields.append(
                    Fieldset(
                        _("Fields of Research"),
                        TableInlineFormset(
                            "fors", template="portal/category_table_inline_formset.html"
                        ),
                        # Row(Column(HTML( "Total:")), Column(HTML("<span id='fors_total_shares'>0</share>"))),
                    )
                )
            if round.has_vmts:
                category_fields.append(
                    Fieldset(
                        _(" Vision Mātauranga Theme Categories"),
                        Row(
                            Column("vm_ecs", css_class="col-3"),
                            Column("vm_ens", css_class="col-3"),
                            Column("vm_hsw", css_class="col-3"),
                            Column("vm_ink", css_class="col-3"),
                            css_id="id_toas_row",
                        ),
                        # Div(
                        #     Row(Column("is_vm_na")),
                        #     Row(Column("vm_rationale")),
                        #     # Row(Column("rationale_vm_na"), css_id="id_vm_na"),
                        #     # HTML(
                        #     #     """<script>
                        #     # $(document).ready(function() {
                        #     #     //set initial state.
                        #     #     if ($('#id_is_vm_na').is(':checked')) {
                        #     #         $('#id_vm_na').show()
                        #     #     } else { $('#id_vm_na').hide() };
                        #     #     $('#id_is_vm_na').change(function() {
                        #     #         if(this.checked) {
                        #     #             // var returnVal = confirm("Are you sure?");
                        #     #             // $(this).prop("checked", returnVal);
                        #     #             $('#id_vm_na').show();
                        #     #         } else $('#id_vm_na').hide();
                        #     #     });
                        #     # });
                        #     # </script>"""
                        #     # ),
                        # ),
                    ),
                )
            if round.has_keywords:
                category_fields.append(
                    Fieldset(
                        _("Keywords"),
                        Field("keywords"),
                    )
                )

        self.helper = FormHelper(self)
        tabs = [
            # Tab(
            #     "Playgroud",
            #     Modal(
            #         # email.help_text was set during the initalization of the django form field
            #         Field("email", placeholder="Email", wrapper_class="mb-0"),
            #         Button(
            #             "submit",
            #             "Send Reset Email",
            #             id="email_reset",
            #             css_class="btn-primary mt-3",
            #             onClick="someJavasciptFunction()",  # used to submit the form
            #         ),
            #         css_id="my_modal_id",
            #         title="This is my modal",
            #         title_class="w-100 text-center",
            #     ),
            # ),
            Tab(
                mark_safe(f'<i class="fas fa-yin-yang"></i> {_("Summary")}'),
                HTML("{% load tags %}{% jinja 'partials/report_summary.html' %}"),
                css_id="summary",
            ),
            Tab(
                mark_safe(f'<i class="fas fa-users"></i> {_("Personnel")}'),
                HTML(
                    """{% load tags %}
                <div class="alert alert-dark" role="alert">
                    <p style="margin-bottom: 0px;">
                    {{ _('Please retort all personnel who have participated in this project \
                            and who are not named in the contract. \
                            Please estimate both the amount of FTE, since the last report, \
                            that is supported by this contract as well as the total amount of FTE \
                            devoted to the project.') }}
                    </p>
                </div>"""
                ),
                TableInlineFormset("personnel"),
                css_id="personnel",
            ),
        ]
        if round.has_categories:
            tabs.append(
                Tab(
                    _("Categories"),
                    HTML(
                        '<div class="alert alert-dark" role="alert"><p>%s</p></div>'
                        % (
                            _(
                                "The collection of this data is for the purpose of our reporting "
                                "obligations to NZRIS or to allow categorisation of your application "
                                "during the selection process (i.e. to early- or mid-career "
                                "fellowship pool)."
                            ),
                        )
                    ),
                    *category_fields,
                    css_id="categories",
                ),
            )

        tabs.extend(
            [
                Tab(
                    mark_safe(
                        f'<i class="material-icons" style="vertical-align: middle; font-size: 0.99em;">work</i> {_("Activities")}'
                    ),
                    HTML(
                        """{% load tags %}
                <div class="alert alert-dark" role="alert">
                    <p style="margin-bottom: 0px;">
                    {{ _('Please report any <strong>outcomes or activities</strong> that have arisen from \
                        this project within the period. NB: if linked, the contract PI is able to import \
                        many activity types from their ORCID profile record.') }}
                    </p>
                </div>
                <div id="activity-list">
                {% jinja 'partials/reported_activity_list.html' %}
                </div>"""
                    ),
                    Div(
                        Div(
                            ButtonHolder(
                                Button(
                                    "add_activity",
                                    _("Add Activity"),
                                    css_class="btn-primary btn-sm",
                                ),
                                Button(
                                    "import_activities_from_orcid",
                                    _("Import from ORCID"),
                                    css_class="btn-secondary btn-sm",
                                ),
                                Button(
                                    "no_activity_to_add",
                                    _("Nothing to add"),
                                    css_class="btn-primary btn-sm",
                                ),
                                css_class="float-right mb-5",
                            ),
                            css_class="col-12",
                        ),
                        css_class="row",
                    ),
                    css_id="activities",
                ),
                Tab(
                    mark_safe(f'<i class="fas fa-newspaper"></i> {_("Publication")}'),
                    HTML(
                        """{% load tags %}
                <div class="alert alert-dark" role="alert">
                    <p style="margin-bottom: 0px;">
                    {{ _('Please report any publications that have arisen from this project within the period. NB: if linked, the contract PI is able to import these from their ORCID profile record.') }}
                    </p>
                </div>
                <div id="publication-list">
                {% jinja 'partials/report_publication_list.html' %}
                </div>"""
                    ),
                    Div(
                        Div(
                            ButtonHolder(
                                Button(
                                    "import_ris_file",
                                    _("Import RIS file"),
                                    css_class="btn-primary btn-sm",
                                    hx_get=reverse(
                                        "ris-import", kwargs={"pk": instance and instance.pk}
                                    )
                                    + "?_modal_dialog=1",
                                    hx_target="#publication-dialog",
                                    hx_params="none",
                                ),
                                # Button(
                                #     "import_from_orcid",
                                #     _("Import from ORCID"),
                                #     css_class="btn-secondary btn-sm",
                                # ),
                                HTML(
                                    f"""{{% load static %}}
                                    <button
                                        class="btn btn-secondary btn-sm"
                                        id="button-id-publication_import_from_orcid"
                                        hx-indicator="#button-spinner"
                                        hx-post="?action=publication_import_from_orcid"
                                        hx-target="#publication-list"
                                    >
                                    {_("Import from ORCID")}
                                        <img  id="button-spinner" class="htmx-indicator" src="{{% static '/images/bars.svg' %}}"/>
                                    </button>
                                    """
                                ),
                                Button(
                                    "nothing_to_add",
                                    _("Nothing to add"),
                                    css_class="btn-primary btn-sm",
                                ),
                                css_class="float-right mb-5",
                            ),
                            css_class="col-12",
                        ),
                        css_class="row",
                    ),
                    css_id="publications",
                ),
                Tab(
                    mark_safe(f'<i class="fas fa-dollar-sign"></i> {_("Funding")}'),
                    HTML(
                        """{% load tags %}
                <div class="alert alert-dark" role="alert">
                    <p style="margin-bottom: 0px;">
                    {{ _('Please report any funding that have or your colleagues have applied for that is related to \
                        this project within the period together with the proportion that the team \
                        is able to access. \
                        NB: if linked, the contract PI is able to import these from their ORCID profile record.') }}
                    </p>
                </div>
                <div id="reported-funding-list">
                {% jinja 'partials/report_funding_list.html' %}
                </div>"""
                    ),
                    Div(
                        Div(
                            ButtonHolder(
                                HTML(
                                    f"""{{% load static %}}
                                    <button
                                        class="btn btn-secondary btn-sm"
                                        id="button-id-funding_import_from_orcid"
                                        hx-indicator="#button-spinner"
                                        hx-post="?action=funding_import_from_orcid"
                                        hx-target="#reported-funding-list"
                                    >
                                    {_("Import from ORCID")}
                                        <img  id="button-spinner" class="htmx-indicator" src="{{% static '/images/bars.svg' %}}"/>
                                    </button>
                                    """
                                ),
                                # Button(
                                #     "funding_import_from_orcid",
                                #     mark_safe(f"""{_("Import from ORCID")}
                                #     <img  id="spinner" class="htmx-indicator" src="{{% load static %}}{{% static '/images/bars.svg' %}}"/>
                                #     """),
                                #     css_class="btn-secondary btn-sm",
                                #     hx_post=f"?action=funding_import_from_orcid",
                                #     # hx_params="none",
                                #     hx_target="#reported-funding-list",
                                #     hx_indicator="#spinner",
                                # ),
                                Button(
                                    "funding_nothing_to_add",
                                    _("Nothing to add"),
                                    css_class="btn-primary btn-sm",
                                ),
                                css_class="float-right mb-5",
                            ),
                            css_class="col-12",
                        ),
                        css_class="row",
                    ),
                    css_id="funding",
                ),
            ]
        )
        if is_assessor and instance.file != "":
            fields = [
                HTML(
                    """{% load tags %}
                    <div class="table-responsive">
                    <table class="table table-bordered searchable">
                    <tbody>
                    <tr>
                    <th class="table-dark" scope="row" style="width: 21%; min-width: 160px; max-width: 180px;">
                    Completed Report:
                    </th>
                    <td>
                        <a href="{{ object.file.url }}" target="_blank">
                        {{ object.file|basename }}
                        </a>
                    </td>
                    </tr>
                    </tbody>
                    </table>
                    </div>"""
                ),
                "assessment",
            ]
            del self.fields["file"]
            # self.fields["assessment"].required = True
        else:
            del self.fields["assessment"]
            if round.nomination_template:
                help_text = _(
                    'You can download the research report template at <strong><a href="%s">%s</a></strong>'
                ) % (round.report_template.url, os.path.basename(round.report_template.name))
                fields = [
                    HTML(
                        '<div class="alert alert-dark" role="alert">%s</div>'
                        % (
                            _(
                                "Please download the research report template at "
                                '<strong><a href="%s">%s</a></strong>, '
                                "complete then upload below."
                            )
                            % (
                                round.report_template.url,
                                os.path.basename(round.report_template.name),
                            )
                        )
                    ),
                    Field("file", label=help_text, help_text=help_text),
                ]
                self.fields["file"].help_text = help_text
            else:
                fields = ["file"]
            self.fields["file"].widget.attrs[
                "accept"
            ] = ".pdf,.odt,.ott,.oth,.odm,.doc,.docx,.docm,.docb,.rtf,.tex"

        tabs.append(
            Tab(
                mark_safe(f'<i class="fas fa-flag"></i> {_("Report")}'),
                *fields,
                css_id="report",
            )
        )
        if instance and instance.pk:
            if is_assessor:
                self.fields["recipients"] = forms.MultipleChoiceField(
                    label=_("TO"),
                    choices=[(v, v) for v in ["PI", "RO", "RA", "TS"]],
                    required=False,
                    initial=["RO"],
                )
                self.fields["cc_recipients"] = forms.MultipleChoiceField(
                    label=_("CC"),
                    choices=[(v, v) for v in ["PI", "RO", "RA", "TS"]],
                    required=False,
                    initial=["TS"],
                )
                self.fields["to_pi"] = forms.BooleanField(label=_("PI"), required=False)
                self.fields["to_ro"] = forms.BooleanField(
                    label=_("RO"), required=False, initial=True
                )
                self.fields["to_ra"] = forms.BooleanField(label=_("RA"), required=False)
                self.fields["to_ts"] = forms.BooleanField(label=_("TS"), required=False)
                self.fields["cc_pi"] = forms.BooleanField(label=_("PI"), required=False)
                self.fields["cc_ro"] = forms.BooleanField(label=_("RO"), required=False)
                self.fields["cc_ra"] = forms.BooleanField(
                    label=_("RA"), required=False, initial=True
                )
                self.fields["cc_ts"] = forms.BooleanField(label=_("TS"), required=False)
            tabs.append(
                Tab(
                    mark_safe(f'<i class="fas fa-comments"></i> {_("Correspondence")}'),
                    Field("host_contact_email"),
                    Field("comment"),
                    Fieldset(
                        None,
                        Field("attachment"),
                        (
                            Row(
                                Column(
                                    Row(
                                        Column(
                                            HTML("<strong><u>TO</u></strong>:&nbsp;"),
                                            css_class="col-1",
                                        ),
                                        Column(
                                            Field(
                                                "recipients",
                                                template="bootstrap4/layout/recipients_inline.html",
                                            )
                                        ),
                                    ),
                                    Row(
                                        Column(
                                            HTML("<strong><u>CC</u></strong>:&nbsp;"),
                                            css_class="col-1",
                                        ),
                                        Column(
                                            Field(
                                                "cc_recipients",
                                                template="bootstrap4/layout/recipients_inline.html",
                                            )
                                        ),
                                    ),
                                ),
                                Column(
                                    HTML("<strong>Category</strong>:&nbsp;"),
                                    css_class="col-1 text-right",
                                    style="text-align: right; vertical-align: middle; float: right; padding-top: 7px;",
                                ),
                                Column("category"),
                                # "text-align: right; vertical-align: middle; float: right; padding-top: 7px;"
                                Column(
                                    HTML("<strong>Alert date</strong>:&nbsp;"),
                                    css_class="col-1 text-right",
                                    style="text-align: right; vertical-align: middle; float: right; padding-top: 7px;",
                                ),
                                Column(Field("alert_date")),
                                Column(
                                    Submit(
                                        "post_comment",
                                        _("Post Comment"),
                                        css_class="btn-primary float-right",
                                    ),
                                ),
                            )
                            if is_assessor
                            else ButtonHolder(
                                Submit(
                                    "post_comment",
                                    _("Post Comment"),
                                    css_class="btn-primary",
                                ),
                                Button(
                                    "import_email_file",
                                    _("Import Email"),
                                    hx_get=reverse(
                                        "email-import", kwargs={"pk": instance and instance.pk}
                                    )
                                    + "?_modal_dialog=1",
                                    hx_target="#form-dialog",
                                    hx_params="none",
                                    data_toggle="tooltip",
                                    title=_("Import an email file as a comment ..."),
                                    css_class="btn-outline-primary",
                                ),
                                css_class="float-right",
                            )
                        ),
                    ),
                    HTML(
                        '{% include "snippets/comments.html" with comments=object.comments.all %}'
                    ),
                    css_id="correspondence",
                )
            )
        if is_assessor:
            tabs.append(
                Tab(
                    mark_safe(f'<i class="fas fa-flag"></i> {_("Performance")}'),
                    TableInlineFormset(
                        "performance", template="portal/performance_inline_formset.html"
                    ),
                    css_id="performance",
                )
            )
        #     Tab(
        #         _("Research"),
        #         Field("project_title"),
        #         Field("abstract"),
        #         Field("notes"),
        #         css_id="research",
        #     ),
        #     Tab(
        #         _("Personnel"),
        #         TableInlineFormset("personnel"),
        #         css_id="personnel",
        #     ),
        #     Tab(
        #         _("Proposal"),
        #         HTML('{% include "snippets/application_detail_table.html" with a=application %}'),
        #         css_id="proposal",
        #     ),
        #     Tab(
        #         _("Reporting"),
        #         Fieldset(
        #             _("Reporting Schedule"),
        #             TableInlineFormset("reporting_schedule"),
        #             css_id="reporting_schedule",
        #         ),
        #         css_id="reporting",
        #     ),
        #     Tab(
        #         _("Compliance"),
        #         *compliance_fields,
        #         css_id="compliance",
        #     ),
        #     Tab(
        #         mark_safe(f'<i class="fas fa-dollar-sign"></i> {_("Finances")}'),
        #         HTML(
        #             """{% load i18n %}<div class="alert alert-dark" role="alert">
        #             {% blocktrans %}
        #             Funding has been allocated over the award period.
        #             You can distribute it differently, but may not exceed
        #             the total award. All amounts are exclusive of GST.
        #             {% endblocktrans %}
        #             </div>"""
        #         ),
        #         Fieldset(
        #             _("Budget Allocation"),
        #             TableInlineFormset(
        #                 "allocations", template="portal/allocations_table_inline_formset.html"
        #             ),
        #             css_id="allocations",
        #         ),
        #         (
        #             # Field("proposal_budget"),
        #             Fieldset(
        #                 None,
        #                 HTML(
        #                     f"""<div class="input-group mb-2">
        #                 <div class="input-group-prepend">
        #                     <span class="input-group-text">{_("Proposal Budget")}</span>
        #                 </div>
        #                 <div class="form-control d-flex h-auto">
        #                     <span class="text-break" style="flex-grow:1;min-width:0">
        #                     <a href="{proposal_budget_file.url}">
        #                         {os.path.basename(proposal_budget_file.name)}
        #                     </a>
        #                     </span>
        #                 </div>
        #             </div>"""
        #                 ),
        #                 # Submit(
        #                 #     "copy_proposal_budget",
        #                 #     _("Copy"),
        #                 #     css_class="btn-primary float-right",
        #                 #     data_document_action="copy_proposal_budget",
        #                 #     # data_document_role="PB",
        #                 #     data_document_role="PB",
        #                 # ),
        #             )
        #             if proposal_budget_file
        #             else None
        #         ),
        #         Fieldset(
        #             None,
        #             # Field("award_budget", label=""),
        #             Field("budget", label=""),
        #             ButtonHolder(
        #                 Submit(
        #                     "request_budget_correction",
        #                     _("Request Correction"),
        #                     css_class="btn-primary",
        #                     data_document_action="request_correction",
        #                     # data_document_role="PB",
        #                     data_document_role="B",
        #                 ),
        #                 Submit(
        #                     "approve_budget",
        #                     _("Awaiting Approval"),
        #                     css_class="btn-secondary",
        #                     data_document_action="awaiting_approval",
        #                     # data_document_role="AB",
        #                     data_document_role="B",
        #                 ),
        #                 css_class="float-right",
        #             ),
        #         ),
        #         css_id="finances",
        #     ),
        #     Tab(
        #         mark_safe(f'<i class="far fa-file"></i> {_("Appendices")}'),
        #         Div(
        #             DocumentInlineFormset("documents"),
        #             css_id="documents",
        #         ),
        #         css_id="appendices",
        #     ),

        # if instance and instance.pk:
        #     tabs.append(
        #         Tab(
        #             mark_safe(f'<i class="fas fa-comments"></i> {_("Correspondence")}'),
        #             Field("host_contact_email"),
        #             Field("comment"),
        #             Fieldset(
        #                 None,
        #                 Field("attachment"),
        #                 Submit(
        #                     "post_comment",
        #                     _("Post Comment"),
        #                     css_class="btn-primary float-right",
        #                 ),
        #             ),
        #             HTML(
        #                 '{% include "snippets/comments.html" with comments=object.comments.all %}'
        #             ),
        #             css_id="correspondence",
        #         )
        #     )
        self.helper.layout = Layout(
            TabHolder(*tabs),
            ButtonHolder(
                Button("previous", "« " + _("Previous"), css_class="btn-outline-primary"),
                Div(
                    Submit(
                        "save_draft",
                        _("Save"),
                        css_class="btn-primary",
                        data_toggle="tooltip",
                        title=_("Save draft contract"),
                    ),
                    submit_button,
                    HTML(
                        """<a href="{{ view.get_success_url }}"
                        type="button"
                        role="button"
                        class="btn btn-secondary"
                        id="cancel">
                            %s
                        </a>"""
                        % _("Cancel")
                    ),
                    Button("next", _("Next") + " »", css_class="btn-primary"),
                    css_class="float-right",
                ),
                css_class="mb-5",
            ),
        )
        self.helper.include_media = False

    # def save(self, *args, **kwargs):
    #     created = not self.instance.pk
    #     res = super().save(*args, **kwargs)
    #     r = self.instance.application.round
    #     for fn, dr in self.part_fields:
    #         if created or fn in self.changed_data:
    #             file = self.cleaned_data.get(fn, None)
    #             part = self.instance.documents.filter(document_type__role=dr).last()
    #             if part:
    #                 if not file:
    #                     part.delete()
    #                 else:
    #                     part.file.save(
    #                         name=file.name,
    #                         content=file,
    #                     )
    #             elif file:
    #                 required_document = r.required_contract_documents.filter(
    #                     document_type__role=dr
    #                 ).last()
    #                 if not required_document:
    #                     dt = models.DocumentType.where(role=dr).last()
    #                     required_document = models.RequiredContractDocument.create(
    #                         round=r, document_type=dt
    #                     )

    #                 models.ContractDocument.create(
    #                     contract=self.instance, required_document=required_document, file=file
    #                 )

    #     if created or any(
    #         (fn in self.changed_data)
    #         for fn in ["not_applicable", "not_applicable_comment", "ethics_statement"]
    #     ):
    #         es_part = self.instance.documents.filter(document_type__role="E").last()
    #         try:
    #             es = self.instance.ethics_statement
    #         except models.ContractEthicsStatement.DoesNotExist:
    #             es = models.ContractEthicsStatement(contract=self.instance)
    #         es.not_relevant = self.cleaned_data.get("not_applicable", False)
    #         es.comment = self.cleaned_data.get("not_applicable_comment", None)
    #         es.file = es_part and es_part.file
    #         es.save()

    #     return res

    class Meta:
        model = models.Report
        exclude = [
            "address",
            "alert_date",
            "assessed_at",
            "assessor",
            "attachment",
            "category",
            "comment",
            "contract",
            "converted_file",
            "fors",
            "fund",
            "number",
            "org",
            "period",
            "publications",
            "rccs",
            "reported_at",
            "schedule_entry",
            "seos",
            "site",
            "state",
            "submitted_by",
            "type",
        ]
        widgets = dict(
            start_date=DateInput(),
            end_date=DateInput(),
            keywords=autocomplete.ModelSelect2Multiple(
                url="keyword-autocomplete",
                attrs={
                    "data-placeholder": _("Choose a keyword or create a new one ..."),
                },
            ),
            host_contact_email=ModelSelect2NoPK(
                url="org-email-autocomplete",
                attrs={
                    "data-placeholder": _("Select an email addrss or create a new one ..."),
                },
            ),
            panels=autocomplete.ModelSelect2Multiple(url="panel-autocomplete"),
            panel=autocomplete.ModelSelect2(url="panel-autocomplete"),
            abstract=SummernoteInplaceWidget(attrs={"summernote": {"width": "100%"}}),
            notes=SummernoteInplaceWidget(attrs={"summernote": {"width": "100%"}}),
            assessment=SummernoteInplaceWidget(
                attrs={
                    "data-required": 1,
                    "oninvalid": "this.setCustomValidity('%s')" % _("Assessment is required"),
                    "oninput": "this.setCustomValidity('')",
                    "summernote": {"width": "100%", "height": "200px"},
                }
            ),
        )


class ChangeRequestForm(ModelForm):

    description = forms.CharField(
        required=False,
        widget=SummernoteInplaceWidget(attrs={"summernote": {"width": "100%", "height": "200px"}}),
    )
    file = FileField(
        required=False,
        label="Request letter",
        widget=forms.ClearableFileInput(
            attrs={
                "accept": ".doc,.docx,.dot,.dotx,.docm,.dotm,.docb,.odt,.ott,.oth,.odm,.rtf,.tex"
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        initial = kwargs.get("initial", {})
        if initial:
            kwargs["initial"] = initial
        user = kwargs.pop("user", None) or initial and initial.get("user")
        if initial and user and "submitted_by" not in initial:
            initial["submitted_by"] = user

        super().__init__(*args, **kwargs)
        instance = self.instance or kwargs.get("instance")
        contract = (
            instance and instance.pk and instance.contract or initial and initial.get("contract")
        )
        org = contract and contract.org
        is_ro = org and org.research_offices.filter(user=user).exists()
        if is_ro:
            del self.fields["categories"]
            del self.fields["subcategories"]
            # del self.fields["tags"]
            self.fields.pop("tags", None)
        employments_url = reverse("profile-employments")
        educations_url = reverse("profile-educations")
        self.fields["new_host"].help_text = mark_safe(
            _(
                "New host organisation. Make sure that PI is affiliated with the new host organisation: "
                f"<a href='{employments_url}' target='_blank'>employment records</a> "
                f"or <a href='{educations_url}' target='_blank'>education records</a> "
            )
        )
        if contract and (pi := contract.pi):
            self.fields["new_host"].widget.forward.append(forward.Const(pi.pk, "user"))
        submission_disabled = not instance or not is_ro
        helper = FormHelper(self)
        helper.use_custom_control = True
        if not submission_disabled:
            helper.add_input(Submit("save", _("Save Draft"), css_class="btn-secondary"))
            helper.add_input(
                Button(
                    "submit",
                    _("Submit"),
                    css_class="btn-primary",
                    data_toggle="modal",
                    data_target="#id_resolution_modal",
                    data_action="submit",
                )
            )
        else:
            helper.add_input(Submit("save", _("Save"), css_class="btn-secondary"))
            helper.add_input(
                Button(
                    "resubmit",
                    _("Resubmit"),
                    css_class="btn-outline-danger",
                    data_tooltip="tooltip",
                    title=_("Request resubmission of the change request"),
                    data_toggle="modal",
                    data_target="#id_resolution_modal",
                    data_action="resubmit",
                )
            )
            helper.add_input(
                Button(
                    "approve",
                    _("Approve"),
                    css_class="btn-success",
                    data_tooltip="tooltip",
                    title=_(
                        "Approve the change request and convert it to a new contract or a contract variation"
                    ),
                    data_toggle="modal",
                    data_target="#id_resolution_modal",
                    data_action="approve",
                )
            )
        helper.add_input(
            Button(
                "close",
                _("Close"),
                css_class="btn-outline-secondary",
                onclick=f"window.location='{instance.get_absolute_url()}';",
            )
        )
        # if instance and instance.pk:
        #     helper.layout = Layout()
        #     # helper.add_input(
        #     #     Button(
        #     #         "delete",
        #     #         _("Delete"),
        #     #         css_class="btn-outline-danger",
        #     #         onclick=f"window.location='{instance.get_delete_url()}';",
        #     #     )
        #     # )
        self.helper = helper

    def save(self, *args, **kwargs):
        instance = self.instance
        # created = not self.instance.pk
        contract = self.initial.get("contract")
        if isinstance(contract, int):
            contract = models.Contract.get(pk=contract)
        if not instance.contract_id and contract:
            instance.contract = contract
            instance.number = self.instance.get_number(contract)
        res = super().save(*args, **kwargs)
        return res

    class Meta:
        model = models.ChangeRequest
        exclude = [
            "tags",
            "contract",
            "derivative",
            # "submitted_by",
            "state",
            "state_changed_at",
            "converted_file",
            "reply",
        ]
        help_texts = {"tags": ""}
        widgets = dict(
            submitted_by=HiddenInput(),
            contract=HiddenInput(),
            file=forms.ClearableFileInput(
                attrs={"accept": ".xls,.xlw,.xlt,.xml,.xlsx,.xlsm,.xltx,.xltm,.xlsb,.csv,.ctv"}
            ),
            # start_date=DateInput(),
            # end_date=DateInput(),
            new_host=autocomplete.ModelSelect2(
                "org-autocomplete",
                forward=["contract"],
                attrs={"data-placeholder": _("Choose an organisation or create a new one ...")},
            ),
            categories=autocomplete.ModelSelect2Multiple(
                url="change-category-autocomplete",
                forward=[
                    "types",
                    forward.Const("1", "level"),
                ],
            ),
            subcategories=autocomplete.ModelSelect2Multiple(
                url="change-category-autocomplete",
                forward=[
                    "types",
                    "categories",
                    forward.Const("2", "level"),
                ],
            ),
            types=autocomplete.ModelSelect2Multiple(url="change-type-autocomplete"),
            tags=autocomplete.TagSelect2(
                url="tag-autocomplete",
                attrs={
                    "data-placeholder": _(
                        "Please enter a tag or multiple tags. You can select multiple tags..."
                    ),
                },
            ),
        )


# vim:set ft=python.django:
