from os.path import basename

from crispy_forms.utils import render_crispy_form
from django.contrib import messages
from django.templatetags.static import static
from django.urls import reverse
from django.utils import translation
from jinja2 import Environment, pass_context


@pass_context
def crispy(context, form, helper=None):
    return render_crispy_form(form, helper=getattr(form, "helper", helper), context=context)


def environment(**options):
    options.update({"extensions": ["jinja2.ext.i18n"]})
    env = Environment(**options)
    env.globals.update(
        {
            "get_messages": messages.get_messages,
            "crispy": crispy,
            "static": static,
            "url": lambda viewname, urlconf=None, current_app=None, *args, **kwargs: reverse(
                viewname=viewname,
                urlconf=urlconf,
                args=args or None,
                kwargs=kwargs or None,
                current_app=current_app,
            ),
        }
    )
    env.filters["basename"] = basename
    env.install_gettext_translations(translation)
    return env
