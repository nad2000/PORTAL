import os
from functools import partial

from crispy_forms.bootstrap import Tab, TabHolder, InlineRadios

# from crispy_forms.bootstrap import Modal
from crispy_forms.helper import FormHelper
from crispy_forms.layout import (
    Hidden,
    HTML,
    TEMPLATE_PACK,
    BaseInput,
    Button,
    ButtonHolder,
    Column,
    Div,
    Field,
    Fieldset,
    Layout,
    LayoutObject,
    Row,
)
from dal import autocomplete
from django import forms
from django.conf import settings
from django.forms import FileField, HiddenInput, Widget, inlineformset_factory
from django.forms.models import BaseInlineFormSet, modelformset_factory
from django.forms.widgets import NullBooleanSelect, Select, TextInput
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
from .models import DOCUMENT_ROLES

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

        super().__init__(attrs=attrs, format=format)


YearInput = partial(DateInput, attrs={"class": "form-control yearpicker", "type": "text"})
# FileInput = partial(FileInput, attrs={"class": "custom-file-input", "type": "file"})
# FileInput = partial(FileInput, attrs={"class": "custom-file-input"})


class InvitationStateInput(Widget):
    # def __init__(self, attrs=None):
    #     super().__init__(attrs)
    #     breakpoint()
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
        return render_to_string(self.template, {"formset": formset, "form_id": self.form_id})


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
        document_type = f"{required_document.document_type}"

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
    template = "portal/application_document_formset.html"

    def render(self, form, form_style, context, template_pack=TEMPLATE_PACK):
        formset = context[self.formset_name_in_context]

        required_documents = context["required_documents"]
        round = context["round"]
        ordering = dict(
            round.required_documents.values_list("id", "ordering").order_by("ordering")
        )
        formset.forms.sort(key=lambda f: ordering.get(f.initial.get("required_document"), 0))
        help_texts = {
            rd_id: make_help_text(
                required_document=round.required_documents.filter(id=rd_id).first()
            )
            for rd_id in ordering.keys()
        }
        for f in formset.forms:
            rd_id = f.initial.get("required_document", 0)
            if rd_id:
                # f.file.help_text = help_texts.get(rd_id)
                f.fields["file"].help_text = help_texts.get(rd_id)
                f.form_label = f"{required_documents.get(rd_id, _('Document'))}"

        return render_to_string(
            self.template,
            {
                "formset": formset,
                "form_id": self.form_id,
                "required_documents": required_documents,
            },
        )


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


class SubscriptionForm(forms.ModelForm):
    class Meta:
        model = models.Subscription
        exclude = [
            "site",
        ]


class UserForm(forms.ModelForm):
    class Meta:
        model = models.User
        fields = ["title", "first_name", "middle_names", "last_name"]
        widgets = {
            "title": autocomplete.ModelSelect2(
                "title-autocomplete",
                attrs={"data-placeholder": _("Choose your title or create a new one ...")},
            ),
        }


class ProfileForm(forms.ModelForm):
    def clean_is_accepted(self):
        """Allow only 'True'"""
        if not self.cleaned_data["is_accepted"]:
            raise forms.ValidationError(_("Please read and consent to the Privacy Policy"))
        return True

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
            date_of_birth=DateInput(start_date="-100y", end_date="-6y"),
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


class ApplicationForm(forms.ModelForm):
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
            attrs={"accept": ".pdf,.odt,.ott,.oth,.odm,.doc,.docx,.docm,.docb,.rtf,.tex"}
        ),
    )

    @cached_property
    def was_submitted(self):
        return "submit" in self.data

    def clean(self):
        cleaned_data = super().clean()
        if self.was_submitted and (round := self.round):
            if round.research_experience_in_years_required and not (
                cleaned_data.get("research_experience_in_years")
            ):
                self.add_error(
                    "research_experience_in_years", _("Research experience in years required")
                )

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
                and settings.SITE_ID != 4
            ):
                raise forms.ValidationError(
                    _("Need to attach a CV before submitting the application."),
                )

        return self.cleaned_data.get("cv_file")

    def save(self, *args, **kwargs):
        if (
            self.cleaned_data.get("letter_of_support_file") is False
            and self.instance
            and (los := self.instance.letter_of_support)
        ):
            self.instance.letter_of_support = None
            los.delete()

        if (
            self.cleaned_data.get("cv_file") is False
            and self.instance
            and self.instance.round
            and self.instance.round.applicant_cv_required
            and self.instance.round.curriculum_vitae_templates.count() > 0
        ):
            self.instance.cv = None

        return super().save(*args, **kwargs)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        initial = kwargs.get("initial", {})
        user = initial.get("user")
        language = get_language()
        site_id = settings.SITE_ID
        if site_id == 4:
            self.fields["application_title"].label = _("Title of proposed research")
            self.fields["application_title_en"].label = f'{_("Title of proposed research")} [en]'
            self.fields["application_title_mi"].label = f'{_("Title of proposed research")} [mi]'

        self.helper = FormHelper(self)
        instance = self.instance
        # self.helper.help_text_inline = True
        # self.helper.html5_required = True

        fields = [
            Fieldset(
                (
                    _("Team representative")
                    if instance and instance.is_team_application
                    else _("Individual applicant")
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
                Column("org", css_class="col-9"),
                Column("position", css_class="col-3"),
            ),
            "postal_address",
            Row(Column("city"), Column("postcode")),
            # Row(Column("daytime_phone"), Column("mobile_phone")),
            Row(
                Column(
                    Field(
                        "daytime_phone",
                        pattern=r"\+?[0-9- ]+",
                        placeholder="e.g., +64 4 472 7421",
                    )
                ),
                Column(
                    Field(
                        "mobile_phone",
                        pattern=r"\+?[0-9-]+",
                        placeholder="e.g., +64 4 472 7421",
                    )
                ),
            ),
            # ButtonHolder(Submit("submit", "Submit", css_class="button white")),
        ]
        if instance.submitted_by and not instance.submitted_by == user:
            fields.append(Field("is_tac_accepted", type="hidden"))

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
            self.fields["presentation_url"].required = True
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
            if round.research_experience_in_years_required:
                category_fields = [Field("research_experience_in_years")]
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
                                 <span class="rcorners" style="text-align: right; color: gray; font-weight: normal;" id="id_application_toa_total_share"></span>
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
                            Row(Column("vm_rationane")),
                            # Row(Column("rationane_vm_na"), css_id="id_vm_na"),
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
                        if site_id == 4
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
            if site_id == 4:
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
                if site_id == 4:
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
                    Field("is_tac_accepted"),
                    css_id="tac",
                ),
            )

        submission_disabled = (
            not instance.is_tac_accepted
            and instance.submitted_by
            and instance.submitted_by != user
        )
        submit_button = Submit(
            "submit",
            _("Submit"),
            # disabled=not instance.is_tac_accepted,  # and instance.submitted_by != user,
            data_toggle="tooltip",
            title=(
                _(
                    "Your team leader must accept the Terms and Conditions before the submission can happen"
                )
                if submission_disabled
                else _("Submit the application")
            ),
            css_class="btn-outline-primary",
            disabled=submission_disabled,
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
                        title=_("Save draft application"),
                    ),
                    submit_button,
                    HTML("""<a href="{{ view.get_success_url }}"
                        type="button"
                        role="button"
                        class="btn btn-secondary"
                        id="cancel">
                            %s
                        </a>""" % _("Cancel")),
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
            "organisation",
            "round",
            "seos",
            "site",
            "state",
            "submitted_by",
        ]
        widgets = dict(
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
            title=autocomplete.ModelSelect2(
                "title-autocomplete",
                attrs={"data-placeholder": _("Choose your title or create a new one ...")},
            ),
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
        )
        labels = {"keywords": ""}
        help_texts = {
            "vm_ecs": None,
            "vm_ens": None,
            "vm_hsw": None,
            "vm_ink": None,
        }


class ContractMemberForm(FTEMixin, forms.ModelForm):
    class Meta:
        model = models.ContractMember
        fields = "__all__"
        disabled = ["state"]
        widgets = dict(user=HiddenInput(), state=InvitationStateInput(attrs={"readonly": True}))


class AllocationForm(forms.ModelForm):
    class Meta:
        model = models.Allocation
        fields = ["period", "allocation"]
        widgets = {"period": TextInput(attrs={"readonly": "readonly"})}


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


class ContractForm(forms.ModelForm):
    # fund = forms.ModelChoiceField(queryset=models.Fund.objects.order_by("code"))
    part_fields = (
        ("research_aims", DOCUMENT_ROLES.AIMS),
        ("project_timeline", DOCUMENT_ROLES.PT),
        ("proposal_budget", DOCUMENT_ROLES.PB),
        ("award_budget", DOCUMENT_ROLES.AB),
        ("ethics_statement", DOCUMENT_ROLES.E),
    )
    not_applicable = forms.BooleanField(label=_("Not Applicable"), required=False)
    not_applicable_comment = forms.CharField(
        label=_("Comment"), widget=forms.Textarea, required=False
    )
    has_animal_use = forms.ChoiceField(
        choices=[(True, _("Yes")), (False, _("No")), ("", _("N/A"))],
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
    involves_childeren = forms.ChoiceField(
        choices=[(True, _("Yes")), (False, _("No")), ("", _("N/A"))],
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

    research_aims = FileField(
        required=False,
        widget=forms.ClearableFileInput(
            attrs={"accept": ".pdf,.odt,.ott,.oth,.odm,.doc,.docx,.docm,.docb"},
        ),
    )

    project_timeline = FileField(
        required=False,
        widget=forms.ClearableFileInput(
            attrs={"accept": ".xls,.xlw,.xlt,.xml,.xlsx,.xlsm,.xltx,.xltm,.xlsb,.csv,.ctv"}
        ),
    )

    proposal_budget = FileField(
        required=False,
        widget=forms.ClearableFileInput(
            attrs={"accept": ".xls,.xlw,.xlt,.xml,.xlsx,.xlsm,.xltx,.xltm,.xlsb,.csv,.ctv"}
        ),
    )

    award_budget = FileField(
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
            if es := models.ContractEthicsStatement.where(contract=instance).last():
                initial["not_applicable"] = es.not_relevant or False
                initial["not_applicable_comment"] = es.comment or ""

        super().__init__(*args, **kwargs)
        # language = get_language()
        instance = self.instance or instance
        application = instance.application or initial.get("application")
        site_id = settings.SITE_ID
        if site_id == 4:
            self.fields["project_title"].label = _("Title of proposed research project")
            # self.fields["application_title_en"].label = f'{_("Title of proposed research")} [en]'
            # self.fields["application_title_mi"].label = f'{_("Title of proposed research")} [mi]'

        # r = self.instance.application.round
        # parts = dict((v, v) for f, v in self.part_fields)
        parts = (
            {p.document_type.role: p for p in instance.documents.prefetch_related("document_type")}
            if instance.pk
            else {}
        )

        submission_disabled = not instance or (
            instance.submitted_by and instance.submitted_by != user
        )
        is_pi = instance and (
            instance.submitted_by == user
            or (instance.pk and instance.members.filter(user=user, role__code="PI").exists())
            or application.submitted_by == user
        )
        is_ro = application and application.org.research_offices.filter(user=user).exists()
        submit_button = Submit(
            "submit_contract",  # NB! Never call a button 'submit'!
            _("Submit"),
            # disabled=not instance.is_tac_accepted,  # and instance.submitted_by != user,
            data_toggle="tooltip",
            title=(
                _("Only P.I. can submit the contract")
                if not is_pi
                else (
                    _("Not all the parts/appendices of the contract were approved and/or accepted")
                    if submission_disabled
                    else _("Submit the contract")
                )
            ),
            css_class="btn-outline-primary",
            disabled=submission_disabled or not is_pi,
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
                        "Please provide an ethic from. If this is not applicable to your application, "
                        'click "Not Applicable" and state why in the comment.'
                    )
                ),
            ]
            if is_pi or is_ro
            else []
        )
        disabled_compliance = not (is_pi or is_ro)
        compliance_fields.extend(
            [
                Field("ethics_statement", label=_("Ethics Statement")),
                "not_applicable",
                "not_applicable_comment",
            ]
        )
        if not disabled_compliance:
            compliance_fields.append(
                HTML(
                    '<p class="text-warning">%s</p>'
                    % _(
                        "Royal Society Te Apārangi and other institutions are signatories to teh ANZCCART "
                        "Openness Agreement on Animal Research and Teaching in New Zealand ... TODO:..."
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
                    '<p class="text-warning">%s</p>'
                    % _(
                        "It is necessary for the Researcher to notify if children "
                        "are involved in the research and therefor "
                        "subject to Section 19 of the Vulnerable Children's Act 2014. All ... TODO:..."
                    )
                )
            )
        compliance_fields.extend(
            [
                InlineRadios("involves_childeren"),
                InlineRadios("has_child_protection"),
            ]
        )
        if instance and instance.pk:
            es = models.ContractEthicsStatement.where(contract=instance).last()
            if es and es.not_relevant:
                self.fields["not_applicable_comment"].required = True

        if disabled_compliance:
            self.fields["ethics_statement"].disabled = True
            self.fields["has_animal_use"].disabled = True
            self.fields["is_signatory_to_oa"].disabled = True
            self.fields["involves_childeren"].disabled = True
            self.fields["has_child_protection"].disabled = True
            self.fields["not_applicable"].disabled = True
            self.fields["not_applicable_comment"].disabled = True
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
                        Field("start_date", type="hidden", css_class="hidden"),
                        Field("end_date", type="hidden", css_class="hidden"),
                    ]
                    if self.instance and self.instance.id
                    else [
                        HTML('<div class="alert alert-dark" role="alert">TODO: ...</div>'),
                        Field("start_date"),
                        Field("end_date"),
                    ]
                ),
                css_id="summary",
            ),
            Tab(
                _("Research"),
                Field("project_title"),
                Fieldset(
                    None,
                    Field("research_aims", label=""),
                    Submit(
                        "approve_research_aims",
                        _("Approve"),
                        data_toggle="tooltip",
                        data_enabled_title=_("Approve research aims"),
                        data_disabled_title=_("Please upload research aims before approving it"),
                        data_document_role="AIMS",
                        title=(
                            _("Approve research aims")
                            if "AIMS" in parts
                            else _("Please upload research aims before approving it")
                        ),
                        css_class="btn-primary float-right",
                        # css_class="btn-outline-primary",
                        disabled=("AIMS" not in parts and "research_aims" not in self.initial),
                        css_id="id_approve_research_aims",
                    ),
                    css_id="research_aims_fieldset",
                ),
                Fieldset(
                    None,
                    Field("project_timeline", label=""),
                    Submit(
                        "approve_project_timeline",
                        _("Approve"),
                        data_document_role="PT",
                        data_toggle="tooltip",
                        data_enabled_title=_("Submit the application"),
                        data_disabled_title=_(
                            "Please upload project timeline before approving it"
                        ),
                        title=(
                            _("Approve project timeline")
                            if "PT" in parts
                            else _("Please upload project timeline before approving it")
                        ),
                        css_class="btn-primary float-right",
                        # css_class="btn-outline-primary",
                        disabled=("PT" not in parts and "project_timeline" not in self.initial),
                    ),
                    css_id="project_timeline_fieldset",
                ),
                Field("abstract"),
                Field("notes"),
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
                    TableInlineFormset("reporting_schedule"),
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
                HTML("""{% load i18n %}<div class="alert alert-dark" role="alert">
                    {% blocktrans %}
                    Funding has been allocated over the award period.
                    You can distributed it differently, but may not exceed
                    the total award. All amounts are exclusive of GST.
                    {% endblocktrans %}
                    </div>"""),
                Fieldset(
                    _("Budget Allocation"),
                    TableInlineFormset(
                        "allocations", template="portal/allocations_table_inline_formset.html"
                    ),
                    css_id="allocations",
                ),
                Field("proposal_budget"),
                Fieldset(
                    None,
                    Field("award_budget", label=""),
                    ButtonHolder(
                        Submit(
                            "request_budget_correction",
                            _("Request Correction"),
                            css_class="btn-primary",
                            data_document_action="request_correction",
                            data_document_role="PB",
                        ),
                        Submit(
                            "approve_budget",
                            _("Awaiting Approval"),
                            css_class="btn-secondary",
                            data_document_action="awaiting_approval",
                            data_document_role="AB",
                        ),
                        css_class="float-right",
                    ),
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
                    Field("host_contact_email"),
                    Field("comment"),
                    Fieldset(
                        None,
                        Field("attachment"),
                        Submit(
                            "post_comment",
                            _("Post Comment"),
                            css_class="btn-primary float-right",
                        ),
                    ),
                    HTML(
                        '{% include "snippets/contract_comments.html" with comments=object.comments.all %}'
                    ),
                    css_id="correspondence",
                )
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
                        title=_("Save draft contract"),
                    ),
                    submit_button,
                    HTML("""<a href="{{ view.get_success_url }}"
                        type="button"
                        role="button"
                        class="btn btn-secondary"
                        id="cancel">
                            %s
                        </a>""" % _("Cancel")),
                    Button("next", _("Next") + " »", css_class="btn-primary"),
                    css_class="float-right",
                ),
                css_class="mb-5",
            ),
        )
        self.helper.include_media = False

    def save(self, *args, **kwargs):
        created = not self.instance.pk
        res = super().save(*args, **kwargs)
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
            "site",
            "fund",
            "host_number",
            "org",
            "application",
            "number",
            "submitted_by",
            "rccs",
            "fors",
            "seos",
            "keywords",
            "state",
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
        )


class MemberForm(FTEMixin, ReadOnlyFieldsMixin, FormWithStateFieldMixin, forms.ModelForm):
    readonly_fields = ["state"]

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
                    _("Team member with the email address %(email)s was alrady added"),
                    params={"email": email},
                )
        return cleaned_data

    class Meta:
        model = models.Member
        fields = ["state", "email", "first_name", "middle_names", "last_name", "role"]
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


class RefereeForm(ReadOnlyFieldsMixin, FormWithStateFieldMixin, forms.ModelForm):
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
                    _("Referee with the email address %(email)s was alrady added"),
                    params={"email": email},
                )
        return cleaned_data

    class Meta:
        model = models.Referee
        fields = ["state", "email", "first_name", "middle_names", "last_name"]
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


class ProfileCareerStageForm(forms.ModelForm):
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


class ProfilePersonIdentifierForm(forms.ModelForm):
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


class NominationForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        r = kwargs["initial"].get("round") or self.instance.round
        site_id = settings.SITE_ID

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
                    if site_id == 4
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
            "org",
            HTML("""
            <div id="div_id_nominator" class="form-group">
            <label for="id_nominator" class=" requiredField">%s</label>
                <div class="">
                    <input
                        value="{{ nominator.full_name_with_email }}"
                        disabled="" class="input form-control">
                </div>
            </div>
            """ % _("Nominator")),
        ]
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
                        % (r.nomination_template.url, os.path.basename(r.nomination_template.name))
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

    class Meta:
        model = models.Nomination
        fields = [
            # "round",
            "nominator",
            "title",
            "first_name",
            "middle_names",
            "last_name",
            "email",
            "org",
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
            # round=HiddenInput(),
            # summary=SummernoteInplaceWidget(),
        )


class TestimonialForm(forms.ModelForm):
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
        fields = [
            Field("file", data_toggle="tooltip", title=self.fields["file"].help_text),
            # Field("summary"),
            # Field("referee"),
        ]
        if site_id == 4:
            self.fields["file"].label = ""
        if round.referee_template:
            help_text = _(
                'You can download the application review form template at <strong><a href="%s">%s</a></strong>'
            ) % (round.referee_template.url, os.path.basename(round.referee_template.name))
            # fields.insert(0, HTML(f'<div class="alert alert-info" role="alert">{help_text}</div>'))
            self.fields["file"].help_text = help_text
        self.fields["file"].required = True
        fields = [
            Fieldset(_("Referee Report") if site_id == 4 else _("Testimonial"), *fields),
        ]

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
                        if site_id == 4
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

        # widgets = dict(
        #     summary=SummernoteInplaceWidget(),
        # )


class IdentityVerificationForm(forms.ModelForm):
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
                HTML("""
                    <a href="{{ view.get_success_url }}"
                    type="button"
                    role="button"
                    class="btn btn-secondary"
                    id="cancel">
                        %s
                    </a>""" % _("Cancel")),
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


class PanellistForm(ReadOnlyFieldsMixin, FormWithStateFieldMixin, forms.ModelForm):
    readonly_fields = ["state"]
    confirm_deletion = True

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
                            {str(e)}</a></li>""" for e in evaluations
                    )
                message += "</ul>"
            message += "<ul>"
            return message

        return _(
            "Do you wish to delete the selected panellist and all linked data entries to this panellist?"
        )

    class Meta:
        model = models.Panellist
        exclude = ("site",)
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
        self.add_input(Submit("cancel", _("Cancel"), css_class="btn-danger"))


class ConflictOfInterestForm(forms.ModelForm):
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


class ScoreForm(forms.ModelForm):
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


class RoundConflictOfInterestForm(forms.ModelForm):
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


class ScoreSheetForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.helper = FormHelper()
        super().__init__(*args, **kwargs)

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


# vim:set ft=python.django:
