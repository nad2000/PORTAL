from os.path import basename

from django.conf import settings
from crispy_forms.utils import render_crispy_form
from django.contrib import messages
from django.templatetags.static import static
from django.db.models import Q
from django.urls import reverse
from django.utils import translation
from jinja2 import Environment, pass_context, BaseLoader, TemplateNotFound, ChoiceLoader
# from dbtemplates.models import Template
from django.utils.safestring import mark_safe


class DbLoader(BaseLoader):

    def get_source(self, environment, template):
        # site = Site.objects.get_current()
        # site_id = site and site.pk
        site_id = int(settings.SITE_ID)   # if it uses 'django-multisite'
        t = (
            Template.objects.filter(
                Q(name__exact=template), Q(sites__pk=site_id) | Q(sites__isnull=True)
            )
            .order_by("-sites__pk")
            .first()
        )
        if not t:
            raise TemplateNotFound(template)
        lc = t.last_changed
        pk = t.pk
        return (
            t.content,
            f"{template}::{pk}::{site_id}",
            lambda: not (Template.objects.filter(pk=pk, last_changed__gt=lc).exists()),
        )


@pass_context
def crispy(context, form, helper=None):
    return render_crispy_form(form, helper=getattr(form, "helper", helper), context=context)


def summernote(note):
    """Change relative URLs into the abosolute and make it safe."""
    return note and mark_safe(note.replace(settings.MEDIA_URL, f"file://{settings.MEDIA_ROOT}/"))


def environment(loader=None, **options):
    if loader:
        options["loader"] = loader
        # options["loader"] = ChoiceLoader(
        #     [
        #         DbLoader(),
        #         loader,
        #     ]
        # )

    env = Environment(**options)
    env.globals.update(
        {
            "get_messages": messages.get_messages,
            "crispy": crispy,
            "static": static,
            "mark_safe": mark_safe,
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
    env.filters["safe"] = mark_safe
    env.filters["summernote"] = summernote
    env.install_gettext_translations(translation)
    return env
