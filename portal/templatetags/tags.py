import os
from itertools import groupby
from operator import itemgetter
from urllib.parse import parse_qs

# import jinja2
from django import forms, template
from django.db import models
from django.forms.widgets import NullBooleanSelect
from django.template.loader import get_template
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from markupsafe import Markup

from .. import models as m

register = template.Library()


@register.filter(is_safe=True)
def color_variant(hex_color, brightness_offset=1):
    """takes a color like #87c95f and produces a lighter or darker variant"""
    if len(hex_color) != 7:
        raise Exception(
            "Passed %s into color_variant(), needs to be in #87c95f format." % hex_color
        )
    rgb_hex = [hex_color[x : x + 2] for x in [1, 3, 5]]
    new_rgb_int = [int(round(int(hex_value, 16) * brightness_offset)) for hex_value in rgb_hex]
    new_rgb_int = [
        min([255, max([0, i])]) for i in new_rgb_int
    ]  # make sure new values are between 0 and 255
    # hex() produces "0x88", we want just "88"
    return "#" + "".join([hex(i)[2:] for i in new_rgb_int])


@register.filter
def index(indexable, i):
    return indexable[i]


@register.filter(is_safe=True)
def eq_value(value1, value2):
    return str(value1 or "").strip() == str(value2 or "").strip()


@register.filter()
def is_data_required(field):
    if field.field.widget.attrs and (av := field.field.widget.attrs.get("data-required")):
        return av == 1 or av == "1"


@register.filter(is_safe=True)
def html(obj):
    if not obj:
        return ""
    if hasattr(obj, "__html__"):
        return mark_safe(obj.__html__())
    return mark_safe(f"<pre>{obj}</pre>")


@register.filter
def get_item(hashable, key):
    return hashable.get(key) or isinstance(key, str) and key.isdigit() and hashable.get(int(key))


@register.filter()
def collapsible(value):
    """collapsible if the text length exceeds ML and remainder is more then 20% of the text."""
    ml = 400  # max length
    if value and (s := value.strip()) and (l := len(s)) > ml:
        return (l - ml) / l > 1.0


@register.filter()
def dump(value):
    """User can edit the application."""
    if not isinstance(value, dict):
        data = {k: getattr(value, k) for k in dir(value)}
    else:
        data = value
    return "\r\n".join(f"\t<b>{k}</b>: {v}" for k, v in data.items())


@register.filter()
def has_tooltip(value):
    return hasattr(value, "flat_attrs") and "tooltip" in value.flat_attrs


@register.filter()
def can_edit(value, user):
    """User can edit the application."""
    return user.is_authenticated and (
        value.submitted_by == user
        or value.members.all().filter(user=user).exists()
        # or (value.site_id == 4 and value.org.where(research_offices__user=user).exists())
    )


@register.filter()
def is_ro(value, user):
    """User is a research officer of the organisation."""
    return user.is_authenticated and (value.org.where(research_offices__user=user).exists())


@register.filter()
def can_see_referees(value, user):
    """User can access list of the referees - applicants or panellists."""
    return user.is_authenticated and (
        value.submitted_by == user
        or user.is_superuser
        or user.staff_of_sites.filter(pk=value.site_id).exists()
        or value.round.panellists.all().filter(user=user).exists()
        or (value.org and value.org.where(research_offices__user=user).exists())
    )


@register.filter()
def field_value(value, name, *args, **kwargs):
    """Returns the value of the field of an object."""
    try:
        v = getattr(value, name)
    except AttributeError:
        return _("N/A")
    if v:
        if isinstance(v, m.User):
            return v.full_name_with_email
        if name in ["state", "status"]:
            if state_changed_at := getattr(value, "state_changed_at", None):
                return mark_safe(
                    f"""<span data-toggle="tooltip"
                    title="{_('(the state was updated at %s)') % state_changed_at.strftime('%d-%m-%Y %H:%m')}
                    ">&lt;<b>{v.upper()}</b>&gt</span>"""
                )
            return mark_safe(f"&lt;<b>{v.upper()}</b>&gt;")
    if isinstance(v, bool):
        return _("yes") if v else _("no")
    f = value._meta.get_field(name)
    if isinstance(f, models.BooleanField):
        return _("yes") if v else _("no")
    return _("N/A") if v is None or v == "" else v


@register.filter()
def field_is_empty(value, name):
    if not value or not hasattr(value, name):
        return True
    v = getattr(value, name)
    return v is None or v == ""


@register.filter()
def field_file_name(value, name="file"):
    if not value:
        return _("N/A")
    v = getattr(value, name)
    return v.name if v else None


@register.filter()
def field_file_url(value, name="file"):
    if not value:
        return _("N/A")
    v = getattr(value, name)
    return v.url if v else None


@register.filter()
def fields(value):
    return value and value._meta.fields or []


@register.filter()
def disabled_readonly(value):
    attrs = value.field.widget.attrs
    return attrs.get("readonly") and attrs.get("disabled")


@register.filter()
def is_disabled_readonly_checkbox(value):
    attrs = value.field.widget.attrs
    return (
        isinstance(value.field.widget, forms.CheckboxInput)
        and attrs.get("readonly")
        and attrs.get("disabled")
    )


@register.filter()
def is_readonly_nullbooleanfield(value):
    attrs = value.field.widget.attrs
    return isinstance(value.field.widget, NullBooleanSelect) and attrs.get("readonly")


@register.filter()
def is_file_field(value):
    return isinstance(value, models.FileField)


@register.filter()
def person_name(value, with_email=False):
    if hasattr(value, "user"):
        u = value.user
    elif hasattr(value, "submitted_by"):
        u = value.submitted_by
    else:
        u = None

    output = f"{value.title} " if hasattr(value, "title") and value.title else ""
    output += value.first_name or u and u.first_name or ""

    if (
        middle_names := u
        and u.middle_names
        or hasattr(value, "middle_names")
        and value.middle_names
        or ""
    ):
        output = f"{output} {middle_names}"

    output = f"{output} {u and u.last_name or value.last_name or ''}"
    if with_email:
        output = f"{output} ({u and u.email or value.email})"

    if role := hasattr(value, "role") and value.role:
        output = f"{output}, {role}"

    return output


@register.filter()
def person_with_email(value):
    return person_name(value, with_email=True)


@register.filter()
def basename(value):
    if value and isinstance(value, models.fields.files.FieldFile):
        return os.path.basename(value.name)
    return os.path.basename(value) if value else ""


@register.filter()
def all_scores(value, criteria):
    """Get full list of the scores based on the list of the criteria"""
    yield from value.all_scores(criteria)


@register.filter()
def video_id(value):
    """Get full list of the scores based on the list of the criteria"""
    # https://www.youtube.com/watch?v=NsUWXo8M7UA
    # https://youtu.be/NsUWXo8M7UA
    # https://www.youtube.com/embed/NsUWXo8M7UA
    # https://vimeo.com/60803861
    url, *rest = value.split("?")

    if rest and (qs := parse_qs(rest[0])) and "v" in qs:
        return qs["v"][0]
    return url.split("/")[-1]


@register.filter()
def user_has_nomination(value, user):
    return value.user_has_nomination(user)


@register.simple_tag(takes_context=True)
# @jinja2.pass_context
def jinja(context, template, *args, **kwargs):
    # request = context.get("request")
    # site = context.get("site")
    # contract = object = context.get("object")
    # schedule_entries = {e.period: e for e in contract.reporting_schedule.all().order_by("period", "due_date")}
    output = get_template(template).render(context)
    return Markup(output)


@register.simple_tag(takes_context=True)
# @jinja2.pass_context
def contract_summary(context, *args, **kwargs):
    request = context.get("request")
    site = context.get("site")
    contract = object = context.get("object")
    # schedule_entries = {e.period: e for e in contract.reporting_schedule.all().order_by("period", "due_date")}
    output = get_template("contract_summary.html").render(locals())
    return Markup(output)


@register.simple_tag(takes_context=True)
def document_action_button(
    context,
    required_document=None,
    document=None,
    document_role=None,
    document_file_field="file",
    *args,
    **kwargs,
):
    request = context.get("request")
    # required_document = kwargs.get("required_document")
    # site = context.get("site")
    object = context.get("object")
    if not required_document and document:
        required_document = document.required_document
    if not required_document and document_role and object.pk:
        required_document = object.required_documents.filter(
            document_type__role=document_role
        ).last()
    # user = context.get("user")
    form = context.get("form")
    rd_id = context.get("rd_id") or required_document.pk

    is_ro = context.get("is_ro")
    action = kwargs.get("action") or context.get("action") or "approve"

    document_file = (
        form.initial.get(document_file_field) or (document and document.file) or form.instance.file
    )
    if not document_file:
        if action == "approve":
            disabled_tooltip_text = _(
                f"Please upload { required_document } before  before approving it"
            )
        else:
            disabled_tooltip_text = _(
                f"Please upload { required_document } before requesting corrections"
            )
    else:
        state = (document and document.state) or form.instance.state
        if not is_ro or state == "accepted":
            disabled_tooltip_text = _(f"{ required_document } was already accepted")
        elif state == "approved":
            disabled_tooltip_text = _(f"{ required_document } was already approved")
    if action == "approve":
        if is_ro:
            enabled_tooltip_text = _(f"Approve { required_document }")
            button_label = _("Approve")
        else:
            enabled_tooltip_text = _(f"Accept { required_document }")
            button_label = _("Accept")
    else:
        enabled_tooltip_text = _(f"Request correction of { required_document }")
        button_label = _("Request Correction")

    # schedule_entries = {e.period: e for e in contract.reporting_schedule.all().order_by("period", "due_date")}
    output = get_template("document_action_button.html").render(locals())
    return Markup(output)
