from os.path import basename

from crispy_forms.templatetags.crispy_forms_filters import (
    as_crispy_form,  # this line is different
)
from django.contrib import messages
from django.templatetags.static import static
from django.urls import reverse
from django.utils import translation
from jinja2 import Environment


def environment(**options):
    options.update({"extensions": ["jinja2.ext.i18n"]})
    env = Environment(**options)
    env.globals.update(
        {
            "get_messages": messages.get_messages,
            "crispy": as_crispy_form,
            "static": static,
            "url": reverse,
        }
    )
    env.filters["basename"] = basename
    env.install_gettext_translations(translation)
    return env
