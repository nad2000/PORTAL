import base64
import csv
import io
import json
import mimetypes
import os
import re
import shutil
import traceback
from datetime import timedelta
from decimal import Decimal
from functools import wraps
from itertools import groupby
from urllib.parse import quote, urljoin
from wsgiref.util import FileWrapper

import django.utils.translation
import django_tables2
import jinja2
import py7zr
import rispy
import tablib
from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount, SocialApp
from crispy_forms import bootstrap, layout
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Column, Field, Fieldset, Layout, Row
from dal import autocomplete, forward
from dateutil.parser import parse
from dateutil.relativedelta import relativedelta
from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import (
    AccessMixin,
    LoginRequiredMixin,
    UserPassesTestMixin,
)
from django.contrib.contenttypes.forms import (
    BaseGenericInlineFormSet,
    generic_inlineformset_factory,
)
from django.contrib.contenttypes.models import ContentType
from django.contrib.flatpages.models import FlatPage
from django.contrib.flatpages.views import flatpage
from django.contrib.gis.geoip2 import GeoIP2
from django.contrib.sites.models import Site
from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.cache import cache
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.core.files.base import File
from django.core.validators import FileExtensionValidator
from django.db import connection, transaction
from django.db.models import (
    Count,
    Exists,
    F,
    FilteredRelation,
    Func,
    Min,
    OuterRef,
    Prefetch,
    ProtectedError,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.deletion import RestrictedError
from django.db.models.functions import Coalesce, Lower, Trim
from django.forms import (
    DateInput,
    FileField,
    Form,
    HiddenInput,
    IntegerField,
    ModelForm,
    NumberInput,
    Textarea,
    TextInput,
    URLInput,
    ValidationError,
    fields,
    modelform_factory,
    modelformset_factory,
)
from django.forms import models as model_forms
from django.forms import widgets
from django.http import (
    FileResponse,
    Http404,
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
    StreamingHttpResponse,
)
from django.shortcuts import get_object_or_404, redirect, render, reverse
from django.template.loader import get_template
from django.urls import NoReverseMatch
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.decorators import method_decorator
from django.utils.functional import cached_property
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views import View
from django.views.decorators.cache import cache_page
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_http_methods
from django.views.generic import DetailView, FormView, TemplateView
from django.views.generic.base import ContextMixin
from django.views.generic.edit import CreateView, UpdateView
from django_filters.views import FilterView
from django_q.models import OrmQ
from django_select2 import forms as s2forms
from django_summernote.widgets import SummernoteInplaceWidget
from django_tables2 import SingleTableMixin, SingleTableView
from django_tables2.export import ExportMixin
from extra_views import (
    CreateWithInlinesView,
    InlineFormSetFactory,
    ModelFormSetView,
    UpdateWithInlinesView,
)
from geopy.geocoders import Nominatim
from limesurveyrc2api.exceptions import LimeSurveyError
from private_storage.views import PrivateStorageDetailView, PrivateStorageView

# from private_storage.models import PrivateFile
from pypdf import PdfMerger, PdfReader, PdfWriter
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from sentry_sdk import capture_exception, capture_message, last_event_id
from taggit.models import Tag, TaggedItem
from weasyprint import HTML

from common.models import archive_storage

from . import filters, forms, models, tables
from .forms import Submit
from .models import Address, Application, Person, PersonCareerStage, Subscription, User
from .pyinfo import info
from .utils import send_mail, vignere
from .utils.date_utils import FuzzyDate
from .utils.orcid import OrcidHelper

# from .tasks import notify_user


def __(s):
    """Temporarily disable 'gettex'"""
    return s


def natural_item_list(items):
    if not items:
        return _("N/A")
    if not isinstance(items, (list, tuple)):
        items = list(items)
    count = len(items)
    if not count:
        return _("N/A")
    if count == 1:
        return items[0]
    conjunction = gettext_lazy("and ")
    if count == 2:
        return f" {conjunction} ".join(items)
    return f"{', '.join(items[:-1])}, {conjunction} {items[-1]}"


def route_exists(url_name, *args, **kwargs):
    try:
        reverse(url_name, args=args, kwargs=kwargs)
        return True
    except NoReverseMatch:
        return False


def check_selected_orgs(request):
    """Notify the user of updated org names."""
    selected_orgs = request.POST.getlist("selected_org_with_label", [])
    selected_orgs = filter(
        lambda t: t[1] and t[0].isdigit() and t[1].strip(),
        (v.split(":", 1) for v in selected_orgs),
    )
    if selected_orgs:
        selected_orgs = dict((lambda k, v: (int(k), v))(*v) for v in selected_orgs)
        qs = models.Organisation.where(
            ~Q(name__in=selected_orgs.values()), pk__in=selected_orgs.keys()
        )
        for o in qs:
            old_name, new_name = selected_orgs[o.pk], o.name
            messages.warning(
                request,
                _(
                    f"The selected institution name '{old_name}' was replaced and updated with the up-to-date name: '{new_name}'."
                ),
            )


def reset_cache(request):
    cache.delete(f"{request.user.username}:{request.site_id}")


def csrf_failure(request, reason=None):
    if reason:
        messages.error(request, f"Error occurred handing the form: {reason}")
    return redirect("start")


def handler500(request, *args, **kwargs):
    trace = traceback.format_exc()
    e = kwargs.get("e")
    response = render(
        request,
        "500.html",
        {
            "sentry_event_id": last_event_id(),
            "SENTRY_DSN": settings.SENTRY_DSN,
            "error": str(e),
            "trace": trace,
        },
        status=500,
    )
    # response["Cross-Origin-Opener-Policy"] = "unsafe-none"
    # response["Access-Control-Allow-Origin"] = "*"
    return response


def handler413(request, *args, **argv):
    capture_message(
        f"User {request.user} attempted upload a file exceeding the limit.", level="error"
    )
    return render(
        request,
        "413.html",
        {
            "sentry_event_id": last_event_id(),
            "SENTRY_DSN": settings.SENTRY_DSN,
        },
        status=413,
    )


def favicon(request):
    site_id = request.site_id
    if site_id in [2, 3, 4, 5]:
        return redirect(
            staticfiles_storage.url("images/stlp.royalsociety.org.nz/favicon.ico"),
            permanent=True,
        )
    elif site_id == 2:
        return redirect(
            staticfiles_storage.url(
                "images/international.royalsociety.org.nz/favicons/favicon.ico"
            ),
            permanent=True,
        )
    return redirect(staticfiles_storage.url("images/favicons/favicon.ico"), permanent=True)


# @cache_page(600)
def about(request):
    lang = request.LANGUAGE_CODE
    url = f"/{lang or 'en'}/about/"
    site_id = request.site_id
    if FlatPage.objects.filter(url=url, sites=site_id).exists():
        return flatpage(request, url=url)
    if lang != "en":
        url = "/en/about/"
        if FlatPage.objects.filter(url=url, sites=site_id).exists():
            return flatpage(request, url=url)
    url = "/about/"
    if FlatPage.objects.filter(url=url, sites=site_id).exists():
        return flatpage(request, url=url)
    return render(request, "pages/about.html", locals())


@user_passes_test(lambda u: u.is_admin)
def pyinfo(request, message=None):
    """Show Python and runtime environment and settings or test exception handling."""
    if message:
        try:
            raise Exception(message)
        except Exception as e:
            if settings.DEBUG:
                capture_exception(e)
                return handler500(**locals())
            raise
    return render(request, "pyinfo.html", info)


@user_passes_test(lambda u: u.is_admin)
def tags(request, tag_name=None):
    if tag_name:
        tag = get_object_or_404(models.Tag, name__iexact=tag_name)
        # tagged_items = TaggedItem.objects.filter(tag=tag_name)
        tagged_items = tag.taggit_taggeditem_items.all()

    # tags = TaggedItem.objects.annotate(name=F("tag__name")).values("name").annotate(count=Count("pk")).order_by("-count")
    # tags = (
    #     TaggedItem.objects.annotate(name=F("tag__name"), slug=F("tag__slug"))
    #     .values("name", "slug")
    #     .annotate(count=Count("pk"))
    #     .order_by("name")
    # )
    tags = (
        Tag.objects.values("name", "slug")
        .annotate(count=Count("taggit_taggeditem_items"))
        .order_by("name")
    )
    return render(request, "tags.html", locals())


@login_required
def favorites(request):
    # tags = TaggedItem.objects.annotate(name=F("tag__name")).values("name").annotate(count=Count("pk")).order_by("-count")
    # tags = (
    #     TaggedItem.objects.annotate(name=F("tag__name"), slug=F("tag__slug"))
    #     .values("name", "slug")
    #     .annotate(count=Count("pk"))
    #     .order_by("name")
    # )
    favorites = models.Favorite.objects.filter(user=request.user)
    return render(request, "favorites.html", locals())


@login_required
@user_passes_test(lambda u: u.is_superuser)
def impersonate(request, username):
    if (
        username
        and any(c in username for c in ["<", ">"])
        and (m := re.match(r".*\<(.*)\>.*", username))
    ):
        username = m[1]
    u = User.objects.filter(
        Q(username__istartswith=username)
        | Q(email__istartswith=username)
        | Q(emailaddress__email__istartswith=username)
    ).first()
    resp = redirect(request.META.get("HTTP_REFERER") or "start")
    if not u:
        messages.warning(
            request, _(f"A user matching the entered parameter '{username}' does not exist!")
        )
    elif request.user.pk != u.pk:
        resp.set_cookie("previous_user_id", request.user.pk, max_age=36000, secure=True)
        log_rec = models.Impersonation.create(user=request.user, impersonated=u)
        login(request, u, backend="django.contrib.auth.backends.ModelBackend")
        messages.info(request, _(f"The 'impersonation' recoded at {log_rec.impersonated_at}."))
    return resp


@login_required
def switch_back(request):
    resp = redirect(request.META.get("HTTP_REFERER") or "start")
    if pk := request.COOKIES.get("previous_user_id"):
        u = User.get(pk=pk)
        if request.user.pk != u.pk:
            resp.set_cookie("previous_user_id", request.user.pk, max_age=36000, secure=True)
            login(request, u, backend="django.contrib.auth.backends.ModelBackend")
            log_rec = models.Impersonation.create(user=request.user, impersonated=u)
            messages.info(
                request,
                _(
                    f"You switched back to {u}. The 'impersonation' recoded at {log_rec.impersonated_at}."
                ),
            )
        else:
            del request.COOKIES["previous_user_id"]
            resp.delete_cookie("previous_user_id")
    return resp


def shoud_be_onboarded(function):
    """
    Check if the authentication user has a profile.  If it is missing,
    the user gets redirected to 'on-board' to create a profile.

    If the user is on-board, add the profile to the request object.
    """

    @wraps(function)
    def wrap(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated or user.is_anonymous:
            return redirect(
                reverse(settings.LOGIN_URL) + "?next=" + quote(request.get_full_path())
            )

        person = Person.where(user=user).last()
        if not person or request.session.get("wizard") or ("wizard-views" in request.session):
            wizard_views = request.session.get("wizard-views")
            view_name = person and "profile-update" or "profile-create"
            if person and wizard_views is not None:
                view_name = wizard_views[0]
            messages.info(
                request,
                _(
                    "Your profile is not completed yet. "
                    "Please complete your profile or skip it."
                ),
            )
            return redirect(reverse(view_name) + "?next=" + quote(request.get_full_path()))
        else:
            if request.site_id == 2 and not request.session.get("country"):
                cc = None
                if not (person.address and (cc := person.address.country_id)):
                    try:
                        g = GeoIP2()
                        x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
                        if x_forwarded_for:
                            ip = x_forwarded_for.split(",")[0]
                        else:
                            ip = request.META.get("REMOTE_ADDR")
                        cc = g.country_code(ip)
                    except:
                        pass
                    if (
                        not cc
                        and (lat := request.COOKIES.get("latitude"))
                        and (long := request.COOKIES.get("longitude"))
                    ):
                        try:
                            geolocator = Nominatim(
                                user_agent=f"{apps.get_app_config('portal').verbose_name or 'RSNZ Portal'}"
                            )
                            location = geolocator.reverse(f"{lat}, {long}")
                            cc = location.raw["address"]["country_code"].upper()
                        except:
                            pass
                if cc:
                    request.session["country"] = cc
                    request.session.modified = True

        request.person = person
        return function(request, *args, **kwargs)

    return wrap


@login_required
def logout(request):
    account_logout = reverse("account_logout")
    if "previous_user_id" in request.COOKIES:
        del request.COOKIES["previous_user_id"]
        resp.delete_cookie("previous_user_id")

    if request.user.has_rapidconnect_account:
        return_url = request.build_absolute_uri(account_logout)
        if (
            sa := SocialApp.objects.filter(
                sites__id=request.site_id, provider="rapidconnect"
            ).first()
        ) and (id_value := sa.client_id.split("/")[-1]):
            resp = redirect(f"{settings.RAPIDCONNECT_LOGOUT}?id={id_value}&return={return_url}")
        else:
            resp = redirect(f"{settings.RAPIDCONNECT_LOGOUT}?return={return_url}")
        # Add delete session before rediction - force 'logout' - an ugly workaround:
        resp.delete_cookie("sessionid")
        return resp

    return redirect(account_logout)


def should_be_approved(function):
    """
    Check if the authentication user is approved.  If not then display a
    message to wait for approval.
    """

    @wraps(function)
    def wrap(request, *args, **kwargs):
        user = request.user
        if not user.is_approved:
            messages.error(
                request,
                _(
                    "Your portal access has not been authorised, please allow up to two "
                    "working days for admin us to look into your request."
                ),
            )
            return redirect("index")
        return function(request, *args, **kwargs)

    return wrap


class ArchivalPrivateStorageView(PrivateStorageView):
    """A view to serve files from the archival storage."""

    storage = archive_storage

    def get(self, request, *args, **kwargs):
        """
        Handle incoming GET requests
        """
        private_file = self.get_private_file()

        if not self.can_access_file(private_file):
            raise PermissionDenied(self.permission_denied_message)

        storage = self.storage
        if storage.exists_locally(private_file.relative_name):
            return self.serve_file(private_file)

        if storage.exists_in_archive(private_file.relative_name):
            storage.retrieve_from_archive(private_file.relative_name)
            return self.serve_file(private_file)

        return self.serve_file_not_found(private_file)


class AdminRequiredMixin(AccessMixin):
    """Verify that the current user is admin or staff."""

    def dispatch(self, request, *args, **kwargs):
        if (
            not (u := request.user)
            or not u.is_authenticated
            or not (u.is_superuser or u.is_site_staff)
        ):
            messages.error(request, _("Only the administrator can access this page"))
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)


class StateInPathMixin:
    @cached_property
    def state(self):
        state = (
            self.request.GET.get("state_filter")
            or self.request.GET.get("state")
            or self.request.path.split("/")[-1]
            or self.request.path.split("/")[-2]
        )
        if state and state in (
            [s for s, _ in self.model.state.field.choices]
            if hasattr(self.model, "state")
            else ["new", "draft", "submitted", "archived", "WIP", "in_review"]
        ):
            return state

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if state := self.state:
            context["state"] = state
            context["object_state"] = state
            context["model_name"] = self.model._meta.model_name
        return context

    def get_queryset(self, *args, **kwargs):
        queryset = super().get_queryset(*args, **kwargs)
        if state := self.state:
            if hasattr(self.model, "user_objects"):
                return self.model.user_objects(
                    user=self.request.user,
                    state=state,
                    round=self.request.GET.get("round"),
                    request=self.request,
                    queryset=queryset,
                )
            elif self.model is models.Contract:
                if state == "draft":
                    queryset = queryset.filter(state__in=["draft", "new"])
                else:
                    queryset = queryset.filter(state=state)
            elif self.model is models.Testimonial:
                if state == "draft":
                    queryset = queryset.filter(evaluations__state__in=["draft", "new"])
                else:
                    queryset = queryset.filter(evaluations__state=state)
            elif self.model is models.Nomination:
                if state == "draft":
                    queryset = queryset.filter(state__in=["draft", "new"])
                else:
                    queryset = queryset.filter(state=state)
            elif self.model is models.Round:
                if state == "draft":
                    queryset = queryset.filter(
                        Q(panellists__evaluations__state__in=["new", "draft"])
                        | Q(panellists__evaluations__state__isnull=True)
                    )
                else:
                    queryset = queryset.filter(
                        Q(panellists__evaluations__state=state)
                        | Q(panellists__evaluations__state__isnull=True)
                    )
            else:
                if state == "draft":
                    queryset = queryset.filter(state__in=["draft", "new"])
                elif state in ["accepted", "funded", "in_review"]:
                    queryset = queryset.filter(state=state)
                elif state == "new":
                    queryset = queryset.filter(state=state)
                else:
                    # queryset = queryset.filter(state=state)
                    u = self.request.user
                    if (site_id := self.request.site_id) in [2, 4, 5] and (
                        u.is_superuser or u.staff_of_sites.filter(id=site_id)
                    ):
                        if state == "submitted":
                            queryset = queryset.filter(state__in=["submitted", "cancelled"])
                        else:  # approved
                            queryset = queryset.filter(state="approved")
                    else:
                        queryset = queryset.filter(
                            state__in=["submitted", "approved", "cancelled"]
                        )
        return queryset


class FavoriteMixin:

    def put(self, request, *args, **kwargs):
        obj = self.get_object()
        content_type = ContentType.objects.get_for_model(self.model)
        favorite, is_favorited = models.Favorite.objects.get_or_create(
            user=request.user,
            content_type=content_type,
            object_id=obj.pk,
        )
        if not is_favorited:
            favorite.delete()
        object_id = obj.pk
        with_class_name = request.GET.get("with_class_name", False)
        # context = {
        #     "is_favorited": is_favorited,
        #     "object_id": obj.pk,
        #     # "content_type_id": content_type_id,
        #     # You might also want to pass the count of favorites
        # }
        # return render(request, "snippets/favorite_button.html", locals())
        # return HttpResponse(
        #     render_to_string("snippets/favorite_button.html", context, request=request)
        # )

        if request.GET.get("with_class_name", False):
            return HttpResponse(f"""
              <i id="favorite-status-{ obj.calss_name }-{ object_id }"
              class="{ 'fa' if is_favorited else 'far' } fa-star" aria-hidden="true">
              </i>
            """)
        return HttpResponse(f"""
          <i id="favorite-status-{ object_id }"
          class="{ 'fa' if is_favorited else 'far' } fa-star" aria-hidden="true">
          </i>
        """)


class NotesMixin:

    def get_notes_formset(self):

        u = self.request.user
        fsc = generic_inlineformset_factory(
            models.Note,
            fields=("content",),
            extra=1,
            can_order=False,
            can_delete=True,
            can_delete_extra=True,
        )
        if self.object and self.object.id:
            fs = fsc(
                self.request.POST or None,
                instance=self.object,
                queryset=models.Note.objects.filter(
                    content_type=ContentType.objects.get_for_model(self.model),
                    object_id=self.object.id,
                ),
                prefix="notes",
            )
            for f in fs.forms:
                i = f.instance
                content_field = f.fields["content"]
                if f.instance and f.instance.pk:
                    content_field.widget.attrs["rows"] = max(
                        (i.content and f.instance.content.count("\n") + 1) or 3, 3
                    )
                    if i.author:
                        if i.author != u:
                            content_field.widget.attrs["readonly"] = True
                        if i.created_at:
                            content_field.help_text = _("Added on %s by %s") % (
                                i.created_at.strftime("%Y-%m-%d %H:%M"),
                                i.author,
                            )
                        else:
                            content_field.help_text = _("Added by %s") % i.author
                else:
                    content_field.widget.attrs["rows"] = 3

        else:
            fs = fsc(
                self.request.POST or None, queryset=models.Note.objects.none(), prefix="notes"
            )
        return fs
        # class NoteInline(GenericTabularInline):

    def get_context_data(self, **kwargs):
        if not (context := getattr(self, "context", None)):
            context = super().get_context_data(**kwargs)
            self.context = context
        u = self.request.user
        if u.is_admin:
            context["is_admin"] = True
            context["notes"] = self.get_notes_formset()
        return context

    def form_valid(self, form):
        resp = super().form_valid(form)
        if not (context := getattr(self, "context", None)):
            context = self.get_context_data()
        u = self.request.user
        if u.is_admin and (notes := context.get("notes")):
            if not notes.instance or not notes.instance.pk:
                notes.instance = a

            for f in notes.forms:
                if f.instance and not f.instance.pk and not f.instance.author:
                    f.instance.author = u
            if notes.is_valid():
                notes.save()
        return resp


class AccountView(LoginRequiredMixin, TemplateView):
    template_name = "account.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        u = self.request.user
        context["user"] = u
        context["emails"] = list(
            EmailAddress.objects.filter(~Q(email__lower=u.email.lower()), user=u)
        )
        context["accounts"] = list(SocialAccount.objects.filter(user=u))
        return context


@method_decorator(shoud_be_onboarded, name="dispatch")
class CreateUpdateView(LoginRequiredMixin, UpdateView):
    """A trick to make create and update view in a single view."""

    template_name = "form.html"

    def get_object(self, queryset=None):
        try:
            return super().get_object(queryset)
        except AttributeError:
            return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["model_name"] = self.model._meta.model_name
        if self.object and hasattr(self.object, "state") and self.object.state:
            context["object_state"] = self.object.state

        return context

    def get_form_kwargs(self):
        """Return the keyword arguments for instantiating the form."""
        kwargs = super().get_form_kwargs()
        kwargs["site_id"] = self.request.site_id or 0
        return kwargs

    def get_success_url(self):
        try:
            return super().get_success_url()
        except:
            return (
                self.request.GET.get("next")
                or self.request.META.get("HTTP_REFERER")
                or reverse("start")
            )


class SingleObjectMixin(ContextMixin):

    slug_field = "number"
    slug_url_kwarg = "number"
    pk_url_kwarg = "pk"

    _obj = None

    def get_object_filter(self, value):
        if isinstance(value, int) or value.isnumeric():
            return {"pk": int(value)}
        return {self.get_slug_field(): value}

    def get_object(self, queryset=None):
        if not self.request.user.is_authenticated:
            return None

        if self._obj:
            return self._obj

        if queryset is None:
            queryset = self.get_queryset()

        obj_id = self.kwargs.get(self.pk_url_kwarg) or self.kwargs.get(self.slug_url_kwarg)
        if obj_id is not None:
            queryset = queryset.filter(Q(**self.get_object_filter(obj_id)))

        try:
            # Get the single item from the filtered queryset
            obj = queryset.first()
            if not obj:
                slug_field = self.get_slug_field()
                an = get_object_or_404(models.ApplicationNumber, **{slug_field: obj_id})
                obj = an.application
        except queryset.model.DoesNotExist:
            raise Http404(
                _("No %(verbose_name)s found matching the query")
                % {"verbose_name": queryset.model._meta.verbose_name}
            )
        if not obj:
            raise Http404(
                _("No %(verbose_name)s found matching the query")
                % {"verbose_name": queryset.model._meta.verbose_name}
            )
        self._obj = obj
        return self._obj


class DetailView(LoginRequiredMixin, SingleObjectMixin, DetailView):
    template_name = "detail.html"
    cache_timeout = int(getattr(settings, "CACHE_TIMEOUT", 60))

    def get_cache_timeout(self):
        return self.cache_timeout

    @property
    def key_prefix(self):
        u = self.request.user
        return f"{u.is_admin or u.pk}"

    # TODO:  make more managable
    # def dispatch(self, request, *args, **kwargs):
    #     if request.method == "GET" and request.user.is_authenticated:
    #         return cache_page(self.get_cache_timeout(), key_prefix=self.key_prefix)(
    #             super().dispatch
    #         )(request, *args, **kwargs)
    #     resp = super().dispatch(request, *args, **kwargs)
    #     return resp

    def get_transitions(self):
        model_name = self.object._meta.model_name

        def button_name(transition):
            if hasattr(transition, "custom") and (
                name := transition.custom.get("button_name") or transition.custom.get("verbose")
            ):
                return name
            else:
                # Make the function name the button title, but prettier
                return "{0} {1}".format(transition.name.replace("_", " "), model_name).title()

        def button_tooltip(obj, transition):
            if hasattr(transition, "custom") and (
                name := transition.custom.get("verbose") or transition.custom.get("button_name")
            ):
                return f"{name} {obj}"
            else:
                # Make the function name the button title, but prettier
                return "{0} {2}".format(transition.name.replace("_", " "), model_name, obj).title()

        if not getattr(self, "object", None):
            self.object = self.get_object()
        return [
            (t.name, button_name(t), button_tooltip(self.object, t))
            for t in self.object.get_available_user_state_transitions(self.request.user)
            if t.name not in ["save_draft"] and t.custom.get("internal") is not True
        ]

    def tag_form(self, *args, **kwargs):

        form = modelform_factory(
            self.model,
            fields=["tags"],
            labels={"tags": ""},
            help_texts={"tags": ""},
            widgets={
                "tags": autocomplete.TagSelect2(
                    url="tag-autocomplete",
                    attrs={
                        "data-placeholder": _(
                            "Please enter a tag or multiple tags. You can select multiple tags..."
                        ),
                    },
                )
            },
        )(self.request.POST or None, instance=self.object)
        helper = FormHelper(form)
        helper.help_text_inline = False
        helper.html5_required = False
        helper.form_show_labels = False
        helper.use_custom_control = False
        helper.include_media = False
        helper.layout = Layout(
            Row(
                Column("tags", css_class="col-11"),
                Column(
                    Submit(
                        "save_tags",
                        _("Save Tags"),
                        css_class="btn-primary",
                        data_tooltip="tooltip",
                        title=_("Save tags"),
                    ),
                    css_class="col-1",
                ),
                css_class="row",
            )
        )
        form.helper = helper
        return form

    def get_comment_form(self):

        CommentForm = modelform_factory(
            self.model.comments.rel.model,
            form=forms.CommentForm,
            fields=(
                ["host_contact_email", "comment", "attachment"]
                if hasattr(self.model, "host_contact_email")
                else ["comment", "attachment"]
            ),
            exclude=["report", "token", "contract", "change_request", "object"],
        )
        return CommentForm(
            self.request.POST or None,
            self.request.FILES or None,
            instance=self.object,
            prefix="comment",
            initial={
                "host_contact_email": getattr(self.object, "host_contact_email", None)
                or getattr(self.object, "host_contact", "")
            },
        )

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context["exclude"] = ["id", "created_at", "updated_at", "org", "site", "comments"]
        model_name_slug = self.object._meta.db_table.replace("_", "-").lower()
        context["update_view_name"] = f"{model_name_slug}-update"
        context["category"] = self.object._meta.verbose_name_plural
        if hasattr(self.object, "state"):
            context["object_state"] = self.object.state
            context["model_name"] = self.object._meta.model_name
        context["update_button_name"] = _("Edit")
        if self.model and self.model in (models.Application, models.Contract, models.Testimonial):
            context["export_button_view_name"] = f"{model_name_slug}-export"
        u = self.request.user
        if u.is_admin:
            context["can_edit"] = True
            if hasattr(self.model, "tags"):
                context["tag_form"] = self.tag_form()

        if hasattr(self.model, "comments"):
            context["has_comments"] = True
            context["comments"] = self.object.comments.all()
            context["attachments"] = self.object.attached_files
            context["comment_form"] = self.get_comment_form()
            context["tabbed_ui"] = True

        if hasattr(self.model, "state") and self.object.state != "archived":
            context["transitions"] = self.get_transitions()

        return context

    def post_comment(self, request, *args, **kwargs):

        form = self.get_comment_form()
        if not form.is_valid():
            return self.get(request, *args, **kwargs)

        token = models.get_unique_mail_token()
        attachment = form.cleaned_data.get("attachment", None)
        if body := form.cleaned_data.get("comment", None):
            body = body.strip()

        i = self.object
        if self.model is models.Contract:
            c = i
        elif self.model is models.Report or self.model is models.ChangeRequest:
            c = i.contract
        u = request.user
        is_ro = u.is_ro
        recipients = i.host_recipients if is_ro else i.agency_recipients

        if body or attachment:
            comment = i.comments.model(
                submitted_by=u,
                comment=body,
                attachment=attachment,
                token=token,
            )
            if (
                "host_contact_email" in form.changed_data
                and hasattr(i, "host_contact_email")
                and (host_contact_email := form.cleaned_data.get("host_contact_email", None))
                and i.host_contact_email != host_contact_email
            ):
                i.host_contact_email = host_contact_email
                i.save()

            i.comments.add(
                comment,
                bulk=False,
            )

            respond_url = self.request.build_absolute_uri(i.get_absolute_url()) + "#correspondence"
            html_message = f'<p>Comment posted by {u.full_name_with_email} to <data value="{i.number}">{i}</data>'
            html_message += f":</p>{body}" if body else "."
            html_message += f'<hr/>To respond to this message, please, click here: <a href="{respond_url}">REPLY</a>'
            send_mail(
                request=self.request,
                from_email=(
                    "variations" if self.model is models.ChangeRequest else f"{i.model_name}s"
                ),
                subject=f"Comment posted by {u.full_name_with_email} to {i}",
                html_message=html_message,
                cc=[u.full_email_address],
                attachments=attachment and [attachment],
                recipients=recipients,
                thread_index=i.thread_index,
                thread_topic=i.thread_topic,
                token=token,
            )

            comment.recipients.model.objects.bulk_create(
                [
                    (
                        comment.recipients.model(comment=comment, user=r, email=r.email)
                        if isinstance(r, models.User)
                        else comment.recipients.model(
                            comment=comment,
                            email=r,
                            user=User.where(
                                Q(email__iexact=r) | Q(emailaddress__email__iexact=r)
                            ).first(),
                        )
                    )
                    for r in recipients
                ]
            )
            return redirect(request.path.split("#")[0] + "#correspondence")

    def post(self, request, *args, **kwargs):

        if not getattr(self, "object", None):
            self.object = self.get_object()

        if hasattr(self.model, "tags"):
            form = self.tag_form()
            if "save_tags" in form.data and form.is_valid():
                form.save()

        if "post_comment" in request.POST and hasattr(self.model, "comments"):
            return self.post_comment(request, *args, **kwargs)

        return_url = request.POST.get("return_url")
        old_state = state = getattr(self.object, "state", None)
        action, description = request.POST.get("action"), request.POST.get("resolution", None)

        if action:
            if method := getattr(self.object, action, None):
                if not description and action == "withdraw":
                    description = (
                        f"{request.user} withdrew the {self.object.model_name} {self.object}."
                    )
                old_state = self.object.state
                method(request=request, description=description, by=request.user)
                # self.object.save(update_fields=["state", "state_changed_at", "updated_at"])
                state = self.object.state
                if state != old_state:
                    self.object.save()
                if self.model is models.Nomination and action == "withdraw":
                    messages.info(request, _(f"The nomination {n} has been withdrawn."))
                else:
                    messages.success(
                        request,
                        _(f"The {self.object._meta.verbose_name} {self.object} was {state}."),
                    )
                if self.model is models.Nomination and (a := self.object.application) and a.is_wip:
                    old_state = a.object.state
                    a.cancel(
                        request=request,
                        by=request.user,
                        description=description,
                    )
                    state = a.object.state
                    if state != old_state:
                        a.save()
                    messages.info(request, _(f"The application {a} has been cancelled."))

            elif self.model is models.Testimonial and action == "turn_down":
                t = self.object
                t.referee.opt_out(user=request.user, request=request)
                t.referee.save()

            if state != old_state:
                reset_cache(request)

            if return_url:
                return redirect(return_url)

            if state:
                if state == "archived":
                    route = f"{self.object.model_name}s-{old_state}"
                else:
                    if state == "new":
                        state = "draft"
                    route = f"{self.object.model_name}s-{state}"
                if route_exists(route):
                    return redirect(route)

            route = f"{self.object.model_name}s"
            if route_exists(route):
                return redirect(route)

        return redirect(request.path)


@method_decorator(shoud_be_onboarded, name="dispatch")
class ExportView(UserPassesTestMixin, DetailView):
    model = None
    cache_timeout = 0
    template = "pdf_export_template.html"

    def test_func(self):
        u = self.request.user
        return (
            u.is_admin
            or (o := self.get_object_or_404())
            and (
                hasattr(o, "is_pi") and o.is_pi(user=u) or hasattr(o, "is_ro") and o.is_ro(user=u)
            )
        )

    def get_metadata(self, pk):
        return {"/Title": f"{self.model.get(pk)}"}

    def get_object_or_404(self, pk=None):
        if not pk:
            pk = self.kwargs.get("pk")
        return get_object_or_404(self.model, pk=pk)

    def get_objects(self, pk):
        return [self.get_object_or_404(pk)]

    def get_attachments(self, pk):
        o = self.object
        return [o.pdf_file.path] if getattr(o, "file", None) else []

    def get_filename(self, pk=None):
        return getattr(self.object, "number", "export")

    def get(self, request, pk, filename=None):
        o = self.object = self.get_object()
        if not filename:
            return redirect(o.export_url)
        try:
            objects = self.get_objects(pk)
            self.object = self.get_object()
            template = get_template(self.template)
            if hasattr(self, "summary_template"):
                summary_template = self.summary_template
            attachments = self.get_attachments(pk)
            # merger = PdfMerger()
            merger = PdfWriter()
            merger.add_metadata(self.get_metadata(pk))

            if hasattr(o, "to_pdf"):
                pdf_content = io.BytesIO()
                merger = o.to_pdf(
                    request=request,
                    user=request.user,
                )
                merger.write(pdf_content)
                # pdf_response = HttpResponse(pdf_content.getvalue(), content_type="application/pdf")
            else:
                template = get_template(self.template)
                attachments = self.get_attachments(pk)
                # merger = PdfMerger()
                merger = PdfWriter()
                merger.add_metadata(self.get_metadata(pk))

                site_id = getattr(self.object, "site_id", None) or settings.SITE_ID
                logo = logo_1 = logo_2 = None
                if site_id == 2:
                    if logo_path := finders.find(f"images/{domain}/alt_logo_small.png"):
                        logo = f"file://{logo_path}"

                elif site_id in [2, 4, 5]:
                    if logo_path := finders.find("images/MBIE_logo.jpg"):
                        logo_1 = f"file://{logo_path}"

                    if logo_path := finders.find("images/RS_logo.png"):
                        logo_2 = f"file://{logo_path}"

                elif site_id == 7:
                    if logo_path := finders.find("images/pmspace-logo_small.jpg"):
                        logo = f"file://{logo_path}"

                html = HTML(string=template.render(locals()))
                pdf_object = html.write_pdf(presentational_hints=True)
                # converting pdf bytes to stream which is required for pdf merger.
                pdf_stream = io.BytesIO(pdf_object)
                merger.append(pdf_stream)
                for a in attachments:
                    if isinstance(a, (tuple, list)):
                        merger.append(a[1], outline_item=a[0], import_outline=True)
                    else:
                        merger.append(a, import_outline=True)
                pdf_content = io.BytesIO()
                merger.write(pdf_content)

            pdf_content.seek(0)
            pdf_response = FileResponse(pdf_content, content_type="application/pdf")
            pdf_response["Content-Disposition"] = f'inline; filename="{self.get_filename()}.pdf"'
            # NB! Need to disable caching to force usage of the name
            pdf_response["Cache-Control"] = (
                "no-cache, must-revalidate, max-age=0, post-check=0, pre-check=0"
            )
            return pdf_response
        except Exception as ex:
            capture_exception(ex)
            messages.warning(
                self.request,
                _(f"Error while converting to pdf. Please contact Administrator: {ex}"),
            )
            return redirect(self.request.META.get("HTTP_REFERER"))


class CreateView(LoginRequiredMixin, CreateView):
    def get_success_url(self):
        try:
            return super().get_success_url()
        except:
            return (
                self.request.GET.get("next")
                or self.request.META.get("HTTP_REFERER")
                or reverse("home")
            )


# class ObjectView(
#     LoginRequiredMixin, SingleObjectTemplateResponseMixin, ModelFormMixin, ProcessFormView
# ):
#     """ViewSet implementation..."""

#     def init_object(self, request, *args, **kwargs):
#         if kwargs and (kwargs.get(self.pk_url_kwarg) or kwargs.get(self.slug_url_kwarg)):
#             self.object = self.get_object()
#         else:
#             self.object = None
#         return self.object

#     def get(self, request, *args, **kwargs):
#         self.init_object(request, *args, **kwargs)
#         return super().get(request, *args, **kwargs)

#     def post(self, request, *args, **kwargs):
#         self.init_object(request, *args, **kwargs)
#         return super().post(request, *args, **kwargs)


class SubscriptionList(LoginRequiredMixin, SingleTableView):
    model = Subscription
    table_class = tables.SubscriptionTable
    template_name = "table.html"


class SubscriptionDetail(DetailView):
    model = Subscription


@api_view(["GET", "PUT", "POST"])
@authentication_classes([TokenAuthentication])
@permission_classes([IsAuthenticated])
def survey_webhook(request):
    data = json.loads(request.body)
    # https://puanga.prodata.nz/limesurvey/printanswers/view?surveyid=655512
    # https://puanga.prodata.nz/limesurvey/statistics_user/655512?language=en
    # capture_message(f"incoming request form lime survey:\n{request.body}\n\n\n{data}")
    if (token := data.get("token")) and (r := models.Referee.where(survey_token=token).first()):
        if not r.survey_completed_at and (response := data.get("response")):
            if (completed_at := response.get("submitdate")) and not (
                r.survey_completed_at and r.staus == "testified"
            ):
                with transaction.atomic():
                    completed_at = (
                        timezone.now()
                        if (not completed_at or completed_at.startswith("1980-01-01"))
                        else timezone.make_aware(parse(completed_at))
                    )
                    description = f"Referee report was completed at {completed_at}"
                    r.survey_completed_at = completed_at
                    by = (
                        r.user
                        or User.where(
                            Q(email__lower=r.email.lower())
                            | Q(emailaddress__email__lower=r.email.lower())
                        ).first()
                    )
                    for t in models.Testimonial.where(referee=r):
                        if t.state != "submitted":
                            t.submit(by=by, description=description)
                            t._change_reason = description
                            t.save()
                            break
                    else:
                        if models.Referee.get(r.pk).state != "testified":
                            r.testify(by=by, description=description)
                            r._change_reason = description
                            r.save()

    return JsonResponse(
        {
            "status": "OK",
        },
        status=200,
    )


@login_required
def object_counts(request):
    cache_key = f"{request.user.username}:{settings.SITE_ID}"
    cached_context = cache.get(cache_key, {})
    return JsonResponse(cached_context)


@login_required
def complete_survey(request):
    """Handle completion of the survey"""
    # capture_message(f"COMPLETED:\n{request.GET}\n\n\n{request}")
    token = request.GET.get("token")
    survey_id = request.GET.get("survey_id") or request.GET.get("survey-id")
    q = models.Referee.where(
        survey_completed_at__isnull=True,
        application__round__scheme__current_round=F("application__round"),
    )
    if survey_id:
        q = q.filter(application__round__survey_id=survey_id)
    if token:
        q = q.filter(survey_token=token)
    else:
        q = q.filter(Q(user=request.user) | Q(email__lower=request.user.email.lower()))
    for r in q:
        if not survey_id:
            survey_id = r.application.round.survey_id
        if r.survey_token_id and survey_id:
            api = r.survey_api
            # resp = api.token.invite_participants(survey_id, [self.survey_token_id,])
            properties = api.token.get_participant_properties(survey_id, r.survey_token_id)
            if (
                (completed_at := properties.get("completed"))
                and completed_at != "N"
                and not completed_at.startswith("1980-01-01")
            ):
                with transaction.atomic():
                    description = f"Referee report was completed at {completed_at}"
                    r.survey_completed_at = (
                        timezone.make_aware(parse(completed_at)) or timezone.now()
                    )
                    # r.testify(by=r.user, description=description)
                    # r._change_reason = description
                    for t in models.Testimonial.where(
                        ~Q(state="submitted"),
                        referee__application__round__testimonials_required=False,
                        referee=r,
                    ):
                        t.submit(by=r.user, description=description)
                        t._change_reason = description
                        t.save()
                    else:
                        if (
                            r.state != "testified"
                            and not r.application.round.testimonials_required
                        ):
                            r.testify(request=request)
                        r.save()

    q = (
        models.Referee.where(survey_token=token)
        if token
        else models.Referee.where(
            Q(user=request.user) | Q(email__lower=request.user.email.lower()),
            survey_completed_at__isnull=False,
            application__round__scheme__current_round=F("application__round"),
        )
    ).order_by("-id")
    r = q.first()
    if r:
        messages.info(request, _("Thank you! Your survey responses have been recorded."))
        return redirect("application", pk=r.application_id)
    return redirect("index")


@require_http_methods(["POST"])
def subscribe(request):
    email = request.POST["email"]
    if email:
        email = email.lower()
    instance = Subscription.where(email__lower=email).order_by("-id").first()

    form = forms.SubscriptionForm(request.POST, instance=instance)
    if form.is_valid():
        form.save()
        messages.info(request, _("Confirmation e-mail sent to %s.") % email)
        token = models.get_unique_mail_token()
        url = reverse("subscription-confirmation", kwargs=dict(token=token))
        url = request.build_absolute_uri(url)
        # return_url = request.GET.get("next") or request.META.get("HTTP_REFERER")
        # url = f"{url}?next={return_url}"
        send_mail(
            __("Please confirm subscription"),
            __("Please confirm your subscription to our newsletter: %s") % url,
            recipients=[email],
            fail_silently=False,
            token=token,
            request=request,
        )

    return render(request, "account/verification_sent.html", locals())


@require_http_methods(["GET", "POST"])
def confirm_subscription(request, token):
    log_entry = get_object_or_404(models.MailLog, token=token)
    subscription = get_object_or_404(models.Subscription, email__lower=log_entry.recipient)
    if request.method == "POST":
        is_confirmed = bool(request.POST.get("subscribe"))
        subscription.is_confirmed = is_confirmed
        subscription.save()
        messages.info(
            request,
            (
                _("Thank you for subscribing to our newsletter.")
                if is_confirmed
                else _("We will miss you")
            ),
        )
        return redirect("index")
    messages.info(request, _("Thank you for subscribing to our newsletter."))
    return render(request, "confirmation.html", locals())


def unsubscribe(request, token):
    get_object_or_404(models.MailLog, token=token)
    messages.success(request, _("We will miss you"))
    return redirect("index")


@login_required
def round_detail(request, round):
    modal = request.GET.get("modal")
    user = request.user
    round = get_object_or_404(models.Round, id=round)
    applications = Application.where(round=round).values("state").annotate(total=Count("state"))
    total_applications = sum(a["total"] for a in applications)

    nominations = (
        models.Nomination.where(round=round).values("state").annotate(total=Count("state"))
    )
    total_nominations = sum(n["total"] for n in nominations)

    return render(
        request, "partials/round_detail.html" if modal else "round_detail.html", locals()
    )


def round_required_documents(request, round):

    round = get_object_or_404(models.Round, id=round)
    required_documents = round.required_documents.order_by("ordering")
    templates = {
        k: list(g)
        for k, g in groupby(
            round.templates.all().order_by("document_type"), lambda r: r.document_type
        )
    }

    return render(request, "round_required_documents.html", locals())


def get_survey_api_url():
    if "LIMESURVEY_API_URL" in dir(settings):
        return settings.LIMESURVEY_API_URL
    elif server_url := settings.LIMESURVEY_SERVER_URL:
        return f"{server_url}/admin/remotecontrol"
    else:
        site = Site.objects.get_current()
        return f"https://{site.domain}/limesurvey/admin/remotecontrol"


def do_survey(request, survey_id=None, token=None, referee_id=None):
    lime_cookies = [k for k in request.COOKIES if k.startswith("LS-") or k == "YII_CSRF_TOKEN"]
    if lime_cookies:
        # resp = HttpResponseRedirect(request.get_full_path())
        resp = render(
            request,
            "delete_cookies_and_redirect.html",
            {
                "cookies": lime_cookies,
                "url": request.get_full_path(),
            },
        )
        host, *rest = request.get_host().split(":")
        for k in lime_cookies:
            resp.delete_cookie(k, path="/", domain=host)
        # return resp
    u = request.user
    if not u.is_authenticated:
        i = None
        if token := request.GET.get("token"):
            if i := models.Invitation.where(token=token).first():
                if i.state == "revoked":
                    messages.warning(
                        request,
                        _("The invitation has been revoked and is not any more valid."),
                    )
                else:
                    request.session["invitation_token"] = token
        elif referee_id:
            i = get_object_or_404(models.Referee, pk=referee_id).invitation

        user_exists = (
            i
            and User.objects.filter(
                Q(email__lower=i.email.lower()) | Q(emailaddress__email__lower=i.email.lower())
            ).exists()
        )
        if request.user and not request.user.is_authenticated:
            return redirect(
                reverse("account_login" if user_exists else "account_signup")
                + f"?next={quote(request.get_full_path())}"
            )

    if not is_profile_completed(request):
        return redirect(reverse("check-profile") + f"?next={quote(request.get_full_path())}")

    reset_cache(request)
    if referee_id:
        if (
            r := models.Referee.objects.prefetch_related("application", "application__round")
            .filter(pk=referee_id)
            .first()
        ):
            if not (
                u.is_superuser
                or u.is_site_staff
                or u.emailaddress_set.filter(email__lower=r.email.lower()).exists()
            ):
                messages.error(
                    request,
                    _(
                        "The invitation to participate in the survey was not sent to your address. "
                        "Please, make sure you have logged in with a correct account the invitation was sent to."
                    ),
                )
                return redirect("index")

            survey_id = r.application.round.survey_id
        else:
            messages.warning(
                request,
                _("You have been removed from the list of the application referees."),
            )
            return redirect("index")

    if not r.survey_completed_at:
        api = r.survey_api
        was_synced = False
        for _attempt in range(2):  # 2 attempts
            if was_synced:
                break
            if not r.survey_token_id:
                r.add_to_survey(api)
                r.save()

            for arg_list in [
                (r.survey_token_id,),
                (None, {"token": r.survey_token}),
                (None, {"email": r.email}),
            ]:
                try:
                    properties = api.token.get_participant_properties(survey_id, *arg_list)
                    if (
                        properties.get("token") != r.survey_token
                        or properties.get("tid") != r.survey_token_id
                    ):
                        r.survey_token = properties.get("token")
                        r.survey_token_id = properties.get("tid")
                        r.save(update_fields=["survey_token", "survey_token_id"])
                    was_synced = True
                    break
                except LimeSurveyError:
                    pass
            else:
                r.survey_token = None
                r.survey_token_id = None

        if (completed_at := properties.get("completed")) and completed_at != "N":
            with transaction.atomic():
                description = f"Referee report was completed at {completed_at}"
                r.survey_completed_at = timezone.make_aware(parse(completed_at)) or timezone.now()
                # r.testify(by=r.user, description=description)
                # r._change_reason = description
                for t in models.Testimonial.where(~Q(state="submitted"), referee=r):
                    t.submit(by=r.user, description=description)
                    t._change_reason = description
                    t.save()
                else:
                    if r.state != "testified":
                        r.testify(request=request)
                    r.save()

    if r.survey_completed_at:
        if r.state != "submitted":
            r.testify(
                request=request,
                by=u,
                description=f"Synced date with LimeSurve; survey completed at {r.survey_completed_at}",
            )
            r.save()

        messages.warning(
            request,
            _(f"The referee report has been already completed at <b>{r.survey_completed_at}</b>"),
        )
        url = r.survey_url
        if url:
            messages.info(
                request,
                _(
                    f'If you wish to update your response, click here <a href="{url}" class="btn btn-info btn-sm">Update Response</a>'
                ),
            )

        t = models.Testimonial.where(referee=r).order_by("-pk").first()
        if t:
            return redirect("testimonial", pk=t.pk)
        elif r.application_id:
            return redirect("application", pk=r.application_id)
        return redirect(request.META.get("HTTP_REFERER", "index"))

    resp = HttpResponseRedirect(r.survey_url)
    lime_cookies = [k for k in request.COOKIES if k.startswith("LS-") or k == "YII_CSRF_TOKEN"]
    if lime_cookies:
        host, *rest = request.get_host().split(":")
        for k in lime_cookies:
            resp.delete_cookie(k, path="/", domain=host)
    return resp


@login_required
@shoud_be_onboarded
@csrf_protect
def index(request):

    site_id = request.site_id
    if request.resolver_match.view_name in ["start", "home"]:
        reset_cache(request)
    if "error" in request.GET:
        raise Exception(request.GET["error"])
    user = request.user
    is_ro = user.is_ro
    is_admin = user.is_admin
    if site_id in [2, 4, 5]:
        has_ro = (
            models.ResearchOffice.where(
                Q(
                    org__in=Subquery(
                        models.Affiliation.where(person__user=user, end_date__isnull=True).values(
                            "org_id"
                        )
                    )
                )
            ).exists()
            or models.Organisation.where(
                ~Q(ro_email=""),
                ro_email__isnull=False,
                affiliations__person__user=user,
                affiliations__end_date__isnull=True,
            ).exists()
        )
    outstanding_invitations = models.Invitation.outstanding_invitations(user)
    if user.is_approved:
        if is_ro and site_id not in [2, 4, 5] and request.resolver_match.view_name == "index0":
            return render(request, "research_office_index.html", locals())
        outstanding_authorization_requests = models.Member.outstanding_requests(user)
        outstanding_testimonial_requests = models.Referee.outstanding_requests(user)
        outstanding_review_requests = models.Panellist.outstanding_requests(user)
        outstanding_nominations = models.Nomination.where(
            Q(user=user)
            | Q(email__lower=user.email.lower())
            | Q(email__lower__in=Subquery(user.emailaddress_set.values_list("email__lower"))),
            Q(
                ~Q(invitations__state__in=["accepted", "expired", "revoked", "new", "draft"]),
                Q(state__in=["sent", "submitted"]),
            )
            | Q(state="accepted", application__isnull=True),
            round__scheme__current_round=F("round"),
        )
        if is_ro or not is_admin:
            if is_ro:
                # reports to approve
                reports = (
                    models.Report.where(
                        state="submitted",
                        contract__org__research_offices__user=user,
                        contract__state__in=["current", "CUR"],
                    )
                    .distinct()
                    .order_by("state_changed_at")[:7]
                )
            else:
                reports = (
                    models.Report.where(
                        Q(
                            contract__members__user=user,
                            contract__members__role_id__in=["PC", "PI"],
                        )
                        | Q(efforts__person__user=user, efforts__role_id__in=["PC", "PI"]),
                        state__in=["new", "draft"],
                        contract__state__in=["current", "CUR"],
                    )
                    .distinct()
                    .order_by("state_changed_at")[:7]
                )
            if reports.count():
                current_reports = reports

        if site_id not in [2, 4, 5, 7] or not (user.is_admin):

            applications = models.Application.user_draft_applications(user).filter(
                ~Q(round__panellists__user=user),
                round__scheme__current_round=F("round"),
                # round__in=models.Scheme.objects.values("current_round"),
            )

            if is_ro or applications.count() < 7:
                if site_id in [2, 4, 5] or is_ro:
                    draft_applications = applications.order_by(
                        "round__ordering", "first_name", "last_name"
                    )
                else:
                    draft_applications = applications.order_by("round__ordering", "number")

            applications = models.Application.user_applications(
                user, ["submitted", "in_review", "accepted", "approved"], request=request
            ).filter(
                ~Q(round__panellists__user=user),
                round__in=models.Scheme.objects.values("current_round"),
            )
            if is_ro or applications.count() < 7:
                current_applications = applications.order_by("round__ordering", "number")

            if site_id in [4, 5]:
                reports = models.Report.user_objects(user=user, state=["new", "draft"])
                if reports.count() < 7:
                    new_reports = reports

        if user.is_staff or user.is_superuser or user.is_site_staff:
            outstanding_identity_verifications = models.IdentityVerification.where(
                ~Q(file=""),
                user__is_active=True,
                file__isnull=False,
                state__in=["new", "sent"],
                user__registered_on_id=site_id,
            )
            user_verifications = User.where(
                Q(Q(is_approved=False) | Q(is_approved__isnull=True)),
                is_active=True,
                registered_on_id=site_id,
            ).order_by("-last_login")
        schemes = list(models.SchemeApplication.get_data(user))

        if site_id == 2:
            applications = {
                round_id: list(user_applications)
                for (round_id, user_applications) in groupby(
                    models.Application.where(
                        Q(submitted_by=user) | Q(members__user=user, members__role="PI"),
                        round__in=[s.current_round_id for s in schemes],
                    ).order_by("round_id", "number"),
                    lambda a: a.round_id,
                )
            }
            applications = {
                a[0]: {
                    "applications": a[1],
                    "wip_count": sum(1 for o in a[1] if o.state in ["new", "draft"]),
                    "count": len(a[1]),
                }
                for a in applications.items()
            }
            for s in schemes:
                round_applications = applications.get(s.current_round_id, None)
                if round_applications:
                    s.applications = round_applications["applications"]
                    s.wip_count = round_applications["wip_count"]
                    s.application_count = round_applications["count"]
                else:
                    s.applications = None

        previous_applications = [
            dict(
                id=pa.previous_application_id,
                number=pa.previous_application_number,
                title=pa.previous_application_title,
                created_on=pa.previous_application_created_on,
            )
            for pa in schemes
            if pa.previous_application_id
        ]
        if (
            site_id in [2, 4, 5]
            and request.method == "POST"
            and (message := request.POST.get("message", "").strip())
            and (round_id := request.POST.get("round"))
            and (request_round := models.Round.where(id=round_id).first())
        ):
            is_ajax = not request.META.get("HTTP_ACCEPT", "").startswith("text/html")
            ro_emails = [
                (ro.full_name or _("Research Office"), ro.email)
                for ro in User.where(
                    research_offices__org__in=Subquery(
                        models.Affiliation.where(
                            Q(org__ro_email__isnull=True) | Q(org__ro_email=""),
                            person__user=user,
                            end_date__isnull=True,
                        ).values("org_id")
                    )
                ).distinct()
            ]
            ro_emails.extend(
                [
                    (_("Research Office"), email)
                    for email, in models.Organisation.where(
                        ~Q(ro_email=""),
                        ro_email__isnull=False,
                        affiliations__person__user=user,
                        affiliations__end_date__isnull=True,
                    )
                    .distinct()
                    .values_list("ro_email")
                    if email and email.strip() != ""
                ]
            )
            if ro_emails:
                try:
                    url = request.build_absolute_uri(
                        reverse("nomination-create", kwargs={"round": request_round.id})
                    )
                    send_mail(
                        "Request to nominate an applicant",
                        html_message=(
                            f"<p>User {request.user.full_name_with_email} has requested for "
                            f"a nomination to apply for the round {request_round}:</p>"
                            f"<pre>{message}</pre>"
                            f'<p>You can submit the nomination at <a href="{url}">Nominate for {request_round}</a>.</p>'
                        ),
                        reply_to=user.full_email_address,
                        recipients=ro_emails,
                        cc=[user.full_email_address],
                        request=request,
                    )
                except Exception as e:
                    capture_exception(e)
                    if is_ajax:
                        return JsonResponse({"message": str(e), "status": "error"}, status=200)
                    messages.error(request, str(e))
                else:
                    message = _("Your request was sent to the Research Office.")
                    if is_ajax:
                        return JsonResponse({"message": message, "status": "info"}, status=200)
                    messages.info(request, message)
        if len(schemes) == 0:
            return redirect("about")
    else:
        messages.info(
            request,
            _("Your profile has not been approved, Admin is looking into your request"),
        )

    return render(request, "index.html", locals())


# @login_required
# def test_task(req, message):
#     notify_user(req.user.id, message)
#     messages.info(req, _("Task submitted with a message '%s'") % message)
#     return render(req, "index.html", locals())


def check_profile(request, token=None):
    if token and any(token.endswith(c) for c in "<>'\""):
        token = token.strip("<>'\"")
    try:
        if not request.user.is_authenticated:
            invitation = models.Invitation.where(token=token).first()
            user_exists = invitation and (
                User.objects.filter(email=invitation.email).exists()
                or EmailAddress.objects.filter(email=invitation.email).exists()
            )

            if token:
                request.session["invitation_token"] = token
                if (i := models.Invitation.where(token=token).first()) and i.state == "revoked":
                    messages.warning(
                        request,
                        _("The invitation has been revoked and is not any more valid."),
                    )
            return redirect(
                reverse("account_login" if user_exists else "account_signup")
                + f"?next={quote(request.get_full_path())}"
            )

        next_url = request.GET.get("next")
        # TODO: refactor and move to the model the invitation handling:
        u = User.get(request.user.pk)
        if not token:
            if (
                i := models.Invitation.where(
                    Q(state__isnull=True)
                    | Q(state__in=["draft", "submitted", "sent", "bounced", "read"])
                    | Q(email=u.email)
                    | Q(email__in=u.email_addresses)
                )
                .order_by("-id")
                .first()
            ) and i.token:
                token = i.token

        if token:
            if i := models.Invitation.where(token=token).first():
                if not (
                    i.email.lower() == u.email.lower()
                    or u.emailaddress_set.filter(
                        email__lower=i.email.lower(), verified=True
                    ).exists()
                ):
                    messages.warning(
                        request,
                        _(
                            "The invitation was not sent to any of this profile's email addresses. "
                            "Please use and log in with the account that is linked with the email "
                            "address that received the invitation."
                        ),
                    )
                    return redirect(next_url or "start")

            else:
                messages.warning(request, _("There is no invitation with the given token."))
                return redirect(next_url or "home")

            if i.state in [
                "new",
                "draft",
                "submitted",
                "sent",
                "bounced",
                "read",
                "accepted",
                "autoreplied",
            ]:
                if i.type:
                    request.session["invitation_type"] = i.type
                    request.session.modified = True

                if (
                    (i.first_name and not u.first_name)
                    or (i.middle_names and not u.middle_names)
                    or (i.last_name and not u.last_name)
                    or not u.is_approved
                ):
                    if i.first_name and not u.first_name:
                        u.first_name = i.first_name
                    if i.middle_names and not u.middle_names:
                        u.middle_names = i.middle_names
                    if i.last_name and not u.last_name:
                        u.last_name = i.last_name
                    if not u.name:
                        u.name = u.full_name
                    u.is_approved = True
                    u.save(
                        update_fields=[
                            "first_name",
                            "last_name",
                            "middle_names",
                            "name",
                            "is_approved",
                        ]
                    )

                if u.email != i.email:
                    ea, created = EmailAddress.objects.get_or_create(
                        email=i.email, defaults=dict(user=u, verified=True)
                    )
                    if not created and ea.user != u:
                        messages.warning(
                            request, _("there is already user with this email address: ") + i.email
                        )

                if i.state == "accepted":
                    messages.warning(
                        request,
                        _("The invitation has been already accepted."),
                    )
                    next_url = i.handler_url
                else:
                    i.accept(by=u, request=request)
                    i.save()
                    reset_cache(request)

                if i.type == "A" and (n := i.nomination):
                    if not n.user:
                        n.user = u
                        n.save(update_fields=["user"])
                    if a := n.application:
                        if a.submitted_by == u:
                            next_url = reverse("application-update", kwargs={"pk": a.id})
                        else:
                            next_url = reverse("application", kwargs={"pk": a.id})
                    elif n.pk:
                        next_url = reverse(
                            "nomination-application-create", kwargs={"nomination": n.pk}
                        )
                    else:
                        next_url = reverse("application-create", kwargs={"round": n.round_id})
                elif i.type == "T" and (m := i.member) and (a_id := m.application_id):
                    next_url = reverse("application", kwargs={"pk": a_id})
                elif i.type == "R" and (r := i.referee):
                    if (
                        testimonial_submission_closes_at := r.application.round.testimonial_submission_closes_at
                    ) and testimonial_submission_closes_at < timezone.now():
                        messages.error(
                            request,
                            mark_safe(
                                _(
                                    "The referee report submission was closed on "
                                    f"<b>{testimonial_submission_closes_at.date().isoformat()}</b> "
                                    f"at <b>{testimonial_submission_closes_at.time()}</b>."
                                )
                            ),
                        )
                        return redirect(next_url or "home")
                    if (round := i.round or r.application.round) and not round.is_active:
                        message = _("The invitation round is not active.")
                        if (
                            current_round := round.scheme.current_round
                        ) and current_round != round:
                            message = (
                                f'{message} {_(f"The current round is <b>{current_round}</b>")}.'
                            )
                        url = None
                        if (
                            current_invitation := models.Invitation.where(
                                ~Q(state__in=["revoked", "accepted"]),
                                email__lower__in=u.emailaddress_set.values_list("email__lower"),
                            )
                            .order_by("-pk")
                            .first()
                        ):
                            url = current_invitation.url or current_invitation.get_full_url(
                                "onboard-with-token",
                                request=request,
                                token=current_invitation.token,
                            )
                            message = f"""{message} {_(f'The most current invitation sent to you is <a href="{url}">{url}</a>')}.
                             {_('Please follow the invitation link')}."""

                        messages.warning(request, mark_safe(message))
                        return redirect(url or "home")

                    if not (r.survey_token_id or r.survey_token) and (
                        t := models.Testimonial.where(referee=r).last()
                    ):
                        next_url = reverse("testimonial", kwargs={"pk": t.id})
                    elif a_id := r.application_id:
                        # messages.info(
                        #     request,
                        #     (
                        #         _(
                        #             "Please review the application details and submit referee report."
                        #         )
                        #         if i.site_id in [2, 4, 5]
                        #         else _(
                        #             "Please review the application details and submit testimonial."
                        #         )
                        #     ),
                        # )
                        next_url = reverse("application", kwargs={"pk": a_id})

            elif i.state == "revoked":
                next_url = None
                messages.warning(
                    request,
                    _("The invitation has been revoked and is not any more valid."),
                )
            elif i.state == "expired" or not i.state:
                next_url = None
                messages.warning(
                    request,
                    _("The invitation expired and is not any more valid."),
                )

        # if Person.where(user=request.user).exists() and request.user.person.is_completed:
        if Person.where(user=u).exists():
            if token and (
                i := models.Invitation.where(
                    token=token, type="P", panellist__isnull=False
                ).first()
            ):
                next_url = reverse("round-coi", kwargs=dict(round=i.panellist.round_id))

            return redirect(next_url or "home")
        else:
            messages.info(
                request,
                _("Your profile is not completed yet. " "Please complete your profile."),
            )
            if token and models.Invitation.where(token=token, type="T", site_id=2).exists():
                messages.warning(
                    request,
                    _(
                        "Please make sure you filled up your postal address and current affiliation data, "
                        "and uploaded a current CV."
                    ),
                )
            # person.is_employments_completed = True
            # person.is_professional_bodies_completed = True
            # person.is_career_stages_completed = True
            # person.is_external_ids_completed = True
            # person.is_cvs_completed = True
            # person.is_academic_records_completed = True
            # person.is_recognitions_completed = True
            return redirect(
                reverse("profile-update")
                if Person.where(user=u).exists()
                else reverse("profile-create")
                + "?next="
                + (quote(next_url) if next_url else reverse("home"))
            )
    except Exception as e:
        capture_exception(e)
        raise


@login_required
def user_profile(request, pk=None):
    u = User.objects.get(pk=pk) if pk else request.user
    return (
        redirect("profile") if models.Person.where(user=u).exists() else redirect("profile-create")
    )


def is_profile_completed(request):
    if not Person.where(user=request.user).exists():
        return False
    if request.session.get("wizard"):
        if (views := request.session.get("wizard-views")) and views != []:
            return False
        else:
            turn_off_wizard(request)
    return True


class ProfileViewMixin:

    model = models.Person
    template_name = "profile_form.html"
    form_class = forms.ProfileForm
    slug_url_kwarg = "username"
    slug_field = "user__username"

    def get_user_form(self):
        u = self.request.user
        if self.request.method == "POST":
            user_form = forms.UserForm(self.request.POST, instance=u)
        else:
            user_form = forms.UserForm(instance=u, initial=self.get_initial())
        return user_form

    def get_initial(self):
        u = self.request.user
        if u.first_name and u.last_name and u.title and u.middle_names:
            return {}

        initial = {}  # super().get_initial()
        if (
            i := models.Invitation.where(
                ~Q(
                    first_name__isnull=True,
                    last_name__isnull=True,
                    middle_names__isnull=True,
                ),
                Q(state__isnull=True)
                # | Q(state__in=["draft", "submitted", "sent", "bounced"])
                | Q(email=u.email) | Q(email__in=u.email_addresses),
            )
            .order_by("-id")
            .first()
        ):
            initial.update(
                {
                    "first_name": u.first_name or i.first_name,
                    "last_name": u.last_name or i.last_name,
                    # "title": u.title or i.title,
                    "middle_names": u.middle_names or i.middle_names,
                }
            )

        return initial

    def get_context_data(self, **kwargs):
        if "progress" not in kwargs:
            if not is_profile_completed(self.request):
                kwargs["progress"] = 10
                self.request.session["wizard"] = True

        if "user_form" not in kwargs:
            kwargs["user_form"] = self.get_user_form()

        if "address_form" not in kwargs:
            a = self.address
            kwargs["address_form"] = forms.AddressForm(
                data=self.request.POST or None,
                instance=self.object.address if self.object and self.object.pk else None,
                initial=a
                and {
                    "address": a.address or "",
                    "city": a.city or "",
                    "postcode": a.postcode or "",
                    "country": a.country,
                }
                or {"country": "NZ"},
            )
            kwargs["address_form"].helper.form_tag = False

        return super().get_context_data(**kwargs)

    @cached_property
    def address(self):
        try:
            u = self.request.user
            return (
                self.object.address
                if self.object and self.object.pk
                else None or (u and u.person and u.person.address)
            )
        except ObjectDoesNotExist:
            return None

    def get_success_url(self):
        if not is_profile_completed(self.request):
            return reverse(ProfileSectionFormSetView.section_views[0])
        return super().get_success_url()

    def post(self, request, *args, **kwargs):
        form = self.get_user_form()
        if not form.is_valid():
            return self.form_invalid(form)
        form.save()
        res = super().post(request, *args, **kwargs)
        reset_cache(self.request)
        a = self.address
        form = forms.AddressForm(
            self.request.POST,
            initial=a
            and {
                "address": a.address or "",
                "city": a.city or "",
                "postcode": a.postcode or "",
                "country": a.country,
            }
            or {"country": "NZ"},
        )
        # instance=self.object.address if self.object and self.object.pk else None)
        if form.changed_data:
            if form.data.get("address") and form.data.get("address").strip():
                if not form.is_valid():
                    return self.form_invalid(form)
                a = form.save()
                if self.object:
                    self.object.address = a
            elif self.object:
                self.object.address = None

            if self.object:
                self.object.save(update_fields=["address"])

        return res


@login_required
@csrf_exempt
def disable_profile_protection_patterns(request):
    if request.method == "POST":
        if person := models.Person.where(user=request.user).first():
            models.PersonProtectionPattern.where(person=person).delete()
            person.has_protection_patterns = False
            person.save()
    return HttpResponse(status=204)


@login_required
def profile_protection_patterns(request):
    site_id = settings.SITE_ID
    if not (person := models.Person.where(user=request.user).last()):
        url = reverse("prifile-create")
        if (next_url := request.GET.get("next")) and next_url.startswith("/"):
            url = f"{url}?next={next_url}"
        return redirect(url)
    if request.method == "POST":
        no_protection_needed = "no_protection_needed" in request.POST
        rp = request.POST
        pp_codes = rp.getlist("pp_code")
        pp_flags = {ppc: f"pp_enabled:{ppc}" in rp.keys() for ppc in pp_codes}
        if not no_protection_needed and not any(pp_flags.values()):
            no_protection_needed = True
        person.has_protection_patterns = not no_protection_needed
        person.save()

        if not no_protection_needed:
            expires_on_dates = rp.getlist("expires_on")
            for idx, ppc in enumerate(pp_codes):
                if pp_flags[ppc]:
                    ppp, _ = models.PersonProtectionPattern.objects.get_or_create(
                        protection_pattern_id=ppc, person=person
                    )
                    expires_on = expires_on_dates[idx]
                    if expires_on:
                        ppp.expires_on = expires_on
                        ppp.save()

                else:
                    models.PersonProtectionPattern.where(
                        protection_pattern_id=ppc, person=person
                    ).delete()
        else:
            models.PersonProtectionPattern.where(person=person).delete()

        i = (
            models.Invitation.user_inviations(request.user)
            .filter(~Q(state__in=["bounced", "draft", "expired", "revoked"]))
            .order_by("id")
            .last()
        )

        if "wizard" in request.session or "wizard-views" in request.session:
            turn_off_wizard(request)
            url = (i and i.handler_url) or "index"
        else:
            url = (i and i.handler_url) or "profile"

        if not request.user.is_approved and not person.account_approval_message_sent_at:
            site = Site.objects.get_current()
            person.account_approval_message_sent_at = timezone.now()
            person.save(update_fields=["account_approval_message_sent_at"])
            contact_email = models.site_contact_email(site.id)
            if site_id == 1:
                send_mail(
                    request=request,
                    recipients=[request.user.full_email_address],
                    subject="Account Approval request submitted",
                    html_message=(
                        "<p>Tēnā koe,</p>"
                        f"<p>You have submitted an Account Approval request to {site.name}. "
                        "Please allow up to 2 working days for an Administrator to approve your request. "
                        "If you do not receive a confirmation email after 2 working days, please contact "
                        f"<a href='mailto:{contact_email}'>"
                        f"{contact_email}</a></p>"
                        "<p>(Please also check your Spam/Junk inbox)</p>"
                    ),
                )

        reset_cache(request)
        return redirect(url)

    protection_patterns = person.protection_patterns
    return render(request, "profile_protection_patterns.html", locals())


class ReportList(LoginRequiredMixin, StateInPathMixin, SingleTableMixin, FilterView):
    table_class = tables.ReportTable
    model = models.Report
    template_name = "table.html"
    extra_context = {"category": "reports"}
    template_name = "table.html"
    filterset_class = filters.ReportFilterSet

    def get_queryset(self, *args, **kwargs):
        u = self.request.user
        qs = super().get_queryset(*args, **kwargs)
        qs = self.model.user_objects(user=u, queryset=qs, request=self.request)
        return qs


class SelfAssignMixin:

    def put(self, request, *args, **kwargs):
        url = request.META.get("HTTP_REFERER", "") or request.path
        if (action := request.GET.get("action")) == "assign-self":
            obj = self.get_object()
            u = request.user
            if not u.is_admin:
                messages.error(request, _("You have no permission to assign yourself the report."))
            elif obj.assessor and obj.assessor != u:
                messages.error(request, _("The report was already assigned to {obj.assessor}."))
            elif obj.assessor and obj.assessor == u:
                messages.error(request, _("You are already the assessor of this report."))
            elif not obj.assessor:
                obj.assign_assessor(by=u, assessor=u, request=request)
                obj.save(update_fields=["assessor", "updated_at", "state", "state_changed_at"])
                messages.success(
                    request,
                    _("You successfully assigned yourself as the assessor of this report."),
                )
            response = HttpResponse(status=200)
            response["HX-Redirect"] = url
            return response
        else:
            return super().put(request, *args, **kwargs)


class ReportDetail(SelfAssignMixin, FavoriteMixin, DetailView):
    template_name = "portal/report_detail.html"
    model = models.Report

    def get_object_filter(self, value):
        if isinstance(value, int) or value.isnumeric():
            return {"pk": int(value)}
        parts = value.split(":")
        t, p, *n = parts[::-1]
        n = ":".join(n[::-1])
        return {"period": p, "type": t, "contract__number": n}

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        u = self.request.user
        o = self.object
        context["is_ro"] = o.is_ro(u)
        context["can_edit"] = o.can_edit(u)
        context["is_admin"] = u.is_admin
        return context

    # def get(self, request, *args, **kwargs):
    #     return super().get(request, *args, **kwargs)

    # def get_queryset(self):
    #     return (
    #         super()
    #         .get_queryset()
    #         .prefetch_related(
    #             Prefetch(
    #                 "allocations", queryset=models.Allocation.objects.all().order_by("period")
    #             ),
    #             Prefetch(
    #                 "reporting_schedule",
    #                 queryset=models.ReportingScheduleEntry.objects.all().order_by(
    #                     "period", "due_date"
    #                 ),
    #             ),
    #         )
    #     )


class PersonnelInline(InlineFormSetFactory):
    prefix = "personnel"
    model = models.ReportedEffort
    form_class = forms.ReportedEffortForm
    factory_kwargs = {
        "extra": 1,
        "can_delete": True,
        "labels": {"full_name": _("Name"), "fte": _("FTE from contract")},
    }

    def get_form_class(self):
        if self.object and self.request and self.object.assessor == self.request.user:
            return modelform_factory(
                self.model, form=self.form_class, exclude=["state", "member_effort"]
            )
        return self.form_class


class AssessedPerformanceInline(InlineFormSetFactory):
    prefix = "performance"
    model = models.AssessedPerformance
    # fields = ["first_name", "middle_names", "last_name", "email"]
    form_class = forms.AssessedPerformanceForm
    # formset_kwargs = {}
    factory_kwargs = {
        "extra": 0,
        "can_delete": False,
    }


class ReportViewMixin:

    inlines = [PersonnelInline]

    def put(self, request, *args, **kwargs):
        if (action := request.GET.get("action")) == "assign-self":
            obj = self.get_object()
            u = request.user
            if not u.is_admin:
                messages.error(request, _("You have no permission to assign yourself the report."))
            elif obj.assessor and obj.assessor != u:
                messages.error(request, _("The report was already assigned to {obj.assessor}."))
            elif obj.assessor and obj.assessor == u:
                messages.error(request, _("You are already the assessor of this report."))
            elif not obj.assessor:
                obj.assign_assessor(by=u, assessor=u, request=request)
                obj.save(update_fields=["assessor", "updated_at", "state", "state_changed_at"])
                messages.success(
                    request,
                    _("You successfully assigned yourself as the assessor of this report."),
                )
            return self.get(request, *args, **kwargs)
        else:
            return super().put(request, *args, **kwargs)

    def get_inlines(self):
        inlines = super().get_inlines()
        if self.is_assessor and AssessedPerformanceInline not in inlines:
            inlines.append(AssessedPerformanceInline)
        return inlines

    @property
    def is_assessor(self):
        return self.object and self.request.user == self.object.assessor

    # def forms_valid(self, *args, **kwargs):
    #     return super().forms_valid(*args, **kwargs)

    # def forms_invalid(self, *args, **kwargs):
    #     return super().forms_invalid(*args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

        # def get_allocation_formset(self, *args, **kwargs):
        #     if self.object and self.object.id:
        #         extra = 0
        #         initial_allocations = []
        #     else:
        #         a = self.application
        #         duration = a.round.duration or 3
        #         extra = duration
        #         initial_allocations = [
        #             dict(
        #                 period=p,
        #                 allocation=0.0,
        #             )
        #             for p in range(1, duration + 1)
        #         ]
        #     fsc = forms.inlineformset_factory(
        #         models.Report,
        #         models.Allocation,
        #         can_delete=False,
        #         form=forms.AllocationForm,
        #         extra=extra,
        #     )
        #     return fsc(
        #         self.request.POST or None,
        #         instance=self.object,
        #         initial=initial_allocations,
        #         # form_kwargs={"duration": duration},
        #     )

        # def get_reporting_schedule_formset(self, *args, **kwargs):
        #     a = self.application
        #     duration = a.round.duration or 3
        #     if self.object and self.object.id:
        #         initial = None
        #         extra = 1
        #     else:
        #         initial = [
        #             dict(
        #                 period=p,
        #                 type="A" if p != duration else "F",
        #                 # due_date=timezone.now()+relativedelta(years=p),
        #                 due_date=a.created_at + relativedelta(years=p),
        #             )
        #             for p in range(1, duration + 1)
        #         ]
        #         extra = duration
        #     fsc = forms.inlineformset_factory(
        #         models.Report,
        #         models.ReportingScheduleEntry,
        #         can_delete=True,
        #         can_delete_extra=True,
        #         # form=forms.AllocationForm,
        #         # fields="__all__",
        #         exclude=["request_info_date", "state", "acknowledged_at"],
        #         extra=extra,
        #         labels={"date_first_remind": _("First Reminder")},
        #         widgets={
        #             "period": forms.Select(
        #                 choices=[(None, "---"), *((i, i) for i in range(1, duration + 1))]
        #             ),
        #             "due_date": forms.DateInput(start_date="-1y", end_date="+10y"),
        #             "date_first_remind": forms.DateInput(start_date="-1y", end_date="+10y"),
        #         },
        #     )
        #     return fsc(
        #         self.request.POST or None,
        #         instance=self.object,
        #         initial=initial,
        #         queryset=models.ReportingScheduleEntry._default_manager.order_by("period", "due_date"),
        #         # form_kwargs={"duration": duration}
        #     )

        # def get_personnel_formset(self, *args, **kwargs):
        #     a = self.application
        #     duration = a and a.round.duration or 3
        #     if self.object and self.object.id:
        #         extra = 1
        #         initial = []
        #     else:
        #         a = self.application
        #         pi, _ = models.RoleType.objects.get_or_create(
        #             code="PI",
        #             defaults={
        #                 "name": "Principal Investigator",
        #                 "description": "Principal Investigator",
        #             },
        #         )

        #         initial = [
        #             dict(
        #                 email=a.email or a.submitted_by.email,
        #                 first_name=a.first_name or a.submitted_by and a.submitted_by.first_name,
        #                 middle_names=a.middle_names,
        #                 last_name=a.last_name or a.submitted_by and a.submitted_by.last_name,
        #                 role=pi.code,
        #                 user=a.submitted_by,
        #             ),
        #             *[
        #                 dict(
        #                     email=m.email,
        #                     first_name=m.first_name or m.user and m.user.first_name,
        #                     middle_names=m.middle_names,
        #                     last_name=m.last_name or m.user and m.user.last_name,
        #                     role=m.role and models.RoleType.where(name__icontains=m.role).first(),
        #                     user=m.user,
        #                 )
        #                 for m in a.members.all()
        #             ],
        #         ]
        #         extra = len(initial) + 1
        #     fsc = forms.inlineformset_factory(
        #         models.Report,
        #         models.ReportMember,
        #         can_delete=True,
        #         form=forms.ReportMemberForm,
        #         extra=extra,
        #     )
        #     return fsc(
        #         self.request.POST or None,
        #         instance=self.object,
        #         initial=initial,
        #         form_kwargs={"duration": duration},
        #     )

        # def get_document_formset(self, *args, **kwargs):
        #     round = self.application.round
        #     exclued_document_roles = [r for _, r in self.form_class.part_fields]

        #     initial = []
        #     if not (self.object and self.object.id):
        #         for d in self.application.documents.filter(
        #             ~Q(document_type__role__in=exclued_document_roles)
        #         ):
        #             dt, dtr, df = d.document_type, d.document_type.role, d.file
        #             role = dtr
        #             if role in ["AF", "B"]:
        #                 if role == "AF":
        #                     role = "AIM"
        #                 elif role == "B":
        #                     role = "PB"

        #             if role == dtr:
        #                 rcd = round.required_report_documents.filter(document_type=dt).last()
        #                 if not rcd:
        #                     rcd = round.required_report_documents.create(document_type=dt)
        #             else:
        #                 rcd = round.required_report_documents.filter(document_type__role=role).last()
        #                 if not rcd:
        #                     dt = models.DocumentType.where(role=role).last()
        #                     if not dt:
        #                         dt = models.DocumentType.create(role=role)
        #                     rcd = round.required_report_documents.create(document_type=dt)

        #             initial.append(
        #                 dict(
        #                     application_document=d.pk,
        #                     required_document=rcd,
        #                     document_type=rcd.document_type,
        #                     file=df,
        #                 )
        #             )
        #     elif self.request.method != "POST":
        #         initial = [
        #             dict(
        #                 required_document=rd,
        #                 document_type=rd.document_type,
        #             )
        #             for rd in (
        #                 round.required_report_documents.values_list("id", "document_type")
        #                 .filter(
        #                     ~Q(id__in=self.object.documents.values("required_document_id")),
        #                     ~Q(document_type__role__in=exclued_document_roles),
        #                 )
        #                 .order_by("ordering")
        #             )
        #         ]

        # class ReportDocumentForm(ModelForm):

        #     application_document = fields.Field(widget=HiddenInput(), required=False)

        #     def save(self, commit=True):
        #         if (
        #             "application_document" in self.cleaned_data
        #             and not self.cleaned_data["file"]
        #             and (
        #                 d := models.ApplicationDocument.get(
        #                     self.cleaned_data["application_document"]
        #                 )
        #             )
        #         ):
        #             res = super().save(commit=False)
        #             res.file = d.file
        #             res.save()
        #             return res
        #         elif "file" in self.changed_data:
        #             res = super().save(*args, **kwargs)
        #             return res
        #         return self.instance

        # class Meta:
        #     model = models.ReportDocument
        #     exclude = ["converted_file"]

        # fsc = forms.inlineformset_factory(
        #     models.Report,
        #     models.ReportDocument,
        #     form=ReportDocumentForm,
        #     extra=len(initial),
        #     can_delete=False,
        #     exclude=[
        #         "converted_file",
        #     ],
        #     widgets={
        #         "application_document": HiddenInput(),
        #         "required_document": HiddenInput(),
        #         "state": HiddenInput(),
        #         "page_count": HiddenInput(),
        #         "document_type": HiddenInput(),
        #         # "required_document": widgets.Select(attrs={"disabled": True}),
        #         # "page_count": widgets.TextInput(attrs={"readonly": True, "disabled": True}),
        #         "file": widgets.ClearableFileInput(
        #             attrs={
        #                 "placeholder": _("Please upload a file ..."),
        #                 "data-placeholder": _("Please upload a file ..."),
        #                 "data-required": 1,
        #                 "oninvalid": "this.setCustomValidity('%s')"
        #                 % _("The file is required. Please upload a file ..."),
        #                 "oninput": "this.setCustomValidity('')",
        #             }
        #         ),
        #     },
        # )

        # # exclude budgets
        # class fsc(fsc):
        #     def get_queryset(self):
        #         qs = super().get_queryset()
        #         return qs.filter(~Q(document_type__role__in=exclued_document_roles))

        # if self.request.POST:
        #     fs = fsc(
        #         self.request.POST or None,
        #         self.request.FILES or None,
        #         instance=self.object,
        #         # initial=initial,
        #     )
        # else:
        #     fs = fsc(instance=self.object, initial=initial)
        # if initial:
        #     fs.extra = len(initial)
        # return fs

    # def get_address_form(self):
    # report = self.object
    # application = self.application
    # applicant = application and application.submitted_by.person

    # a = None
    # if report and report.address:
    #     a = report.address
    # if not (report and report.pk):
    #     if not a and applicant:
    #         a = applicant.address
    #     if not a and application:
    #         a = applicant.address

    # return forms.AddressForm(
    #     data=self.request.POST or None,
    #     instance=a,
    #     initial=a
    #     and {
    #         "address": a.address or "",
    #         "city": a.city or "",
    #         "postcode": a.postcode or "",
    #         "country": a.country,
    #     }
    #     or {"country": "NZ"},
    # )

    def get_personnel_formset(self, *args, **kwargs):
        a = self.application
        duration = self.object and self.object.duration or a and a.round.duration or 3
        if self.object and self.object.pk:
            extra = 1
            initial = []
        else:
            a = self.application
            pi, _ = models.RoleType.objects.get_or_create(
                code="PI",
                defaults={
                    "name": "Principal Investigator",
                    "description": "Principal Investigator",
                },
            )
            pc, _ = models.RoleType.objects.get_or_create(
                code="PC",
                defaults={
                    "name": "Principal Investigator (Contract)",
                    "description": "Principal Investigator (Contract)",
                },
            )

            initial = [
                dict(
                    email=a.email or a.submitted_by.email,
                    first_name=a.first_name or a.submitted_by and a.submitted_by.first_name,
                    middle_names=a.middle_names,
                    last_name=a.last_name or a.submitted_by and a.submitted_by.last_name,
                    role=pc.code,
                    user=a.submitted_by,
                ),
                *[
                    dict(
                        email=m.email,
                        first_name=m.first_name or m.user and m.user.first_name,
                        middle_names=m.middle_names,
                        last_name=m.last_name or m.user and m.user.last_name,
                        role=m.role and models.RoleType.where(name__icontains=m.role).first(),
                        user=m.user,
                    )
                    for m in a.members.all()
                ],
            ]
            extra = len(initial) + 1
        fsc = forms.inlineformset_factory(
            models.Contract,
            models.ContractMember,
            can_delete=True,
            form=forms.ContractMemberForm,
            extra=extra,
        )
        return fsc(
            self.request.POST or None,
            instance=self.object,
            initial=initial,
            form_kwargs={"duration": duration},
        )

    def get_for_formset(self, *args, **kwargs):
        fsc = forms.inlineformset_factory(
            self.model,
            self.model.fors.through,
            extra=1,
            can_delete=True,
            exclude=[],
            # fields = ["id", "code", "application", "share"],
            labels={"code": _("Field of Research")},
            help_texts={
                "code": _("Field of Research"),
                "share": _("Share in %"),
            },
            widgets={
                "code": autocomplete.ModelSelect2(
                    "for-autocomplete",
                    attrs={
                        "data-placeholder": _("Choose a field of research..."),
                        "placeholder": _("Choose a field of research..."),
                        "data-required": 1,
                        "oninvalid": "this.setCustomValidity('%s')"
                        % _("Field of research is required"),
                        "oninput": "this.setCustomValidity('')",
                    },
                ),
            },
        )

        initial_fors = (
            [
                dict(
                    code=r.code_id,
                    share=r.share,
                )
                for r in self.contract.application.fors.all()
            ]
            if not (self.object and self.object.pk)
            else []
        )
        # fs = fsc(self.request.POST or None, instance=self.object, initial=initial_fors)
        if self.request.POST:
            fs = fsc(self.request.POST, instance=self.object)
        elif not (self.object and self.object.pk):
            fs = fsc(instance=self.object, initial=initial_fors)
        else:
            fs = fsc(instance=self.object)
        if initial_fors:
            fs.extra = len(initial_fors)

        return fs

    def get_seo_formset(self, *args, **kwargs):
        fsc = forms.inlineformset_factory(
            self.model,
            self.model.seos.through,
            # form=forms.RefereeForm,
            extra=1,
            can_delete=True,
            exclude=[],
            labels={"code": _("Socio-Economic Objective")},
            help_texts={
                "code": _("Socio-Economic Objective"),
                "share": _("Share in %"),
            },
            widgets={
                "code": autocomplete.ModelSelect2(
                    "seo-autocomplete",
                    forward=(
                        "id",
                        forward.Const("report", "type"),
                    ),
                    attrs={
                        "data-placeholder": _("Choose a ..."),
                        "placeholder": _("Choose a Socio-Economic Objective..."),
                        "data-required": 1,
                        "oninvalid": "this.setCustomValidity('%s')"
                        % _("Socio-Economic Objective is required"),
                        "oninput": "this.setCustomValidity('')",
                    },
                ),
            },
        )
        initial_seos = (
            [
                dict(
                    code=r.code_id,
                    share=r.share,
                )
                for r in self.object.contract.appication.seos.all()
            ]
            if not (self.object and self.object.pk)
            else []
        )
        fs = fsc(
            self.request.POST or None,
            instance=self.object,
            initial=initial_seos,
        )
        fs.extra = len(initial_seos) or 1
        return fs

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        u = self.request.user
        # context["current_date"] = timezone.localdate()
        context["current_date"] = timezone.now().date()
        r = self.object

        # self.allocations = context["allocations"] = self.get_allocation_formset()
        # self.reporting_schedule = context["reporting_schedule"] = (
        #     self.get_reporting_schedule_formset()
        # )
        # self.personnel = context["personnel"] = self.get_personnel_formset()
        context["contract"] = c = r.contract
        context["application"] = a = c.application
        context["round"] = round = a.round
        if c.host_contact_email:
            context["coordinator"] = c.host_contact_email
        elif nomination := models.Nomination.where(application=a).order_by("-pk").first():
            context["nomination"] = nomination
            context["coordinator"] = nomination.nominator.full_name_with_email

        context["is_pi"] = (a.submitted_by == u) or (
            self.object
            and self.object.pk
            and self.object.is_pi(u)
            # and self.object.contract.members.filter(role="PI").exists()
        )
        if r and r.pk:
            context["needs_attention"] = ["research", "finances"]
            if not r or r.assessor == u:
                context["needs_attention"].append("report")

        if round.has_fors:
            fs = self.get_for_formset()
            context["fors"] = fs

        if round.has_seos:
            fs = self.get_seo_formset()
            context["seos"] = fs

        # Effort:
        # fsc = forms.inlineformset_factory(
        #     self.model,
        #     models.ReportedEffort,
        #     form=forms.ReportedEffortForm,
        #     extra=1,
        #     can_delete=True,
        #     # exclude=["member_effort", "person", "state"],
        #     labels={"full_name": _("Name"), "fte": _("FTE from contract")},
        #     # help_texts={
        #     #     "": _("Socio-Economic Objective"),
        #     #     "share": _("Share in %"),
        #     # },
        #     # widgets={
        #     #     "code": autocomplete.ModelSelect2(
        #     #         "seo-autocomplete",
        #     #         forward=("pk", "model_name",),
        #     #         attrs={
        #     #             "data-placeholder": _("Choose a ..."),
        #     #             "placeholder": _("Choose a Socio-Economic Objective..."),
        #     #             "data-required": 1,
        #     #             "oninvalid": "this.setCustomValidity('%s')"
        #     #             % _("Socio-Economic Objective is required"),
        #     #             "oninput": "this.setCustomValidity('')",
        #     #         },
        #     #     ),
        #     # },
        # )
        # initial_seos = (
        #     [
        #         dict(
        #             code=r.code_id,
        #             share=r.share,
        #         )
        #         for r in models.ApplicationSeo.where(application=a)
        #     ]
        #     if not (self.object and self.object.pk)
        #     else []
        # )
        # fs = fsc(
        #     self.request.POST or None,
        #     instance=self.object,
        #     # initial=initial_seos,
        # )
        # # fs.extra = len(initial_seos) or 1
        # fs.extra = 1
        # context["personnel"] = fs

        inlines = kwargs.get("inlines", []) or context.get("inlines") or self.construct_inlines()
        context.update((fs.prefix, fs) for fs in inlines)

        # self.documents = context["documents"] = self.get_document_formset()
        # context["required_documents"] = {
        #     rd.id: rd for rd in round.required_report_documents.all().order_by("ordering")
        # }
        # if "address_form" not in kwargs:
        #     context["address_form"] = self.get_address_form()

        return context

    def post(self, *args, **kwargs):
        user = self.request.user
        if self.request.GET.get("action") == "publication_import_from_orcid":
            report = self.get_object()
            api = OrcidHelper(user)
            data, success = api.get_orcid_data(path="/works")
            put_codes = set()
            for f in data.get("group"):
                for s in f["work-summary"]:
                    title = s["title"]["title"]["value"]
                    publication_date = FuzzyDate.create(s.get("publication-date")).start_date()
                    put_codes.add(s["put-code"])

            publications = []
            for put_code in put_codes:
                data, _ = api.get_orcid_data(path=f"/work/{put_code}")
                publications.append(data)

            with transaction.atomic():
                for data in publications:
                    put_code = data["put-code"]
                    publication_date = FuzzyDate.create(s.get("publication-date")).start_date()
                    title = data["title"]["title"]["value"]
                    sub_title = data["title"].get("subtitle")
                    title2 = sub_title.get("value") if sub_title else None
                    url = data.get("url")
                    journal_title = data.get("journal-title")
                    citation = data.get("citation")
                    external_ids = data.get("external-ids")
                    doi = None
                    if external_ids:
                        for ei in external_ids.get("external-id"):
                            if ei.get("external-id-type") == "doi":
                                doi = ei.get("external-id-value")
                                break

                    publication_type = data.get("type")
                    if publication_type:
                        pt = models.PublicationType.where(
                            Q(orcid_type=publication_type) | Q(code=publication_type.upper())
                        ).first()
                        if not pt:
                            pt, _ = models.PublicationType.get_or_create(
                                Q(orcid_type=publication_type) | Q(code=publication_type.upper()),
                                defaults=dict(
                                    code=publication_type.upper(),
                                    description=publication_type.title(),
                                ),
                            )
                        elif not pt.orcid_type:
                            pt.orcid_type = publication_type
                            pt.save(update_fields=["orcid_type"])
                    else:
                        pt = None

                    p, created = models.Publication.get_or_create(
                        abstract=data.get("short-description"),
                        doi=doi,
                        orcid=self.request.user.get_orcid(),
                        put_code=put_code,
                        # publication_date=publication_date,
                        year_ref=publication_date.year if publication_date else None,
                        title2=title2,
                        title=title,
                        type=pt,
                        url=url and url.get("value"),
                        # citations =
                        # citations_date =
                        # editor =
                        # host =
                        # host_ref =
                        # impact_factor =
                        # impact_year =
                        # isi_loc =
                        # journal =
                        # location = e.get("publisher"),
                        # page_ref =
                        # publisher=e.get("publisher"),
                        # rsnz_ref =
                        # state = '',
                        # status =
                        # status_date =
                        # uid =
                        # updated_at =
                        # volume=e.get("volume"),
                        # xcr =
                        # year_ref=e.get("year"),
                    )
                    report.publications.through.objects.get_or_create(report=report, publication=p)

            return render(
                self.request, "partials/report_publication_list.html", {"report": report}
            )
        if self.request.GET.get("action") == "funding_import_from_orcid":
            report = self.get_object()
            api = OrcidHelper(user)
            data, success = api.get_orcid_fundings()
            put_codes = set()
            for f in data.get("group"):
                for s in f["funding-summary"]:
                    title = s["title"]["title"]["value"]
                    start_date = FuzzyDate.create(s.get("start-date")).start_date()
                    end_date = FuzzyDate.create(s.get("end-date")).end_date()
                    put_codes.add(s["put-code"])

            for put_code in put_codes:
                data, _ = api.get_orcid_data(path=f"/funding/{put_code}")
                title = data["title"]["title"]["value"]
                funding_type = data.get("type")
                funding_type = funding_type and funding_type[0].upper() or None
                start_date = FuzzyDate.create(s.get("start-date")).start_date()
                end_date = FuzzyDate.create(s.get("end-date")).end_date()
                amount = data.get("amount")
                if amount:
                    currency = amount.get("currency-code")
                    amount = amount.get("value")
                else:
                    currency = None
                organisation = data.get("orgnanization")
                if organisation:
                    org_name = organisation.get("name")
                    org_address = organisation.get("address")
                    country_code = org_address and org_address.get("country")
                    q = models.Organisation.where(name=org_name)
                    if country_code:
                        q = q.filter(address__country_id=country_code)
                    org = q.last()
                    if not org:
                        if org_address:
                            city = org_address.get("city")
                            region = org_address.get("region")
                            country_code = org_address.get("country")
                            country = (
                                country_code and models.Country.where(code=country_code).last()
                            )

                            address, _ = models.Address.get_or_create(
                                address=f"{org_name}\n{region}\n{country.name}",
                                region=region,
                                country=country,
                            )
                        org, _ = models.Organisation.get_or_create(
                            name=org_name,
                            address=address,
                        )
                else:
                    org = None
                    org_name = None

                organization_defined_type = data.get("organization-defined-type")
                url = data.get("url")
                models.ReportedFunding.get_or_create(
                    orcid=self.request.user.get_orcid(),
                    put_code=put_code,
                    report=report,
                    # state = '',
                    defaults=dict(
                        type=funding_type,
                        subtype=organization_defined_type
                        and organization_defined_type.get("value"),
                        title=title,
                        url=url and url.get("value"),
                        description=data.get("short-description"),
                        currency_id=currency,
                        amount=amount,
                        start_date=start_date,
                        end_date=end_date,
                        agency=org,
                        agency_name=org_name,
                    ),
                )

            return render(self.request, "partials/report_funding_list.html", {"report": report})

        return super().post(*args, **kwargs)

    # def form_invalid(self, form):
    #     return super().form_invalid(form)

    def form_valid(self, form):
        r = i = form.instance or self.object
        c = r.contract
        a = c.application
        round = a.round
        u = self.request.user
        # if not i.submitted_by:
        #     i.submitted_by = u
        # if not i.org:
        #     i.org = a.org
        # if not i.application:
        #     i.application = a
        # if not i.number:
        #     i.number = models.Report.new_number(application=a)
        # if not i.fund:
        #     i.fund = models.Fund.last()
        try:
            with transaction.atomic():
                resp = super().form_valid(form)
                update_url = i and i.pk and reverse("report-update", kwargs=dict(pk=i.pk))

                if round.has_seos:
                    seos = self.get_seo_formset()
                    if not seos.instance or not seos.instance.id:
                        seos.instance = i
                    if seos.is_valid():
                        seos.save()
                    else:
                        for f in seos.forms:
                            if not f.is_valid():
                                if "__all__" in f.errors:
                                    messages.error(self.request, f.errors["__all__"])
                        if update_url:
                            return redirect(f"{update_url}#categories")
                        return self.form_invalid(form)

                if round.has_fors:
                    fors = self.get_for_formset()
                    if not fors.instance or not fors.instance.id:
                        fors.instance = i
                    if fors.is_valid():
                        fors.save()
                    else:
                        for f in fors.forms:
                            if not f.is_valid():
                                if "__all__" in f.errors:
                                    messages.error(self.request, f.errors["__all__"])

                        if update_url:
                            return redirect(f"{update_url}#categories")
                        return self.form_invalid(form)

                if "submit_report" in form.data:
                    i.submit(request=self.request)
                    i.save()
                elif "assess" in form.data:
                    i.assess(request=self.request)
                    i.save()
                elif "approve" in form.data:
                    description = (
                        self.request.POST.get("description")
                        or self.request.POST.get("resolution")
                        or f"{u} approved report {i}"
                    )
                    i.approve(request=self.request, description=description)
                    i.save()

        except Exception as ex:
            capture_exception(ex)
            messages.error(self.request, getattr(ex, "message", str(ex)))
            return super().form_invalid(form)

        # is_host = (
        #     a.org.research_offices.filter(user=u).exists()
        #     or a.submitted_by == u
        #     or a.members.filter(user=u).exists()
        # )
        # recipients = (
        #     (
        #         (
        #             i.host_contact_email
        #             or [u for u in Site.objects.get_current().staff_users.all()]
        #             or [u for u in User.where(is_superuser=True)]
        #         )
        #         if is_host
        #         else [ro.user for ro in a.org.research_offices.all()]
        #         or [u for u in User.where(Q(applications=a) | Q(members__application=a))]
        #     )
        #     if self.request.POST.get("doc_role")
        #     or self.request.POST.get("doc_type")
        #     or "post_comment" in self.request.POST
        #     else []
        # )
        # recipient_list = ", ".join(
        #     [
        #         r.full_name_with_email if isinstance(r, models.User) else r
        #         for r in (recipients if isinstance(recipients, (list, tuple)) else [recipients])
        #     ]
        # )
        # if (
        #     self.request.POST.get("doc_role")
        #     or self.request.POST.get("doc_type")
        #     or self.request.POST.get("required_doc")
        # ):
        #     document_role = form.data.get("doc_role")
        #     document_type = form.data.get("doc_type")
        #     document_action = form.data.get("doc_action")
        #     required_document = form.data.get("required_doc")
        #     resolution = (form.data.get("resolution") or "").strip()
        #     if (document_role in models.DOCUMENT_ROLES or document_type or required_document) and (
        #         d := (
        #             i.documents.filter(required_document=required_document).order_by("id").last()
        #             if required_document
        #             else (
        #                 i.documents.filter(
        #                     required_document__document_type__role=document_role
        #                 ).last()
        #                 if document_role
        #                 else (
        #                     i.documents.filter(
        #                         Q(document_type=document_type)
        #                         | Q(required_document__document_type=document_type)
        #                     )
        #                     .order_by("id")
        #                     .last()
        #                 )
        #             )
        #         )
        #     ):
        #         previous_state = d.state
        #         if document_action == "approve":
        #             if is_host:
        #                 if d.state not in ["accepted", "approved"]:
        #                     d.approve(
        #                         request=self.request, description=resolution or f"approved by {u}"
        #                     )
        #                     # d.save()
        #                 else:
        #                     messages.warning(
        #                         self.request, _("The document was already %s") % _(d.state)
        #                     )
        #             else:
        #                 if d.state != "accepted":
        #                     d.accept(
        #                         request=self.request, description=resolution or f"accepted by {u}"
        #                     )
        #                     # d.save()
        #                 else:
        #                     messages.warning(
        #                         self.request, _("The document was already %s") % _(d.state)
        #                     )
        #             if d.state != previous_state:
        #                 messages.info(self.request, _("The document %s was %s") % (d, _(d.state)))
        #         elif document_action == "request_correction":
        #             d.save_draft(
        #                 request=self.request,
        #                 description=resolution or f"requested corrections by {u}",
        #             )
        #         if previous_state != d.state:
        #             d.save()

        #         respond_url = self.request.build_absolute_uri(
        #             reverse("report-update", kwargs=dict(pk=i.pk))
        #         )
        #         if document_role in ["B", "PB", "AB"]:
        #             respond_url += "#finances"
        #         # elif document_role in ["AIM", "PT"]:
        #         #     respond_url += "#research"
        #         elif document_role or document_type or required_document:
        #             respond_url += "#appendices"

        #         if not document_action or document_action == "approve":
        #             # TODO: notify about approvals after all documents got approved:
        #             html_message = f'<p>The report record <data value="{i.number}">{i}</data> was update by {u.full_name_with_email}:</p>'
        #             html_message += f'<p>Comment posted by {u.full_name_with_email} to <data value="{i.number}">{i}</data>'
        #             html_message += f":</p>{resolution}" if resolution else "."
        #             html_message += f'<hr/>To review the entry, please, click here: <a href="{respond_url}">{i}</a>'
        #             subject = f"Report {i} {d.document_type} {d} was {d.state} by {u.full_name_with_email}"
        #         elif document_action == "request_correction":
        #             html_message = f'<p>The report record <data value="{i.number}">{i}</data> was update by {u.full_name_with_email}'
        #             html_message += f":</p>{resolution}" if resolution else ".</p>"
        #             html_message += f'<hr/>To review the entry, please, click here: <a href="{respond_url}">{i}</a>'
        #             subject = f"{u.full_name_with_email} requested correction(s) of the report {i} {d.document_type} {d}"
        #             messages.info(
        #                 self.request,
        #                 _("The request to amend the %s was sent to %s") % (d, recipient_list),
        #             )
        #         elif document_action in ["request_approval", "awaiting_approval"]:
        #             html_message = f'<p>The report record <data value="{i.number}">{i}</data> was update by {u.full_name_with_email}:'
        #             html_message += f":</p>{resolution}" if resolution else ".</p>"
        #             html_message += f'<hr/>To review the entry, please, click here: <a href="{respond_url}">{i}</a>'
        #             subject = f"{u.full_name_with_email} requested approval of the report {i} {d.document_type} {d}"
        #             messages.info(
        #                 self.request,
        #                 _("The request to approve the %s was sent to %s") % (d, recipient_list),
        #             )
        #         send_mail(
        #             request=self.request,
        #             subject=subject,
        #             html_message=html_message,
        #             cc=[u.full_email_address],
        #             recipients=recipients,
        #             thread_index=i.thread_index,
        #             thread_topic=i.thread_topic,
        #         )
        #         return redirect("report-update", pk=i.pk)

        if "post_comment" in self.request.POST:

            attachment = form.cleaned_data.get("attachment", None)
            if body := form.cleaned_data.get("comment", None):
                body = body.strip()

            if body or attachment:
                CommentForm = modelform_factory(models.ReportComment, exclude=["report", "token"])
                comment_form = CommentForm(
                    self.request.POST or None,
                    self.request.FILES or None,
                )
                comment = comment_form.save(commit=False)
                comment.submitted_by = u
                comment.token = models.get_unique_mail_token()
                comment.report = i
                comment.save()

                subject = (
                    f"{comment.get_category_display()} / {i}"
                    if comment.category
                    else f"Comment posted by {u.full_name_with_email} to {i}"
                )

                _recipients = form.cleaned_data.get("recipients", [])
                _cc_recipients = form.cleaned_data.get("cc_recipients", [])
                recipients = [e.user or e.email for e in i.efforts.filter(role__in=_recipients)]
                if "RO" in _recipients:
                    recipients.extend(c.org.get_ro())
                cc_recipients = [e.user or e.email for e in i.efforts.filter(role__in=_recipients)]
                if "RO" in _cc_recipients:
                    cc_recipients.extend(c.org.get_ro())

                # TODO: default recipients if the sender is a researcher?
                if not recipients:
                    pi = i.pi
                    if u.is_site_staff:
                        recipients = [pi]
                    else:
                        # TODO: ????
                        admin = User.get(username="admin")
                        recipients = [admin]

                report_comment_recipients = [
                    (
                        comment.recipients.model(email=e, comment=comment)
                        if isinstance(e, str)
                        else models.ReportCommentRecipient(user=e, email=e.email, comment=comment)
                    )
                    for e in recipients
                ]
                report_comment_recipients.extend(
                    [
                        (
                            comment.recipients.model(email=e, comment=comment, is_cced=True)
                            if isinstance(e, str)
                            else models.ReportCommentRecipient(
                                user=e, email=e.email, comment=comment, is_cced=True
                            )
                        )
                        for e in cc_recipients
                    ]
                )
                if "RO" in _recipients:
                    report_comment_recipients.extend(
                        [
                            comment.recipients.model(
                                user=ro if not isinstance(ro, str) else None,
                                email=ro.email if not isinstance(ro, str) else ro,
                                comment=comment,
                                is_cced=False,
                            )
                            for ro in c.org.get_ro()
                        ]
                    )
                if "RO" in _cc_recipients:
                    report_comment_recipients.extend(
                        [
                            comment.recipients.model(
                                user=ro if not isinstance(ro, str) else None,
                                email=ro.email if not isinstance(ro, str) else ro,
                                comment=comment,
                                is_cced=True,
                            )
                            for ro in c.org.get_ro()
                        ]
                    )

                comment.recipients.model.objects.bulk_create(report_comment_recipients)

                respond_url = (
                    self.request.build_absolute_uri(self.request.path) + "#correspondence"
                )
                html_message = f'<p>Comment posted by {u.full_name_with_email} to <data value="{i}">{i}</data>'
                html_message += f":</p>{body}" if body else "."
                html_message += f'<hr/>To respond to this message, please, click here: <a href="{respond_url}">REPLY</a>'
                send_mail(
                    request=self.request,
                    from_email="reports",
                    subject=subject,
                    html_message=html_message,
                    cc=cc_recipients,
                    attachments=attachment and [attachment],
                    recipients=recipients,
                    thread_index=i.thread_index,
                    thread_topic=i.thread_topic,
                    token=comment.token,
                )
                return redirect(f"{self.request.path}#correspondence")
        if "save" in self.request.POST:
            return redirect(self.request.path)
        return resp


class ReportCreate(NotesMixin, ReportViewMixin, CreateWithInlinesView):
    model = models.Report
    form_class = forms.ReportForm

    # def post(self, request, *args, **kwargs):
    #     form = self.get_user_form()
    #     if not form.is_valid():
    #         return self.form_invalid(form)
    #     form.save()
    #     reset_cache(self.request)
    #     return super().post(request, *args, **kwargs)

    # def post(self, request, *args, **kwargs):
    #     self.object = None
    #     form = self.get_form()
    #     if form.is_valid():
    #         allocation_fs = self.get_allocation_formset()
    #         return self.form_valid(form)
    #     else:
    #         return self.form_invalid(form)

    # def get_context_data(self, **kwargs):
    #     data = super().get_context_data(**kwargs)

    #     if "user_form" not in kwargs:
    #         kwargs["user_form"] = self.get_user_form()

    #     return data

    def get_initial(self, *args, **kwargs):
        initial = super().get_initial(*args, **kwargs)
        a = self.application
        r = a.round

        initial["application"] = a
        initial["year"] = a.created_at.year
        initial["org"] = a.org
        initial["project_title"] = a.application_title or a.round.title
        initial["start_date"] = timezone.now()
        if r.duration:
            initial["end_date"] = timezone.now() + relativedelta(years=r.duration)

        initial["user"] = self.request.user
        initial["number"] = models.Report.new_number(application=a)
        initial["fund"] = a.round.scheme.fund or models.Fund.last()
        if research_aims := a.file and a or a.documents.filter(document_type__role="AF").last():
            initial["research_aims"] = research_aims.file
        if project_timeline := a.documents.filter(document_type__role="PT").last():
            initial["project_timeline"] = project_timeline.file
        if proposal_budget := a.budget and a or a.documents.filter(document_type__role="B").last():
            initial["budget"] = initial["proposal_budget"] = a.budget or proposal_budget.file
        return initial

        # u = self.request.user
        # n = (
        #     models.Nomination.where(user=self.request.user, state="submitted")
        #     .order_by("-id")
        #     .first()
        # )
        # if n:
        #     initial["first_name"] = n.first_name or u.first_name
        #     initial["middle_names"] = n.middle_names or u.middle_names
        #     initial["last_name"] = n.last_name or u.last_name
        #     initial["title"] = n.title or u.title
        return initial


class ReportUpdate(
    LoginRequiredMixin,
    NotesMixin,
    SelfAssignMixin,
    ReportViewMixin,
    UserPassesTestMixin,
    UpdateWithInlinesView,
):

    model = models.Report
    form_class = forms.ReportForm
    permission_denied_message = _("Only the round panellist and staff can export the application")

    def get_permission_denied_message(self):
        o = self.get_object()
        return f"You have not permission to edit {o}"

    def test_func(self):
        u = self.request.user
        return u.is_admin or (o := self.get_object()) and o.can_edit(u)

    # def get_context_data(self, *args, **kwargs):
    #     context = super().get_context_data(*args, **kwargs)
    #     return context


class FileImportForm(Form):

    def __init__(self, label=None, allowed_extensions=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["file"] = FileField(
            label=label or _("File"),
            required=True,
            widget=widgets.ClearableFileInput(
                attrs={
                    "placeholder": _("Please upload a file ..."),
                    "data-placeholder": _("Please upload a file ..."),
                    "data-required": 1,
                    "oninvalid": "this.setCustomValidity('%s')"
                    % _("The file is required. Please upload a file ..."),
                    "oninput": "this.setCustomValidity('')",
                    "accept": (
                        ",".join(f".{e}" for e in allowed_extensions)
                        if allowed_extensions
                        else ".*"
                    ),
                }
            ),
            validators=allowed_extensions
            and [FileExtensionValidator(allowed_extensions=allowed_extensions)],
        )
        self.helper = FormHelper(self)
        self.helper.include_media = False
        self.helper.form_tag = False
        self.helper.layout = Layout("file")


class ReportRisImportForm(Form):
    file = FileField(
        label=_("RIS file"),
        required=True,
        widget=widgets.ClearableFileInput(
            attrs={
                "placeholder": _("Please upload a file ..."),
                "data-placeholder": _("Please upload a file ..."),
                "data-required": 1,
                "oninvalid": "this.setCustomValidity('%s')"
                % _("The file is required. Please upload a file ..."),
                "oninput": "this.setCustomValidity('')",
                "accept": ".ris",
            }
        ),
        validators=[FileExtensionValidator(allowed_extensions=["ris"])],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.include_media = False
        self.helper.form_tag = False
        self.helper.layout = Layout("file")


class FileImportView(LoginRequiredMixin, FormView):
    form_class = FileImportForm
    template_name = "portal/file_import_form.html"
    allowed_extensions = ["eml", "msg"]
    label = gettext_lazy("Message")
    model = models.Report

    def get_model(self):
        if model_name := self.request.GET.get("model"):
            if model_name in ["reportcomment", "report"]:
                return models.Report
            elif model_name in ["changerequest", "changerequestcomment"]:
                return models.ChangeRequest
            return models.Contract
        return self.model

    def get_success_url(self):
        if o := self.object:
            return o.get_absolute_url()
        if model_name := self.request.GET.get("model"):
            if model_name in ["reportcomment", "report"]:
                return reverse("report", kwargs=self.kwargs)
            elif model_name in ["changerequest", "changerequestcomment"]:
                return reverse("change-request", kwargs=self.kwargs)
            return reverse("contract", kwargs=self.kwargs)
        return reverse("report", kwargs=self.kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["allowed_extensions"] = self.allowed_extensions
        kwargs["label"] = self.label
        return kwargs

    @cached_property
    def is_modal(self):
        return (
            self.request.GET.get("_modal_dialog")
            or self.request.GET.get("_popup")
            or self.request.POST.get("_modal_dialog")
            or self.request.POST.get("_popup")
        )

    @property
    def object(self):
        model = self.get_model()
        if "pk" in self.kwargs:
            return get_object_or_404(model, pk=self.kwargs.get("pk"))

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        if self.is_modal:
            context["modal_dialog"] = True
        if model_name := self.request.GET.get("model"):
            context["model"] = model_name
        context["object"] = self.object
        return context

    def get_template_names(self):
        if self.is_modal:
            return ["partials/file_import_form.html"]
        return super().get_template_names()

    def form_valid(self, form):
        return super().form_valid(form)


class ReportRisImportView(FileImportView):
    # form_class = ReportRisImportForm
    form_class = FileImportForm
    template_name = "portal/ris_import_form.html"
    model = models.Report
    allowed_extensions = ["ris"]
    label = gettext_lazy("RIS file")

    def get_success_url(self):
        return reverse("report", kwargs=self.kwargs)

    @property
    def report(self):
        return get_object_or_404(self.model, pk=self.kwargs.get("pk"))

    def get_context_data(self, *args, **kwargs):
        assert self.kwargs.get("pk")
        context = super().get_context_data(*args, **kwargs)
        context["report"] = self.object
        return context

    def get_template_names(self):
        if self.request.GET.get("_modal_dialog") or self.request.GET.get("_popup"):
            return ["partials/ris_import_form.html"]
        return super().get_template_names()

    def form_valid(self, form):
        form.cleaned_data["file"].file.seek(0)
        report = self.object
        entries = rispy.loads(form.cleaned_data["file"].file.read().decode())
        with transaction.atomic():
            for e in entries:
                tor = e.get("type_of_reference")
                if tor:
                    rt, _ = models.RisPublicationType.get_or_create(
                        code=tor, defaults={"description": tor}
                    )
                    t = rt.type
                    if not t:
                        t, _ = models.PublicationType.get_or_create(
                            code=tor, defaults={"description": tor}
                        )
                        rt.type = t
                        rt.save(update_fields=["type"])
                else:
                    t = rt = None
                url = e.get("urls", [None])[0]
                p, created = models.Publication.get_or_create(
                    doi=e.get("doi"),
                    # rsnz_ref =
                    type=t,
                    ris_type=rt,
                    # status =
                    # status_date =
                    title=e.get("title"),
                    title2=e.get("secondary_title"),
                    # host =
                    # journal =
                    publisher=e.get("publisher"),
                    # editor =
                    # location = e.get("publisher"),
                    url=url,
                    volume=e.get("volume"),
                    year_ref=e.get("year"),
                    # page_ref =
                    # host_ref =
                    # citations =
                    # citations_date =
                    abstract=e.get("abstract"),
                    # uid =
                    # updated_at =
                    # impact_factor =
                    # impact_year =
                    # xcr =
                    # isi_loc =
                )
                if created:
                    if e.get("authors"):
                        models.PublicationAuthor.bulk_create(
                            [
                                models.PublicationAuthor(publication=p, name=n, type="PRIMARY")
                                for n in e.get("authors", [])
                            ]
                        )
                    if e.get("secondary_authors"):
                        models.PublicationAuthor.bulk_create(
                            [
                                models.PublicationAuthor(publication=p, name=n, type="SECONDARY")
                                for n in e.get("secondary_authors", [])
                            ]
                        )
                    if e.get("urls"):
                        models.PublicationLink.bulk_create(
                            [
                                models.PublicationLink(publication=p, link=l, type="URL")
                                for l in e.get("urls", [])
                            ]
                        )
                    if e.get("file_attachments1"):
                        models.PublicationLink.create(
                            publication=p, link=e.get("file_attachments1"), type="ATTAACHMENT"
                        )
                if not report.publications.contains(p):
                    report.publications.add(p)
            report.save()
        if self.request.GET.get("_modal_dialog") or self.request.POST.get("_modal_dialog"):
            return render(
                self.request, "partials/report_publication_list.html", {"report": report}
            )
        return super().form_valid(form)

    # def get_form(self, form_class=None):
    #     form = super().get_form(form_class=form_class)
    #     if not hasattr(form, "helper"):
    #         form.helper = FormHelper()
    #         form.layout = Layout("file")
    #     if not self.request.GET.get("_modal_dialog"):
    #         form.helper.layout.append(
    #             bootstrap.FormActions(
    #                 layout.Submit("import", "Import ..."),
    #                 layout.Button("cancel", "Cancel", css_class="btn btn-secondary"),
    #                 css_class="float-right",
    #             ),
    #         )
    #     return form


class EmailImportView(FileImportView):

    allowed_extensions = ["eml", "msg"]
    label = gettext_lazy("Message")
    model = models.Report
    extra_context = {"hx_target": "#comments"}

    def form_valid(self, form):

        file_field = form.cleaned_data["file"]
        file_name = file_field.name
        file_field.file.seek(0)
        o = self.object

        if reply_to := self.request.GET.get("reply_to"):
            reply_to = get_object_or_404(o.comments.model, pk=reply_to)
        try:
            o.import_email(
                file_field.file,
                filename=file_name,
                request=self.request,
                by=self.request.user,
                reply_to=reply_to,
            )
            messages_list = [
                messages.Message(
                    messages.constants.INFO, _(f"{file_name} was successfully imported...")
                )
            ]
        except Exception as ex:
            capture_exception(ex)
            messages_list = [
                messages.Message(
                    messages.constants.ERROR, _(f"Failed to import {file_name}: {ex}")
                )
            ]

        return render(
            self.request,
            "partials/comments.html",
            {"messages": messages_list, "comments": o.comments},
        )


class ReportExportView(ExportView):
    """Report PDF export view"""

    summary_template = "partials/report_summary.html"
    model = models.Report


class ChangeRequestExportView(ExportView):
    """ChangeRequest PDF export view"""

    model = models.ChangeRequest


class ProfileDetail(ProfileViewMixin, DetailView):
    template_name = "profile.html"
    raise_exception = True

    def post(self, request, *args, **kwargs):
        """Check the POST request call"""
        if "load_from_orcid" in request.POST:
            # for orcidhelper in self.orcid_data_helpers:
            #     count, user_has_linked_orcid = orcidhelper.fetch_and_load_orcid_data(request.user)
            #     total_records_fetched += count
            orcidhelper = OrcidHelper(request.user)
            total_records_fetched, user_has_linked_orcid = orcidhelper.fetch_and_load_orcid_data()
            if user_has_linked_orcid:
                messages.success(
                    self.request, f"{total_records_fetched} ORCID profile records imported"
                )
                return HttpResponseRedirect(self.request.path_info)
            else:
                messages.warning(
                    self.request,
                    _(
                        "In order to import ORCID profile, please, "
                        "link your ORCID account to your portal account."
                    ),
                )
                return redirect(
                    reverse("socialaccount_connections")
                    + "?next="
                    + quote(request.get_full_path())
                )

    def get_object(self):
        if "pk" in self.kwargs:
            p = super().get_object()
            u = self.request.user
            if u.is_staff or u.is_superuser or p.user == u or u.is_site_staff:
                return p
            raise PermissionDenied(_("You are not allowed to see this profile."))
        return self.request.user.person


class ProfileUpdate(ProfileViewMixin, LoginRequiredMixin, UpdateView):
    def get_object(self):
        return self.request.user.person


class ProfileCreate(ProfileViewMixin, CreateView):

    def form_valid(self, form):
        form.instance.user = self.request.user
        return super().form_valid(form)

    def get(self, request, *args, **kwargs):
        u = self.request.user
        if models.Person.where(user=u).exists():
            messages.error(self.request, _("The profile was aready created."))
            return redirect("profile-update")

        # Start profile wizard:
        if not request.session.get("wizard"):
            if request.site_id in [1, 7] and not request.session.get("scheme"):
                rounds = models.Round.where(scheme__current_round=F("pk")).order_by("ordering")
                return render(request, "preselect_scheme.html", locals())

            if not (
                request.site_id in [1, 7]
                and (code := request.session.get("scheme"))
                and (pk := request.session.get("round"))
                and (round := models.Round.where(pk=pk).first())
                and round.is_partial_profile_allowed
            ):
                self.request.session["wizard"] = True
                self.request.session["wizard-views"] = (
                    ProfileSectionFormSetView.section_views.copy()
                )
                self.request.session.modified = True

        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if (round_pk := request.POST.get("round")) and (
            round := models.Round.where(pk=round_pk).first()
        ):
            self.request.session["scheme"] = round.scheme.code or round.scheme.pk
            self.request.session["round"] = round.pk
            self.request.session.modified = True
            return redirect(request.path_info)

        return super().post(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)

        if "user_form" not in kwargs:
            kwargs["user_form"] = self.get_user_form()

        return data

    def get_initial(self):
        initial = super().get_initial()
        u = self.request.user
        n = (
            models.Nomination.where(
                Q(user=self.request.user)
                | Q(email__lower__in=u.emailaddress_set.values_list("email__lower")),
                state__in=["submitted", "sent", "bounced"],
            )
            .order_by("-id")
            .first()
        )
        if n:
            initial["first_name"] = n.first_name or u.first_name
            initial["middle_names"] = n.middle_names or u.middle_names
            initial["last_name"] = n.last_name or u.last_name
            initial["title"] = n.title or u.title
            initial["user"] = u
        return initial


# def send_mail(self, subject_template_name, email_template_name,
#                 context, from_email, to_email, html_email_template_name=None):
#     """
#     Send a django.core.mail.EmailMultiAlternatives to `to_email`.
#     """
#     subject = loader.render_to_string(subject_template_name, context)
#     # Email subject *must not* contain newlines
#     subject = ''.join(subject.splitlines())
#     body = loader.render_to_string(email_template_name, context)

#     email_message = EmailMultiAlternatives(subject, body, from_email, [to_email])
#     if html_email_template_name is not None:
#         html_email = loader.render_to_string(html_email_template_name, context)
#         email_message.attach_alternative(html_email, 'text/html')

#     email_message.send()


def invite_panellist(request, round):
    """Send invitations to all panellists."""
    count = 0
    panellist = list(
        models.Panellist.where(~Q(invitation__email__lower=Lower("email")) | Q(state__isnull=True))
    )
    for p in panellist:
        p.get_or_create_invitation(by=request and request.user)

    invitations = list(
        models.Invitation.where(
            ~Q(state="accepted"),
            round=round,
            panellist__in=panellist,
            type="P",
            sent_at__isnull=True,
        )
    )
    for i in invitations:
        i.send(request)
        i.save()
        count += 1
    return count


class InvitationCreate(CreateView):
    model = models.Invitation
    template_name = "form.html"
    # form_class = ProfileForm
    # exclude = ["organisation", "state", "submitted_at", "accepted_at", "expired_at"]
    fields = ["email", "first_name", "middle_names", "last_name", "org"]
    widgets = {"org": autocomplete.ModelSelect2("org-autocomplete")}
    labels = {"org": _("organisation")}

    def form_valid(self, form):
        u = self.request.user
        i = form.instance
        i.user = u
        if i.org:
            i.organisation = i.org.name
        if not i.inviter:
            i.inviter = u

        form.save()
        i.send(self.request, by=u)
        i.save()

        messages.success(self.request, _("An invitation was sent to ") + i.email)
        return redirect(self.get_success_url())

    def get_form_class(self):
        """Return the form class to use in this view."""
        return model_forms.modelform_factory(self.model, fields=self.fields, widgets=self.widgets)


# @login_required
# @shoud_be_onboarded
# @require_http_methods(["GET", "POST"])
# def profile_career_stages(request, pk=None):
#
#     if request.method == "GET":
#         queryset = ProfileCareerStage.objects.filter(profile=request.user.profile).order_by(
#             "year_achieved"
#         )
#         formset = ProfileCareerStageFormSet(queryset=queryset)
#     elif request.method == "POST":
#         formset = ProfileCareerStageFormSet(request.POST)
#         if formset.is_valid():
#             for form in formset.save(commit=False):
#                 if not hasattr(form, "profile") or not form.profile:
#                     form.profile = request.user.profile
#                 form.save()
#             # formset.save_m2m()
#             formset.save()
#     return render(
#         request,
#         "profile_section.html",
#         {"formset": formset, "helper": forms.ProfileSectionFormSetHelper()},
#     )


class MemberInline(InlineFormSetFactory):
    model = models.Member
    fields = ["first_name", "middle_names", "last_name", "email"]

    def delete_existing(self, obj, commit=True):
        if commit:
            for i in models.Invitation.where(member=obj):
                i.revoke(self.request)
                i.save()
            obj.delete()


class AuthorizationFormMixin:

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not hasattr(self, "helper"):
            self.helper = FormHelper(self)
            self.helper.include_media = False
        # self.helper.label_class = "offset-md-1 col-md-1"
        # self.helper.field_class = "col-md-8"
        if self.helper.inputs:
            self.helper.inputs.pop()
        if self.helper.inputs:
            self.helper.inputs.pop()

        self.helper.add_input(Submit("submit", _("I agree to be part of this team")))
        self.helper.add_input(
            Submit("turn_down", _("I decline the invitation"), css_class="btn-outline-danger")
        )


class AuthorizationForm(AuthorizationFormMixin, Form):
    pass


# class MemberAuthorizationForm(AuthorizationFormMixin, ModelForm):
class MemberAuthorizationForm(AuthorizationFormMixin, forms.MemberForm):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = kwargs.get("instance", None) or self.instance
        round = instance.application.round
        if round.member_research_experience_in_years_required:
            self.fields["research_experience_in_years"].required = True
        else:
            self.fields.pop("research_experience_in_years", None)

        if round.member_letter_of_support_required:
            self.fields["file"].required = True
        else:
            self.fields.pop("file", None)

        # self.fields["file"].required = True
        # self.fields["country"].required = True

    # def clean_is_accepted(self):
    #     """Allow only 'True'"""
    #     if not self.cleaned_data["is_accepted"]:
    #         raise forms.ValidationError("Please read and consent to the Privacy Policy")
    #     return True
    class Meta(forms.MemberForm.Meta):
        pass
        # fields = ["cv_file", "file", "country", "org", "research_experience_in_years"]
        # widgets = {
        #     "country": autocomplete.ModelSelect2(
        #         "country-autocomplete",
        #         # attrs={"data-placeholder": _("Choose your title or create a new one ...")},
        #         attrs={"data-required": 1},
        #     ),
        #     "org": autocomplete.ModelSelect2(
        #         "org-autocomplete",
        #         forward=["country"],
        #         attrs={
        #             "data-placeholder": _("Choose an organisation ..."),
        #             "placeholder": _("Choose an organisation ..."),
        #             "data-required": 1,
        #             "oninvalid": "this.setCustomValidity('%s')" % _("Organisation is required"),
        #             "oninput": "this.setCustomValidity('')",
        #         },
        #     ),
        #     "file": widgets.ClearableFileInput(
        #         attrs={
        #             "accept": ".pdf,.odt,.ott,.oth,.odm,.doc,.docx,.docm,.docb",
        #             "data-required": 1,
        #         },
        #     ),
        #     "cv_file": widgets.ClearableFileInput(
        #         attrs={
        #             "accept": ".pdf,.odt,.ott,.oth,.odm,.doc,.docx,.docm,.docb",
        #             "data-required": 1,
        #         },
        #     ),
        # }


class ApplicationDetail(FavoriteMixin, DetailView):

    model = Application
    template_name = "portal/application_detail.html"

    # def last_modified(self, request, *args, **kwargs):
    #     if (
    #         (o := self.get_object())
    #         and (u := request.user)
    #         and u.is_authenticated
    #         and hasattr(o, "updated_at")
    #     ):
    #         # return f"u.username:o.updated_at.strftime('%s')"
    #         return f"o.updated_at.strftime('%s')"

    def dispatch(self, request, *args, **kwargs):
        u = self.request.user
        if hasattr(self, "object"):
            a = getattr(self, "object", None)
        else:
            a = self.get_object()
            self.object = a
        if u.is_authenticated and not u.is_admin:
            if not a.user_can_view(u):
                messages.error(request, _("You do not have permissions to view this application."))
                return redirect(self.request.META.get("HTTP_REFERER", "index"))
        if a and "number" in kwargs and a.number != kwargs["number"]:
            url = request.build_absolute_uri(
                reverse("application-detail", kwargs={"number": a.number})
            )
            messages.warning(
                request,
                _(
                    "Application number <b>%(old_number)s</b>  has been changed to <b>%(number)s</b>. "
                    'Please further use <a href="%(url)s">%(url)s</a> to access the application.'
                )
                % {
                    "old_number": kwargs["number"],
                    "number": a.number,
                    "url": url,
                },
            )
            return redirect(url)
        return super().dispatch(request, *args, **kwargs)

    def get_member(self):
        """Returns the member entry related to the current user"""
        user = self.request.user
        return self.object.members.filter(
            Q(user=user)
            | Q(email__lower=user.email.lower())
            | Q(email__lower__in=user.emailaddress_set.values_list("email__lower"))
        ).last()

    # @method_decorator(condition(last_modified_func=last_modified))
    def get(self, request, *args, **kwargs):
        resp = super().get(request, *args, **kwargs)

        if (a := self.object) and (r := a.round) and r.survey_id:
            u = self.request.user
            referee = (
                a.referees.filter(
                    Q(user=u) | Q(email=u.email) | Q(email__in=u.email_addresses),
                    Q(application__round__testimonial_submission_closes_at__isnull=True)
                    | Q(application__round__testimonial_submission_closes_at__gt=timezone.now()),
                    survey_completed_at__isnull=True,
                )
                .order_by("-id")
                .first()
            )
            if referee and referee.state != "opted_out":
                survey_url = reverse("survey-referee", kwargs={"referee_id": referee.id})
                site = models.Site.objects.get_current()
                messages.info(
                    self.request,
                    (
                        f'<span class="badge badge-primary">{_("New")}</span> '
                        f"{_('You have a request to review a %s application to act on')}."
                        f"""<a href="{survey_url}" class="alert-link">
                        {_('Please click here to complete the referee report')}!
                    </a>"""
                    )
                    % site.name,
                )
        return resp

    @method_decorator(csrf_protect)
    def post(self, request, *args, **kwargs):
        if "save_tags" in request.POST and hasattr(self.model, "tags"):
            return super().post(request, *args, **kwargs)

        a = self.object = self.get_object()
        r = a.round
        u = request.user
        if (
            (action := request.POST.get("action"))
            and action == "turn_down"
            and (
                referee := (
                    models.Referee.get(referee_id)
                    if (referee_id := request.POST.get("referee_id"))
                    else a.referees.filter(user=u).last()
                )
            )
        ):
            referee.opt_out(
                request=request,
                by=u,
                description=request.POST.get("resolution", _("User opted out...")),
            )
            referee.save()
            reset_cache(request)
            return redirect("index")

        if member := self.get_member():
            if not member.user:
                member.user = u

            if "submit" in request.POST:
                form = self.get_member_form(instance=member)
                if form.is_valid():
                    member = form.save(commit=False)
                    member.authorize(request)
                    form.save(commit=True)
                else:
                    for e in form.errors:
                        messages.error(request, e)
                    return redirect(request.path)

                messages.info(
                    self.request,
                    _("Thank you for accepting the invitation."),
                )

            elif "turn_down" in request.POST:
                member.opt_out(request)
                member.save()

        elif action := request.POST.get("action"):
            if action == "cancel":
                self.object.cancel(request)
                self.object.save()
                messages.info(
                    self.request,
                    _("The application was cancelled. The applicant(s) were notified."),
                )
            elif action == "request_resubmission":
                self.object.request_resubmission(request)
                self.object.save()
                messages.info(
                    self.request,
                    _(
                        "The request to review and resubmit the application was sent to the applicant(s)."
                    ),
                )
            elif action == "approve":
                a = self.object
                if (
                    a.round.agent_declaration
                    and (is_declaration_accepted := request.POST.get("agent_declaration_accepted"))
                    and is_declaration_accepted not in ["on", "1", 1, True, "true"]
                ):
                    messages.error(
                        self.request,
                        _("You have to accept the <strong>Agent Declaration<strong>."),
                    )
                else:
                    a.approve(
                        request,
                        agent_declaration_accepted=request.POST.get("agent_declaration_accepted"),
                    )
                    a.save()

                if a.site_id in [2, 5]:
                    url = a.get_full_detail_url(request=request)
                    count = (
                        a.invite_referees(
                            request=request,
                            dispatch_invitations=(
                                a.site_id not in [2, 5]
                                or (
                                    a.site_id in [2, 5]
                                    and a.round.closes_at
                                    and a.round.closes_at <= timezone.now()
                                )
                            ),
                        )
                        or a.referees.filter(state__in=["sent"]).count()
                    )
                    if count and request:

                        closes_at = a.round.closes_at
                        if a.site_id not in [2, 5] or closes_at and closes_at <= timezone.now():
                            messages.info(
                                self.request,
                                _(
                                    f'The application <a href="{url}">{a}</a> '
                                    "has been successfully submitted to {count} referee(s) to review it."
                                ),
                            )
                        else:
                            messages.info(
                                self.request,
                                _(
                                    f"{count} referee invitation(s) were created. "
                                    "The invitation(s) will be sent to referees after the round closes."
                                ),
                            )
                else:
                    messages.info(
                        self.request,
                        _(
                            "The application was approved. The applicant(s) and administrator(s) were notified."
                        ),
                    )
            elif action == "accept":
                a = self.object
                if a.state != "accepted":
                    a.accept(request)
                    a.save()
                    messages.success(request, _("The application was successfully accepted"))
                else:
                    messages.warning(request, _("The application was already accepted"))

        return redirect(request.path)

    def get_member_form(self, instance=None, initial=None):
        if self.object and self.object.site_id == 2:
            u = self.request.user
            p = u.person
            initial = initial or {}
            if cv := models.CurriculumVitae.last_user_cv(u):
                initial["cv_file"] = cv.file
            if (
                not (instance and instance.country)
                and "country" not in initial
                and p.address
                and p.address.country
            ):
                initial["country"] = p.address.country
            if not (instance and instance.org) and (
                emp := p.affiliations.filter(type="EMP", end_date__isnull=True, org__isnull=False)
                .order_by("start_date")
                .last()
            ):
                initial["org"] = emp.org
            if (
                pm := models.Member.where(user=u, research_experience_in_years__isnull=False)
                .order_by("-created_at")
                .first()
            ):
                year = timezone.now().year
                initial["research_experience_in_years"] = pm.research_experience_in_years + (
                    year - pm.created_at.year
                )

            return MemberAuthorizationForm(
                self.request.POST or None,
                self.request.FILES or None,
                instance=instance,
                initial=initial,
            )
        return AuthorizationForm()

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)

        a = context["application"] = self.object
        r = a.round
        site_id = a.site_id
        u = self.request.user
        referee = a.referees.filter(
            Q(user=u) | Q(email__lower__in=u.emailaddress_set.values_list("email__lower"))
        ).last()
        if a and site_id in [2, 5]:
            if referee or u.is_admin:
                # context["documents"] = list(
                qs = a.documents.filter(~Q(file=""), file__isnull=False).order_by(
                    "required_document__ordering"
                )
                if referee:
                    qs = qs.filter(required_document__referees_can_access=True)
                context["attachments"] = list(qs)
                context["required_documents"] = (
                    r.required_documents.filter(referees_can_access=True)
                    if referee
                    else r.required_documents.all()
                ).order_by("ordering")
            else:
                context["documents"] = a.user_documents_dict(self.request.user)
        if n := models.Nomination.where(application=a).last():
            context["nomination"] = n
            context["nominator"] = n.nominator
        if m := a.members.filter(
            Q(user=u)
            | Q(email__lower=u.email.lower())
            | Q(email__lower__in=u.emailaddress_set.values_list("email__lower")),
            # has_authorized__isnull=True,
            Q(state__isnull=True) | ~Q(state__in=["authorized", "opted_out"]),
        ).first():
            messages.info(
                self.request,
                _("Please review the application and authorize your team representative."),
            )
            if a.site_id == 2:
                messages.warning(
                    self.request,
                    _(
                        "Please upload the host support letter and the current CV, "
                        "and indicate the county of the origin."
                    ),
                )

            country = m.country_id or self.request.session.get("country")
            initial = country and {"country": country} or {}
            if cv := models.CurriculumVitae.last_user_cv(u, cut_off_months=a.site == 2 and 3):
                initial["cv_file"] = cv.file
            p = u and u.person
            if not m.title:
                initial["title"] = u.title or p.title
            if not m.first_name:
                initial["first_name"] = u.first_name or p and p.first_name
            if not m.middle_names:
                initial["middle_names"] = u.middle_names or p and p.middle_names
            if not m.last_name:
                initial["last_name"] = u.last_name or p and p.last_name

            context["form"] = self.get_member_form(instance=m, initial=initial)
            context["cv_upload_required"] = True
        is_ro = site_id in [2, 4, 5] and (
            n
            and (n.nominator == u or n.org and n.org.where(research_offices__user=u).exists())
            or a.org.where(research_offices__user=u).exists()
        )
        is_owner = (
            a.submitted_by == u or a.members.filter(user=u, state="authorized").exists() or is_ro
        )
        is_referee = (
            not is_ro
            and not is_owner
            and a.referees.filter(
                Q(user=u) | Q(email__lower__in=u.emailaddress_set.values_list("email__lower"))
            ).exists()
        )

        if site_id in [2, 5] and not is_ro and is_owner and a.state in ["in_review", "submitted"]:
            context["update_button_name"] = _("Edit referee list")
        if p := r.panellists.filter(user=u).first():
            context["is_panellist"] = True
            coi = p.conflict_of_interests.filter(Q(application=a)).last()
            context["has_coi"] = not coi or coi.has_conflict is True or coi.has_conflict is None
            context["evaluation"] = models.Evaluation.where(panellist=p, application=a).last()

        context["is_owner"] = is_owner
        can_only_update_referees = context["can_only_update_referees"] = (
            not is_referee and site_id not in [1, 7] and (a.can_only_update_referees(u))
        )

        if (
            is_owner
            and not r.is_open
            and (current_round := r.scheme.current_round)
            and current_round != r
            and current_round.is_open
            and not Application.user_applications(
                user=u, round=current_round, request=self.request
            ).exists()
        ):
            context["can_reenter"] = True
            context["current_round"] = current_round

        if for_panellists := self.request.GET.get("for_panellists", False):
            context["for_panellists"] = for_panellists

        if is_owner or is_ro or u.is_admin:
            if site_id in [2, 5] and for_panellists:
                referees = a.referees.order_by("testified_at")
                if r.required_referees:
                    referees = referees[: r.required_referee]
                context["referees"] = referees
            else:
                context["referees"] = a.referees.all()

        context["was_submitted"] = a.state in [
            "submitted",
            "approved",
            "cancelled",
            "accepted",
            "funded",
        ]
        context["can_update"] = (
            can_only_update_referees
            or (
                site_id not in [2, 5]
                and a.state not in ["submitted", "approved", "cancelled", "accepted"]
            )
            or (site_id in [2, 5] and is_ro and a.state in ["submitted", "new", "draft"])
            or (
                site_id in [2, 5]
                and is_owner
                and a.state in ["new", "submitted", "draft", "in_review"]
            )
        )

        testimonial_submission_closes_at = r.testimonial_submission_closes_at
        if testimonial_submission_closes_at and testimonial_submission_closes_at < timezone.now():
            context["reviewing_closed"] = True
        if not is_owner:
            context["show_basic_details"] = not (
                u.is_admin
                or is_ro
                or (site_id not in [2, 4, 5] and a.referees.filter(user=u).exists())
                or r.panellists.filter(user=u).exists()
                # or models.ConflictOfInterest.where(
                #     Q(has_conflict=False) | Q(has_conflict__isnull=False),
                #     application=a,
                #     panellist__user=u,
                # ).exists()
                or a.org.where(research_offices__user=u).exists()
            )
            if referee := a.referees.filter(
                Q(user=u)
                | Q(
                    email__lower__in=u.emailaddress_set.values_list("email__lower")
                )  ## , ~Q(state="opted_out")
            ).last():
                context["referee"] = referee
                can_change_testimonial = referee.state not in ["opted_out", "testified"]
                if site_id in [2, 5]:
                    context["export_enabled"] = can_change_testimonial
                context["can_decline"] = can_change_testimonial
                if t := models.Testimonial.where(referee=referee).order_by("-pk").first():
                    context["testimonial"] = t
                    if t.state != "submitted":
                        closes_at = r.closes_at
                        if (
                            testimonial_submission_closes_at
                            and testimonial_submission_closes_at < timezone.now()
                        ):
                            messages.warning(
                                self.request,
                                mark_safe(
                                    _(
                                        "The referee report submission was closed on "
                                        f"<b>{testimonial_submission_closes_at.date().isoformat()}</b> "
                                        f"at <b>{testimonial_submission_closes_at.time()}</b>."
                                    )
                                ),
                            )
                        elif (
                            site_id not in [2, 5]
                            or (closes_at and closes_at <= timezone.now())
                            or a.state == "in_review"
                        ) and referee.state != "opted_out":
                            messages.info(
                                self.request,
                                (
                                    _(
                                        "Please review the application details and submit referee report."
                                    )
                                    if site_id in [2, 4, 5]
                                    else _(
                                        "Please review the application details and submit testimonial."
                                    )
                                ),
                            )
                        else:
                            context["reviewing_disabled"] = True
                            if closes_at and closes_at < timezone.now():
                                closes_at_date = closes_at and closes_at.date().isoformat()
                                messages.warning(
                                    self.request,
                                    _(
                                        "The application reviewing will be open after the application "
                                        f"submission is closed (on <b>{closes_at_date}</b>)."
                                    ),
                                )
                            elif a.state not in ["submitted", "in_review"]:
                                messages.warning(
                                    self.request,
                                    _(
                                        "The application reviewing will be open after the application submission is closed."
                                    ),
                                )

        # context["tag_form"] = self.tag_form()

        return context


class ItemFormSetView(ModelFormSetView):

    model = models.Referee
    # fields = ['name', 'sku', 'price']
    # template_name = 'item_formset.html'


@login_required
@require_http_methods(["DELETE"])
def delete_object(request, model, pk):
    messages_list = []
    model = apps.all_models["portal"].get(model)
    if model and (o := pk and get_object_or_404(model, pk=pk)):
        try:
            if i := getattr(o, "invitation", None):
                i.revoke(request, by=request.user)
                i.save()
                messages_list.append(
                    messages.Message(
                        messages.constants.INFO, _(f"The invitation {i} was revoked.")
                    )
                )
            o.delete()
        except Exception as ex:
            # messages_list.append(messages.Message(messages.constants.ERROR, str(ex)))
            return render(
                request,
                "partials/messages.html",
                {"messages": [messages.Message(messages.constants.ERROR, str(ex))]},
            )
        name = o._meta.verbose_name.title()
        messages_list.append(
            messages.Message(messages.constants.INFO, _(f"{name} {o} was successfully deleted"))
        )
        return render(request, "partials/messages.html", {"messages": messages_list})
    # raise Http404(f"No matches the given query - mode: {model}, PK: {pk}")
    return render(
        request,
        "partials/messages.html",
        {
            "messages": [
                messages.Message(
                    messages.constants.ERROR,
                    f"No matches the given query - mode: {model}, PK: {pk}",
                )
            ]
        },
    )


@login_required
@require_http_methods(["DELETE"])
def delete_referee(request, pk):
    if r := pk and models.Referee.where(pk=pk).first():
        return HttpResponse(
            f"""<div class="alert alert-success">Referee {r.full_name_with_email} successfully deleted
    <button type="button" class="close" data-dismiss="alert" aria-label="Close">
        <span aria-hidden="true">×</span>
    </button></div>
    """
        )
    return HttpResponse("""
    <div class="alert alert-success">TODO:<button type="button" class="close" data-dismiss="alert" aria-label="Close"><span aria-hidden="true">×</span></button></div>
    """)


class ApplicationView(LoginRequiredMixin, NotesMixin, SingleObjectMixin):
    model = Application
    form_class = forms.ApplicationForm

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)
        if self.update_only_referees():
            messages.info(
                request,
                _("You can only modify the referee list."),
            )
        return response

    # def form_invalid(self, form):
    #     return super().form_invalid(form)

    def update_only_referees(self, application=None, user=None):
        if not application:
            application = self.object
        if not user:
            user = self.request.user
        return bool(user and application and application.can_only_update_referees(user))

    @cached_property
    def previous_application(self):
        user = self.request.user
        if "previous" in self.request.GET:
            pa = models.Application.all_objects.filter(
                pk=int(self.request.GET.get("previous"))
            ).first()
            if pa and (pa.submitted_by == user or user in pa.members.all()):
                return pa
            raise PermissionDenied(
                _("You do not have permission to access the source application.")
            )

    @cached_property
    def latest_application(self):
        if pa := self.previous_application:
            return pa
        if (r := self.round) and (
            pa := self.model.where(submitted_by=self.request.user, round__scheme=r.scheme)
            .order_by("-pk")
            .first()
        ):
            return pa
        return (
            models.Application.all_objects.filter(submitted_by=self.request.user)
            .order_by("-pk")
            .first()
        )

    def dispatch(self, request, *args, **kwargs):
        u = request.user
        if u.is_authenticated and not u.is_admin:
            if (pk := self.kwargs.get("pk")) and (
                a := get_object_or_404(models.Application, pk=pk)
            ):
                r = a.round
                if not (
                    a.is_applicant(u)
                    or (a.site_id in [2, 4, 5] and a.org.where(research_offices__user=u).exists())
                ):
                    messages.error(
                        request, _("You do not have permissions to edit this application.")
                    )
                    return redirect("application", pk=pk)

                if a.members.filter(
                    ~Q(state="authorized"),
                    Q(user=u) | Q(email__in=u.email_addresses),
                ).exists():
                    messages.warning(
                        request,
                        _(
                            "You have not yet reviewed the application and "
                            "have not authorized your team representative."
                        ),
                    )
                    return redirect("application", pk=pk)

                if a.state and (
                    a.site_id not in [2, 5]
                    and (
                        a.state not in ["new", "draft", "in_review"]
                        or (
                            a.state not in ["new", "draft", "in_review", "submited"]
                            and not models.Nomination.where(
                                Q(org__research_offices__user=u) | Q(nominator=u), application=a
                            ).exists()
                        )
                    )
                ):
                    messages.error(
                        request,
                        _(
                            "The application has been already submitted. "
                            "You cannot modify a submitted application."
                        ),
                    )
                    return redirect("application-detail", number=a.number)
                if (
                    not r.is_open
                    and r.closes_at < timezone.now()
                    and not (
                        a.site_id == 5
                        and a.state == "in_review"
                        and a.org
                        and (a.pi == u or a.org.is_ro(u))
                    )
                ):
                    messages.error(
                        request,
                        _(
                            "The application period has closed. "
                            "You cannot longer modify this application."
                        ),
                    )
                    return redirect("application-detail", number=a.number)
                elif (
                    not r.is_open
                    and r.testimonial_submission_closes_at
                    and r.testimonial_submission_closes_at < timezone.now()
                ):
                    messages.error(
                        request,
                        (
                            _(
                                "The referee report period has closed. "
                                "You cannot longer modify this application."
                            )
                            if a.site_id == 5
                            else _(
                                "The application period has closed. "
                                "You cannot longer modify this application."
                            )
                        ),
                    )
                    return redirect("application-detail", number=a.number)
                if r.survey_id:
                    referee = (
                        a.referees.filter(
                            Q(user=u) | Q(email=u.email) | Q(email__in=u.email_addresses),
                            survey_completed_at__isnull=True,
                        )
                        .order_by("-id")
                        .first()
                    )
                    if referee:
                        survey_url = reverse("survey-referee", kwargs={"referee_id": referee.id})
                        site = models.Site.objects.get_current()
                        messages.info(
                            self.request,
                            (
                                f'<span class="badge badge-primary">{_("New")}</span>'
                                f"{_('You have a request to review a %s application to act on')}."
                                f"""<a href="{survey_url}" class="alert-link">
                                {_('Please click here to complete the referee report')}!
                            </a>"""
                            )
                            % site.name,
                        )
        return super().dispatch(request, *args, **kwargs)

    def continue_url(self, fragment=None):
        if self.object and self.object.pk:
            url = reverse("application-update", kwargs=dict(pk=self.object.pk))
        else:
            url = self.request.path_info.split("?")[0]
        if fragment:
            url = f"{url}#{fragment}"
        return url

    def get_initial(self):
        user = self.request.user
        initial = super().get_initial()
        initial["round"] = self.round.pk
        round = self.round
        nomination = self.nomination
        if round.letter_of_support_required or round.member_letter_of_support_required:
            if (
                has_required_documents := round.required_documents.count() > 0
            ) and not round.required_documents.filter(role="HS").exists():
                round.required_documents.create(
                    role="HS",
                    format="T",
                    title_en="Host Support Letter",
                    title="Host Support Letter",
                    is_optional=False,
                    referees_can_access=False,
                    panellists_can_access=True,
                    exclude=False,
                )

            elif (
                self.object
                and self.object.letter_of_support
                and self.object.letter_of_support.file
            ):
                initial["letter_of_support_file"] = self.object.letter_of_support.file

        if (
            round.is_applicant_cv_required
            and round.curriculum_vitae_templates.count() > 0
            and self.object
            and self.object.id
            and self.object.cv
            and self.object.cv.file
        ):
            initial["cv_file"] = self.object.cv.file

        if not (self.object and self.object.id):
            initial["user"] = user
            initial["email"] = user.email
            initial["language"] = django.utils.translation.get_language()
            current_affiliation = (
                models.Affiliation.where(person=user.person, end_date__isnull=True)
                .order_by("-start_date")
                .first()
            )
            latest_application = self.latest_application
            if address := user.person.address:
                initial["address"] = address
                initial["postal_address"] = address.address
                initial["city"] = address.city
                initial["postcode"] = address.postcode
            if (
                round.research_experience_in_years_required
                or round.member_research_experience_in_years_required
            ):
                research_experience_in_years = (
                    latest_application
                    and latest_application.research_experience_in_years
                    and latest_application.research_experience_in_years + 1
                )
                if not research_experience_in_years and (
                    pa_with_experience_in_years := Application.where(
                        submitted_by=user, research_experience_in_years__isnull=False
                    )
                    .order_by("-id")
                    .first()
                ):
                    research_experience_in_years = (
                        pa_with_experience_in_years.research_experience_in_years + 1
                    )
                if not research_experience_in_years and (
                    ar := models.AcademicRecord.where(
                        person__user=user,
                        start_year__isnull=False,
                        qualification__in=Subquery(
                            models.Qualification.where(description__icontains="phd").values("id")
                        ),
                    )
                    .order_by("start_year")
                    .first()
                ):
                    research_experience_in_years = timezone.now().year - ar.start_year
                if not research_experience_in_years and (
                    pcs := PersonCareerStage.where(
                        ~Q(career_stage__code="R9"),
                        person__user=user,
                        year_achieved__isnull=False,
                    )
                    .order_by("year_achieved")
                    .first()
                ):
                    research_experience_in_years = timezone.now().year - pcs.year_achieved

                if research_experience_in_years:
                    initial["research_experience_in_years"] = research_experience_in_years

            application_with_title = (
                self.model.all_objects.filter(submitted_by=user, title__isnull=False)
                .order_by("-pk")
                .first()
            )
            initial.update(
                {
                    "title": user.title or nomination and nomination.title,
                    # "email": user.email or nomination and nomination.email,
                    "first_name": user.first_name
                    or nomination
                    and nomination.first_name
                    or application_with_title
                    and application_with_title.first_name,
                    "last_name": user.last_name
                    or nomination
                    and nomination.last_name
                    or application_with_title
                    and application_with_title.last_name,
                    "middle_names": user.middle_names
                    or nomination
                    and nomination.middle_names
                    or application_with_title
                    and application_with_title.middle_names,
                }
            )

            if org := (
                initial.get("org")
                or nomination
                and nomination.org
                or current_affiliation
                and current_affiliation.org
                or latest_application
                and latest_application.org
            ):
                initial["org"] = org
                initial["organisation"] = org.name

            if (
                position := current_affiliation
                and current_affiliation.role
                or nomination
                and nomination.position
                or latest_application
                and latest_application.position
            ):
                initial["position"] = position

            if not address and org:
                if address := org.address:
                    initial["address"] = address
                    initial["postal_address"] = address.address
                    initial["city"] = address.city
                    initial["postcode"] = address.postcode

            if latest_application:
                if not address:
                    if latest_application_address := latest_application.address:
                        initial["address"] = latest_application_address
                        initial["postal_address"] = latest_application_address.address
                        initial["city"] = latest_application_address.city
                        initial["postcode"] = latest_application_address.postcode
                    else:
                        initial["postal_address"] = latest_application.postal_address
                        initial["city"] = latest_application.city
                        initial["postcode"] = latest_application.postcode
                initial["daytime_phone"] = latest_application.daytime_phone
                initial["mobile_phone"] = latest_application.mobile_phone

                initial["is_bilingual"] = latest_application.is_bilingual
                initial["summary_en"] = latest_application.summary_en
                initial["summary_mi"] = latest_application.summary_mi
                initial["summary"] = latest_application.summary
                if latest_application.file and latest_application.round.scheme == round.scheme:
                    initial["file"] = latest_application.file
                initial["letter_of_support_required"] = latest_application.letter_of_support
                if (
                    round.applicant_cv_required
                    and latest_application.cv
                    and latest_application.cv.file
                    and round.curriculum_vitae_templates.count() > 0
                ):
                    initial["cv_file"] = latest_application.cv.file
                if latest_application.is_team_application:
                    initial["is_team_application"] = latest_application.is_team_application
                    initial["team_name"] = latest_application.team_name
                    initial["members"] = latest_application.members
                initial["presentation_url"] = latest_application.presentation_url

        if ((o := self.object) and o.site_id == 2 and (not o.pk or o.is_pi(user))) or (
            not self.object and settings.SITE_ID == 2
        ):
            if cv := models.CurriculumVitae.last_user_cv(user=user, cut_off_months=3):
                initial["cv_file"] = cv.file

            if self.request.method == "GET" and (not o or o.pk and not o.cv):
                message = _(
                    "Please ensure that you have attached "
                    "to the application the most recent C.V."
                )

                if cv:
                    message = f"""{message}
                    {_('''Make suer that the select C.V.
                <a href="%s" target="_blank">%s</a>
                from your profile is up-to-date.''')}""" % (
                        cv.file.url,
                        os.path.basename(cv.file.name),
                    )
                messages.warning(self.request, message)

        return initial

    @property
    def round(self):
        if "nomination" in self.kwargs:
            return self.nomination.round
        return (
            models.Round.get(self.kwargs["round"]) if "round" in self.kwargs else self.object.round
        )

    @cached_property
    def nomination(self):
        if "nomination" in self.kwargs:
            return models.Nomination.get(self.kwargs["nomination"])
        elif (
            n := models.Nomination.where(
                user=self.request.user, round=self.round, state="accepted"
            ).last()
            or models.Nomination.where(
                email__lower__in=self.request.user.emailaddress_set.values_list("email__lower"),
                round__scheme__current_round=F("round"),
            )
            .order_by("-id")
            .first()
        ):
            return n

    # def form_invalid(self, form):
    #     return super().form_invalid(form)

    def form_valid(self, form):
        instance = form.instance or self.object
        current_state = instance and instance.state
        # if not instance.pk:
        #     resp = super().form_valid(form)

        context = self.get_context_data()
        referees = context["referees"]
        user = self.request.user
        reset_cache(self.request)
        # url = self.request.path_info
        url = None
        round = self.round
        has_required_documents = round.required_documents.count() > 0
        site_id = self.request.site_id
        update_url = None
        update_only_referees = self.update_only_referees()
        cv = None
        letter_of_support = None
        request = self.request
        try:
            with transaction.atomic():
                # if instance and instance.state != "in_review":
                if not instance.organisation and instance.org:
                    instance.organisation = instance.org.name
                if not instance.email:
                    instance.email = user.email

                resp = super().form_valid(form)

                if (
                    round.letter_of_support_required
                    and (letter_of_support_file := request.FILES.get("letter_of_support_file"))
                    and (
                        "letter_of_support_file" in form.changed_data
                        or not instance.letter_of_support
                    )
                ):
                    letter_of_support = models.LetterOfSupport.create(file=letter_of_support_file)
                    instance.letter_of_support = letter_of_support
                    # if letter_of_support_file.name.endswith(".pdf")

                # Handle CV
                if (
                    not update_only_referees
                    and (round.applicant_cv_required or site_id == 2)
                    and (cv_file := request.FILES.get("cv_file"))
                    and (
                        "cv_file" in form.changed_data
                        or not instance
                        or not instance.cv
                        or (
                            instance.is_team_application
                            and (
                                not instance.pk
                                or instance.members.filter(role="PI", cv__isnull=True).exists()
                            )
                        )
                    )
                ):
                    cv, created = models.CurriculumVitae.get_or_create(
                        owner=user,
                        person=user.person,
                        title=_(f"For application {instance.number}"),
                        defaults={"file": cv_file},
                    )
                    if not created and "cv_file" in form.changed_data:
                        cv.file.save(cv_file.name, cv_file)
                        cv.save()
                    instance.cv = cv

                    if created or ("cv_file" in form.changed_data):
                        if cv.file and cv.converted_file:
                            cv.converted_file.delete()
                            cv.converted_file = None
                            if hasattr(cv, "page_count"):
                                cv.page_count = None
                        cv.update_converted_file(commit=True, request=request)

                if (
                    "file" in form.changed_data
                    and instance.id
                    and instance.file
                    and instance.converted_file
                ):
                    instance.converted_file.delete()
                    instance.converted_file = None
                    if hasattr(instance, "page_count"):
                        instance.page_count = None

                check_selected_orgs(self.request)
                has_deleted = False
                a = form.instance or self.object
                # dispatch invitation to the referees or defer until the application round is closed
                dispatch_invitations = site_id not in [2, 5] or (
                    instance.state in ["approved", "accepted", "in_review"]
                    and round.closes_at
                    and round.closes_at <= timezone.now()
                )
                update_url = a and a.pk and reverse("application-update", kwargs=dict(pk=a.pk))

                if a.is_team_application and not update_only_referees:
                    members = context["members"]
                    has_deleted = bool(members.deleted_forms)
                    if has_deleted:
                        # url = self.request.path_info + "?members=1"
                        # url = self.request.path_info.split("?")[0] + "#application"
                        url = self.continue_url("application")
                    if members.is_valid():
                        # members.instance = a
                        members.save()
                        invitations = a.invite_team_members(self.request)
                        count = invitations and len(invitations) or 0
                        email_list = natural_item_list([i.email for i in invitations])
                        if count > 0:
                            messages.success(
                                self.request,
                                _(
                                    f"{count} invitation(s) to join the team have been sent: {email_list}."
                                ),
                            )
                    else:
                        for f in members.forms:
                            if not f.is_valid():
                                form.errors.update(f.errors)
                                url = self.continue_url("application")
                                raise ValidationError(_("Invalid member form"))

                    if has_deleted:
                        return redirect(f"{update_url or url}#applicant")

                    # if letter_of_support_file.name.endswith(".pdf")

                # if identity_verification_form := context.get("identity_verification"):
                #     identity_verification_form.instance.application = a
                #     if identity_verification_form.is_valid():

                if (
                    has_required_documents
                    and not update_only_referees
                    and (documents := context.get("documents"))
                ):
                    if not documents.instance or not documents.instance.id:
                        documents.instance = a
                    if documents.is_valid():
                        documents.save()
                        for f in documents.forms:
                            if (
                                "file" in f.changed_data
                                and f.instance.file
                                and f.instance.file.path
                            ):
                                f.instance.page_count = None
                                try:
                                    cf = f.instance.update_converted_file(
                                        commit=True, request=request
                                    )
                                except:
                                    url = (
                                        f"{update_url}#documents"
                                        if update_url
                                        else self.continue_url("documents")
                                    )

                    else:
                        if update_url:
                            if documents.errors:
                                for form_errors in documents.errors:
                                    if form_errors and "file" in form_errors:
                                        message = form_errors["file"]
                                        if isinstance(message, list) and message:
                                            message = message[0]
                                        messages.error(self.request, message)
                            return redirect(f"{update_url}#documents")
                        if documents.errors:
                            for form_errors in documents.errors:
                                form.errors.update(form_errors)
                        form.active_tab = "documents"
                        return self.form_invalid(form)

                if a.is_team_application and not update_only_referees:

                    if not letter_of_support and round.member_letter_of_support_required:
                        letter_of_support = a.documents.filter(
                            required_document__role="HS"
                        ).first()
                    pi, created = a.members.model.get_or_create(
                        application=a,
                        email=(
                            user.email
                            if not a.submitted_by or a.submitted_by == user
                            else a.submitted_by.email
                        ),
                        role_id="PI",
                        defaults=dict(
                            user=user,
                            cv=cv,
                            file=letter_of_support and letter_of_support.file,
                            converted_file=letter_of_support and letter_of_support.converted_file,
                            first_name=a.first_name or user.first_name or user.person.first_name,
                            middle_names=a.middle_names
                            or user.middle_names
                            or user.person.middle_names,
                            last_name=a.last_name or user.last_name or user.person.last_name,
                            org=a.org,
                            country_id=a.org.address
                            and a.org.address.country_id
                            or request.session.get("country"),
                            state="authorized",
                            research_experience_in_years=a.research_experience_in_years,
                            authorized_at=a.updated_at,
                            role_description="The submitter of the application",
                        ),
                    )

                    if not created:

                        updated = False

                        if any(
                            fn in form.changed_data
                            for fn in [
                                "first_name",
                                "middle_names",
                                "last_name",
                                "org",
                                "research_experience_in_years",
                            ]
                        ):

                            pi.org = a.org or pi.org
                            pi.country_id = (
                                a.org.address
                                and a.org.address.country_id
                                or request.session.get("country")
                                or pi.country_id
                            )
                            pi.first_name = a.first_name
                            pi.last_name = a.last_name
                            pi.middle_names = a.middle_names
                            pi.research_experience_in_years = (
                                a.research_experience_in_years or pi.research_experience_in_years
                            )

                            updated = True

                        if cv and (not pi.cv or pi.cv.updated_at < cv.updated_at):
                            pi.cv = cv
                            updated = True

                        if letter_of_support and pi.updated_at < letter_of_support.updated_at:
                            pi.file = letter_of_support.file
                            pi.converted_file = letter_of_support.converted_file
                            updated = True

                        if updated:
                            pi.save()

                try:
                    if not referees.instance or not referees.instance.pk:
                        referees.instance = a
                    if referees.is_valid():
                        # referees.instance = a
                        has_deleted = bool(has_deleted or referees.deleted_forms)
                        if has_deleted or "send_invitations" in self.request.POST:
                            url = self.continue_url("referees")

                        for df in referees.deleted_forms:
                            referee = df.instance
                            if referee and referee.pk:
                                for i in models.Invitation.where(models.Q(referee=referee)):
                                    i.revoke(self.request)
                                    i.save()

                        referees.save()
                        if (
                            not (
                                a.file
                                or site_id in [2, 4, 5]
                                and (
                                    (
                                        not has_required_documents
                                        or a.documents.filter(
                                            ~Q(file=""), document_type__role="AF"
                                        ).exists()
                                    )
                                    or (
                                        not round.research_summary_required
                                        or a.summary
                                        or a.summary_en
                                        or a.summary_mi
                                    )
                                )
                            )
                            and a.referees.count()
                        ):
                            if site_id in [2, 5]:
                                messages.info(
                                    self.request,
                                    _(
                                        "The invitation(s) to referee(s) will be sent after "
                                        "you upload the application form and submit it for reviewing to your research office."
                                    ),
                                )
                            else:
                                messages.info(
                                    self.request,
                                    _(
                                        "The invitation(s) to referee(s) will be sent after "
                                        "you upload the application form."
                                    ),
                                )

                            if has_deleted:
                                count = a.invite_referees(
                                    request=self.request, dispatch_invitations=dispatch_invitations
                                )
                                if count > 0 and dispatch_invitations:
                                    messages.success(
                                        self.request,
                                        _("%d referee invitation(s) sent.") % count,
                                    )
                                url = self.continue_url("referees")
                                return redirect(url)
                    else:
                        for f in referees.forms:
                            if not f.is_valid():
                                form.errors.update(f.errors)
                                # if not a.file:
                                #     url = self.continue_url("summary")
                                #     messages.error(
                                #         self.request,
                                #         "Before inviting referees, please upload a completed application form.",
                                #         # "Please upload a new application form or remove the referees.",
                                #     )
                                #     raise ValidationError(_("Missing application form file"))
                                # else:
                                #     url = self.continue_url("referees")
                                url = self.continue_url("referees")
                                raise ValidationError(f"Invalid referee form: {f.errors}")

                    if referees and referees.is_valid():
                        referee_emails = sorted(
                            [
                                f.cleaned_data.get("email")
                                for f in referees.forms
                                if f.cleaned_data.get("email")
                                and f.cleaned_data.get("email").strip()
                            ]
                        )
                        duplicate_referee_emails = [
                            e for e in set(referee_emails) if referee_emails.count(e) > 1
                        ]
                        if duplicate_referee_emails:
                            duplicate_referee_emails = ", ".join(duplicate_referee_emails)
                            messages.error(
                                self.request,
                                _(
                                    "Referee email list is not unique. "
                                    f"There are duplicate entry/entries: {duplicate_referee_emails}. "
                                    "Please remove duplicates and amend the list."
                                ),
                            )
                            if update_url:
                                return redirect(f"{update_url}#referees")
                            form.active_tab = "referees"
                            return self.form_invalid(form)

                except Exception as e:
                    capture_exception(e)
                    messages.error(self.request, str(e))
                    if update_url:
                        return redirect(update_url)
                    return self.form_invalid(form)

                if (
                    not update_only_referees
                    and "photo_identity" in form.changed_data
                    and instance.photo_identity
                ):
                    iv, created = models.IdentityVerification.get_or_create(
                        application=instance,
                        user=self.request.user,
                        defaults=dict(file=instance.photo_identity),
                    )
                    if not created:
                        iv.file = instance.photo_identity
                        iv.resolution = ""
                    iv.send(self.request)
                    messages.info(
                        self.request,
                        _("An identity verification request sent to the administration."),
                    )
                    iv.save()

                if not update_only_referees and (
                    ethics_statement_form := context.get("ethics_statement")
                ):
                    ethics_statement_form.instance.application = a
                    if ethics_statement_form.is_valid():
                        ethics_statement_form.save()

                if not update_only_referees and round.has_fors:
                    fors = context["fors"]
                    if not fors.instance or not fors.instance.id:
                        fors.instance = a
                    if fors.is_valid():
                        fors.save()
                    else:
                        for f in fors.forms:
                            if not f.is_valid():
                                # form.errors.update(f.errors)
                                if "__all__" in f.errors:
                                    messages.error(self.request, f.errors["__all__"])

                        if update_url:
                            return redirect(f"{update_url}#categories")
                        return self.form_invalid(form)

                if not update_only_referees and round.has_seos:
                    seos = context["seos"]
                    if not seos.instance or not seos.instance.id:
                        seos.instance = a
                    if seos.is_valid():
                        seos.save()
                    else:
                        for f in seos.forms:
                            if not f.is_valid():
                                # form.errors.update(f.errors)
                                if "__all__" in f.errors:
                                    messages.error(self.request, f.errors["__all__"])
                        if update_url:
                            return redirect(f"{update_url}#categories")
                        return self.form_invalid(form)

                if not update_only_referees and "file" in form.changed_data and instance.file:
                    try:
                        if cf := instance.update_converted_file(commit=True):
                            messages.success(
                                self.request,
                                _(
                                    "Your application form was converted into PDF file. "
                                    "Please review the converted application form version <a href='%s'>%s</a>. "
                                    "If it is not converted correctly, please save your document file in PDF format and reupload it."
                                )
                                % (cf.file.url, os.path.basename(cf.file.name)),
                            )

                    except Exception as ex:
                        capture_exception(ex)
                        messages.error(
                            self.request,
                            _(
                                "Failed to convert your application form into PDF. "
                                "Please save your application form into PDF format and try to upload it again."
                            ),
                        )
                        # url = self.request.path_info.split("?")[0] + "?summary=1"
                        # url = self.request.path_info.split("?")[0] + "#summary"
                        url = self.continue_url("summary")
                        return redirect(url)

                if (
                    not update_only_referees
                    and "letter_of_support_file" in form.changed_data
                    and instance.letter_of_support
                    and instance.letter_of_support.file
                    and form.cleaned_data["letter_of_support_file"].content_type
                    != "application/pdf"
                ):
                    try:
                        if letter_of_support_cf := instance.letter_of_support.update_converted_file(
                            commit=True
                        ):
                            messages.success(
                                self.request,
                                _(
                                    "Your letter of support form was converted into PDF file. "
                                    "Please review the converted file <a href='%s'>%s</a>."
                                )
                                % (
                                    letter_of_support_cf.file.url,
                                    os.path.basename(letter_of_support_cf.file.name),
                                ),
                            )

                    except Exception as ex:
                        capture_exception(ex)
                        messages.error(
                            self.request,
                            _(
                                "Failed to convert your letter of support form into PDF. "
                                "Please save the letter of support into PDF format and try to upload it again."
                            ),
                        )
                        url = self.continue_url("summary")
                        return redirect(url)

        except Exception as ex:
            if hasattr(form, "errors") and (errors := set(form.errors.get("__all__", []))):
                for e in errors:
                    messages.error(self.request, e)
            else:
                if hasattr(ex, "message"):
                    messages.error(self.request, ex.message)
                else:
                    messages.error(self.request, ex)
            capture_exception(ex)
            # return redirect(url)
            if url:
                return redirect(url)
            if update_url:
                return redirect(update_url)
            return self.form_invalid(form)

        if has_deleted:  # keep editing
            if not url:
                url = self.request.path_info
            return redirect(url)
        else:
            # url = None
            try:
                if "submit" in self.request.POST or "submit_to_referees" in self.request.POST:
                    if not update_only_referees and self.round.applicant_cv_required:
                        if not a.submitted_by or not (
                            models.CurriculumVitae.where(owner=a.submitted_by).exists()
                            or a.documents.filter(~Q(file=""), document_type__role="CV").exists()
                        ):
                            if not a.submitted_by or a.submitted_by != user:
                                messages.error(
                                    self.request,
                                    _(
                                        "Your team lead/representative must submit a CV "
                                        "before submitting the application"
                                    ),
                                )
                                return redirect(self.request.get_full_path())

                            next_url = (
                                reverse("application-update", kwargs={"pk": a.id})
                                if a and a.pk
                                else self.request.get_full_path()
                            )
                            messages.error(
                                self.request,
                                _(
                                    "To complete the application, you must provide a CV, please add a current CV "
                                    "to your profile. Otherwise the Prize application cannot be considered."
                                ),
                            )
                            url = reverse("profile-cvs") + "?next=" + next_url
                            return redirect(url)

                        elif not (
                            a.cv
                            or a.documents.filter(~Q(file=""), document_type__role="CV").exists()
                        ) and (
                            cv := models.CurriculumVitae.where(owner=a.submitted_by)
                            .order_by("-id")
                            .first()
                        ):
                            a.cv = cv

                    if (
                        not update_only_referees
                        and self.round.ethics_statement_required
                        and not (
                            a.ethics_statement
                            or (a.ethics_statement.not_relevant and a.ethics_statement.comment)
                            or a.ethics_statement.file
                        )
                    ):
                        messages.error(
                            self.request,
                            _(
                                "You must submit a ethics statement with your application "
                                "If it is not relevant, please state why."
                            ),
                        )
                        if not url:
                            url = self.continue_url("ethics-statement")
                        # url = url or (self.request.path_info.split("?")[0] + "#ethics-statement")

                    if not update_only_referees and not a.is_tac_accepted:
                        if a.submitted_by == user:
                            messages.error(
                                self.request,
                                _(
                                    "You have to accept the Terms and Conditions before submitting the application"
                                ),
                            )
                            if not url:
                                url = self.continue_url("tac")
                            # url = url or (self.request.path_info.split("?")[0] + "#tac")

                    if (
                        not update_only_referees
                        and a.round.budget_template
                        and not (
                            a.budget
                            or a.documents.filter(~Q(file=""), document_type__role="B").exists()
                        )
                    ):
                        messages.error(
                            self.request,
                            _(
                                "You must add a budget spreadsheet before submitting the application"
                            ),
                        )
                        if not url:
                            url = self.continue_url("summary")
                        # url = url or (self.request.path_info.split("?")[0] + "#summary")

                    if (
                        not update_only_referees
                        and site_id not in [2, 4, 5]
                        and not (
                            a.file
                            or (
                                has_required_documents
                                and models.ApplicationDocument.where(
                                    Q(document_type__role="AF")
                                    | Q(required_document__document_type__role="AF")
                                ).exists()
                            )
                        )
                    ):
                        messages.error(
                            self.request,
                            _(
                                "Missing the application form. Please attach an application form and re-submit"
                            ),
                        )
                        if not url:
                            url = self.continue_url("summary")
                        # url = url or (self.request.path_info.split("?")[0] + "#summary")

                    if (
                        not update_only_referees
                        and a.round
                        and a.round.pid_required
                        and a.submitted_by.needs_identity_verification
                        and not (
                            a.photo_identity
                            or models.IdentityVerification.where(application=a).exists()
                        )
                    ):
                        if (
                            a.photo_identity
                            or models.IdentityVerification.where(application=a).exists()
                        ):
                            messages.error(
                                self.request,
                                _(
                                    "Your identity has not been verified yet by the administration. "
                                    "We will notify you when it is verified and you can complete your application."
                                ),
                            )
                        else:
                            messages.error(
                                self.request,
                                _(
                                    "Your identity has not been verified. "
                                    "Please upload a scan of a document proving your identity."
                                ),
                            )
                        if not url:
                            url = self.continue_url("id-verification")

                    if site_id in [2, 5] or "submit_to_referees" in self.request.POST:
                        if (
                            a.round.required_referees
                            and a.referees.filter(~Q(state__in=["bounced", "opted_out"])).count()
                            < a.round.required_referees
                        ):
                            messages.error(
                                self.request,
                                _("You need to nominate at least %d referee(s).")
                                % a.round.required_referees,
                            )
                            if not url:
                                url = self.continue_url("referees")
                    else:
                        if (
                            a.round.required_referees
                            and a.referees.filter(
                                ~Q(state__in=["bounced", "opted_out"])
                                if site_id in [2, 4, 5]
                                else Q(state="testified")
                            ).count()
                            < a.round.required_referees
                        ):
                            messages.error(
                                self.request,
                                (
                                    _("You need to nominate at least %d referee(s).")
                                    if site_id in [2, 4, 5]
                                    else _(
                                        "You need to procure reviews of your application from at least %d referees."
                                    )
                                )
                                % a.round.required_referees,
                            )
                            if not url:
                                url = self.continue_url("referees")

                    if not update_only_referees and has_required_documents:
                        for rd in a.round.required_documents.filter(is_optional=False):
                            if not a.documents.filter(~Q(file=""), required_document=rd).exists():
                                form.add_error(
                                    None,
                                    _(
                                        f"{rd} is required. Please upload all required "
                                        "documents before submitting the application."
                                    ),
                                )
                                if not hasattr(form, "active_tab"):
                                    form.active_tab = "summary"

                    # if (
                    #     not update_only_referees
                    #     and site_id == 4
                    #     and a.round.has_seos
                    #     and a.application_seos.count() > 3
                    # ):
                    #     form.add_error(
                    #         None,
                    #         _(
                    #             "Please enter up to THREE SEO codes from the drop-down "
                    #             "field, using codes that are as specific as possible."
                    #         ),
                    #     )
                    #     if not hasattr(form, "active_tab"):
                    #         form.active_tab = "categories"

                    if (
                        not update_only_referees
                        and site_id in [2, 4, 5]
                        and a.round.has_seos
                        and a.application_seos.count() > 5
                    ):
                        form.add_error(
                            None,
                            _(
                                "Please enter up to FIVE SEO codes from the drop-down "
                                "field, using codes that are as specific as possible."
                            ),
                        )
                        if not hasattr(form, "active_tab"):
                            form.active_tab = "categories"

                    # if (
                    #     site_id == 4
                    #     and a.round.has_fors
                    #     and (
                    #         not (
                    #             fors_share_sum := a.application_fors.filter(code__is_stem=True)
                    #             .aggregate(Sum("share"))
                    #             .get("share__sum")
                    #         )
                    #         or fors_share_sum < 50
                    #     )
                    # ):
                    #     # form.add_error(
                    #     #     None,
                    #         # _(
                    #         #     "Please make sure that at least 50% of the proposed "
                    #         #     "research falls under one or more of the "
                    #         #     "ANZSRC STEM codes (excluding clinical sciences)."
                    #         # ),
                    #     # )
                    #     # if not hasattr(form, "active_tab"):
                    #     #     form.active_tab = "categories"

                    if site_id == 2 and a.state in ["new", "draft", "tac_accepted"]:

                        is_valid = True
                        if a.members.filter(~Q(role_id="PI"), country__isnull=True).exists():
                            messages.error(
                                self.request,
                                _(
                                    "Not all the team members have specified their country of origin. "
                                    "Please amend the team member list."
                                ),
                            )
                            is_valid = False
                        if a.members.filter(~Q(role_id="PI"), org__isnull=True).exists():
                            messages.error(
                                self.request,
                                _(
                                    "Not all the team members have specified their host organisation."
                                    "Please amend the team member list."
                                ),
                            )
                            is_valid = False
                        if a.members.filter(~Q(role_id="PI"), file="").exists():
                            messages.error(
                                self.request,
                                _(
                                    "Not all the team members have uploaded their host support letter."
                                    "Please ensure that all the team members have uploaded their host support letter."
                                ),
                            )
                            is_valid = False

                        if not is_valid and not url:
                            url = self.continue_url("applicant")

                    if form.errors:
                        return self.form_invalid(form)

                    if url:
                        return redirect(url)

                    if (
                        not update_only_referees
                        and "submit" in self.request.POST
                        and a.state in ["new", "draft", "tac_accepted"]
                    ):
                        if a.round.applicant_declaration and form.data.get(
                            "applicant_declaration_accepted"
                        ) not in ["on", 1, "true", "checked"]:
                            messages.error(
                                self.request,
                                _("Please accept the <strong>Applicant Declaration</strong>"),
                            )
                            url = f'{reverse("application-update", kwargs={"pk": a.pk})}#tac'
                            return redirect(url)

                        a.submit(request=self.request)
                        messages.info(
                            self.request,
                            (
                                _(
                                    "Your application has been successfully submitted. "
                                    "The Research Office will be in touch if there is anything more needed. Good luck."
                                )
                                if site_id in [2, 4, 5]
                                else _(
                                    "Your application has been successfully submitted. "
                                    "The Prize secretariat will be in touch if there is anything more needed. "
                                    "Good luck."
                                )
                            ),
                        )
                        a.save()
                elif (
                    self.request.method == "POST"
                    or "save_draft" in self.request.POST
                    or "send_invitations" in self.request.POST
                    or "save" in self.request.POST  # save and continue
                ):
                    if not current_state or current_state == "new":
                        a.save_draft(request=self.request)
                        a.save()
                    if "send_invitations" in self.request.POST:
                        # url = self.request.path_info.split("?")[0] + "#referees"
                        if not url:
                            url = self.continue_url("referees")
                        # return redirect(url)
                    elif "save" in self.request.POST:
                        url = a.update_url or self.request.path

                    elif not update_only_referees:
                        if (
                            site_id == 4
                            and a.round.has_fors
                            and a.fors.count() > 0
                            and (
                                not (
                                    fors_share_sum := a.application_fors.filter(code__is_stem=True)
                                    .aggregate(Sum("share"))
                                    .get("share__sum")
                                )
                                or fors_share_sum < 50
                            )
                        ):
                            messages.warning(
                                self.request,
                                _(
                                    "Please make sure that at least 50% of the proposed "
                                    "research falls under one or more of the "
                                    "ANZSRC STEM codes (excluding clinical sciences)."
                                ),
                            )

                if "submit_to_referees" in self.request.POST or (
                    site_id not in [2, 5] or a.state in ["approved", "accepted"]
                ):
                    if site_id not in [2, 5]:
                        count = a.invite_referees(
                            request=self.request, dispatch_invitations=dispatch_invitations
                        )
                    else:
                        count = a.send_out_to_referees(request=self.request) or a.referees.count()
                        a.save()
                else:
                    count = a.invite_referees(
                        request=self.request, dispatch_invitations=dispatch_invitations
                    )
                if dispatch_invitations and count:
                    messages.info(
                        self.request,
                        _(
                            f"Your application has been successfully submitted to {count} referee(s) to review it."
                        ),
                    )
                elif count:
                    messages.info(
                        self.request,
                        _(f"{count} new referee invitation(s) were successfully created."),
                    )

            except ValidationError as e:
                capture_exception(e)
                for m in e.messages:
                    messages.error(self.request, str(m))
                return redirect(self.continue_url(getattr(e, "code", None)))

            except Exception as e:
                capture_exception(e)
                messages.error(self.request, str(e))
                return redirect(self.continue_url())

            if url:
                return redirect(url)
        return resp

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        update_only_referees = self.update_only_referees()
        context["update_only_referees"] = update_only_referees
        context["model_name"] = self.model._meta.model_name
        if self.object and self.object.state:
            context["object_state"] = self.object.state

        round = self.round
        context["round"] = round
        latest_application = self.latest_application
        has_required_documents = round.required_documents.count() > 0

        if round.ethics_statement_required:
            et_not_relevant = (
                self.object
                and self.object.ethics_statement
                and self.object.ethics_statement.not_relevant
            )
            EthicsStatementForm = model_forms.modelform_factory(
                models.EthicsStatement,
                exclude=["application"],
                widgets={
                    "file": widgets.ClearableFileInput(
                        attrs=(
                            {
                                "accept": ".pdf,.odt,.ott,.oth,.odm,.doc,.docx,.docm,.docb,.rtf,.tex",
                            }
                            if et_not_relevant
                            else {
                                "placeholder": _("Please upload a file ..."),
                                "data-placeholder": _("Please upload a file ..."),
                                "data-required": 1,
                                "oninvalid": "this.setCustomValidity('%s')"
                                % _("The file is required. Please upload a file ..."),
                                "oninput": "this.setCustomValidity('')",
                                "accept": ".pdf,.odt,.ott,.oth,.odm,.doc,.docx,.docm,.docb,.rtf,.tex",
                            }
                        )
                    )
                },
            )
            ethics_statement_form = EthicsStatementForm(
                self.request.POST or None,
                self.request.FILES or None,
                instance=(
                    self.object.ethics_statement
                    if self.object
                    and self.object.id
                    and models.EthicsStatement.where(application=self.object).exists()
                    else None
                ),
                prefix="et",
            )
            ethics_statement_form.helper = forms.FormHelper(ethics_statement_form)
            ethics_statement_form.helper.form_tag = False
            ethics_statement_form.helper.layout = Layout(
                "file",
                "not_relevant",
                Field(
                    "comment",
                    oninvalid=f"""this.setCustomValidity('{_("If not relevant, please comment. "
                    "For example, the work in this application did not involve people or animals.")}')""",
                    oninput="this.setCustomValidity('')",
                ),
            )
            if self.object and (es := getattr(self.object, "ethics_statement", None)):
                ethics_statement_form.fields["comment"].required = es.not_relevant
            context["ethics_statement"] = ethics_statement_form

        # if (
        #     round.pid_required
        #     and not self.request.user.is_identity_verified
        #     and (
        #         not (self.object and self.object.id)
        #         or (
        #             not self.object.submitted_by_id
        #             or self.object.submitted_by == self.request.user
        #         )
        #     )
        # ):
        #     IdentityVerificationForm = model_forms.modelform_factory(
        #         models.IdentityVerification,
        #         exclude=["application", "resolution", "state"],
        #         widgets={"user": HiddenInput()},
        #     )
        #     identity_verification_form = IdentityVerificationForm(
        #         self.request.POST or None,
        #         self.request.FILES or None,
        #         instance=self.object.identity_verification
        #         if self.object
        #         and self.object.id
        #         and models.IdentityVerification.where(application=self.object).exists()

        #         else None,
        #         prefix="iv",
        #         initial={"user": self.request.user},
        #     )
        #     identity_verification_form.helper = forms.FormHelper(identity_verification_form)
        #     identity_verification_form.helper.form_tag = False
        #     identity_verification_form.helper.layout = Layout(
        #         Field(
        #             "photo_identity",
        #             data_toggle="tooltip",
        #             title=_(
        #                 "Please upload a scanned copy of the passport or drivers license "
        #                 "of the team lead in PDF, JPG, or PNG format"
        #             ),
        #         ),
        #     )
        #     context["identity_verification"] = identity_verification_form

        if round.scheme.team_can_apply:
            context["helper"] = forms.MemberFormSetHelper()
            duration = (
                self.object and self.object.site_id or settings.SITE_ID
            ) != 2 and round.duration
            if self.request.POST:
                context["members"] = (
                    forms.MemberFormSet(
                        self.request.POST, instance=self.object, form_kwargs={"duration": duration}
                    )
                    if self.object
                    else forms.MemberFormSet(self.request.POST, form_kwargs={"duration": duration})
                )
            else:
                initial_members = (
                    [
                        dict(
                            email=m.email,
                            first_name=m.first_name,
                            middle_names=m.middle_names,
                            last_name=m.last_name,
                            role=m.role,
                            user=m.user,
                        )
                        for m in latest_application.members.all()
                    ]
                    if latest_application and not (self.object and self.object.id)
                    else []
                )
                context["members"] = (
                    forms.MemberFormSet(
                        instance=self.object,
                        initial=initial_members,
                        form_kwargs={"duration": duration},
                    )
                    if self.object
                    else forms.MemberFormSet(
                        initial=initial_members, form_kwargs={"duration": duration}
                    )
                )

        if round.required_referees:
            referee_count = self.object and self.object.referees.count() or 0
            if round.is_flexible_number_of_referees:
                extra = max(((round.required_referees or 0) - referee_count), 1)
                max_num = referee_count + extra
            else:
                extra = max(((round.required_referees or 0) - referee_count), 0)
                max_num = referee_count + extra

            kwargs = {
                # "min_num": round.required_referees,
                "max_num": max_num,
                # "can_delete": False,
                "can_delete": True,
                "can_delete_extra": True,
                # "can_delete_extra": bool(round.is_flexible_number_of_referees),
                "extra": extra,
                "validate_max": False,
                "validate_min": False,
            }
        else:
            kwargs = {
                "extra": 1,
                "can_delete": True,
            }

        RefereeFormSet = forms.inlineformset_factory(
            self.model,
            models.Referee,
            form=forms.RefereeForm,
            formset=forms.MandatoryApplicationFormInlineFormSet,
            **kwargs,
        )

        if self.request.POST:
            referee_form_set = RefereeFormSet(self.request.POST, instance=self.object)
        else:
            referee_form_set = RefereeFormSet(
                instance=self.object,
                # initial=[
                #     dict(
                #         email=r.email,
                #         first_name=r.first_name,
                #         middle_names=r.middle_names,
                #         last_name=r.last_name,
                #     )
                #     for r in latest_application.referees.all()
                # ]
                # if latest_application and not (self.object and self.object.id)
                # else [],
            )
        context["referees"] = referee_form_set

        if has_required_documents:
            self.required_documents = context["required_documents"] = {
                rd.id: rd for rd in round.required_documents.order_by("ordering")
            }
            context["documents"] = self.get_document_formset()

        if round.has_fors:
            fsc = forms.inlineformset_factory(
                self.model,
                models.ApplicationFor,
                extra=1,
                can_delete=True,
                exclude=[],
                # fields = ["id", "code", "application", "share"],
                labels={"code": _("Field of Research")},
                help_texts={
                    "code": _("Field of Research"),
                    "share": _("Share in %"),
                },
                widgets={
                    "code": autocomplete.ModelSelect2(
                        "for-autocomplete",
                        attrs={
                            "data-placeholder": _("Choose a field of research..."),
                            "placeholder": _("Choose a field of research..."),
                            "data-required": 1,
                            "oninvalid": "this.setCustomValidity('%s')"
                            % _("Field of research is required"),
                            "oninput": "this.setCustomValidity('')",
                        },
                    ),
                },
            )

            initial_fors = (
                [
                    dict(
                        code=r.code_id,
                        share=r.share,
                    )
                    for r in models.ApplicationFor.where(application=latest_application)
                ]
                if latest_application and not (self.object and self.object.id)
                else []
            )
            # fs = fsc(self.request.POST or None, instance=self.object, initial=initial_fors)
            if self.request.POST and not update_only_referees:
                fs = fsc(self.request.POST, instance=self.object)
            elif not (self.object and self.object.id):
                fs = fsc(instance=self.object, initial=initial_fors)
            else:
                fs = fsc(instance=self.object)
            if initial_fors:
                fs.extra = len(initial_fors)
            context["fors"] = fs

        if round.has_seos:
            fsc = forms.inlineformset_factory(
                self.model,
                models.ApplicationSeo,
                # form=forms.RefereeForm,
                extra=1,
                can_delete=True,
                exclude=[],
                labels={"code": _("Socio-Economic Objective")},
                help_texts={
                    "code": _("Socio-Economic Objective"),
                    "share": _("Share in %"),
                },
                widgets={
                    "code": autocomplete.ModelSelect2(
                        "seo-autocomplete",
                        forward=(
                            "pk",
                            forward.Const("application", "type"),
                        ),
                        attrs={
                            "data-placeholder": _("Choose a ..."),
                            "placeholder": _("Choose a Socio-Economic Objective..."),
                            "data-required": 1,
                            "oninvalid": "this.setCustomValidity('%s')"
                            % _("Socio-Economic Objective is required"),
                            "oninput": "this.setCustomValidity('')",
                        },
                    ),
                },
            )
            initial_seos = (
                [
                    dict(
                        code=r.code_id,
                        share=r.share,
                    )
                    for r in models.ApplicationSeo.where(application=latest_application)
                ]
                if latest_application and not (self.object and self.object.id)
                else []
            )
            fs = fsc(
                not update_only_referees and self.request.POST or None,
                instance=self.object,
                initial=initial_seos,
            )
            fs.extra = len(initial_seos) or 1
            context["seos"] = fs
        return context

    def get_form_kwargs(self):
        """Return the keyword arguments for instantiating the form."""
        kwargs = super().get_form_kwargs()
        update_only_referees = self.update_only_referees()
        user = self.request.user
        initial = kwargs.get("initial", {})

        if update_only_referees:
            kwargs["update_only_referees"] = True
            if "data" in kwargs:
                del kwargs["data"]
            if "files" in kwargs:
                del kwargs["files"]

        kwargs["initial"]["user"] = user

        if self.object and self.object.id:
            return kwargs

        if "nomination" in self.kwargs:
            kwargs["initial"]["nomination"] = self.kwargs["nomination"]
            kwargs["initial"]["round"] = self.round.id
        elif "round" in self.kwargs:
            kwargs["initial"]["round"] = self.kwargs["round"]

        if n := self.nomination:
            kwargs["nomination"] = n

        if self.request.method == "GET" and initial:
            if self.request.site_id not in [2, 4, 5]:
                initial["application_title"] = self.round.title
            if "nomination" in self.kwargs and self.nomination and (no := self.nomination.org):
                initial["org"] = no.pk
                initial["organisation"] = no.name

        return kwargs

    def get_document_formset(self, *args, **kwargs):
        round = self.round
        initial_documents = [
            dict(required_document=rd_id)
            for rd_id in (
                round.required_documents.filter(
                    ~Q(id__in=self.object.documents.values("required_document_id"))
                ).order_by("ordering")
                if (self.object and self.object.pk)
                else round.required_documents.order_by("ordering")
            ).values_list("id", flat=True)
        ]
        required_documents = {rd.id: rd for rd in round.required_documents.order_by("ordering")}

        fsc = forms.inlineformset_factory(
            self.model,
            models.ApplicationDocument,
            extra=len(initial_documents),
            can_delete=False,
            exclude=[
                "document_type",
                "converted_file",
            ],
            widgets={
                "required_document": HiddenInput(),
                "page_count": HiddenInput(),
                # "required_document": widgets.Select(attrs={"disabled": True}),
                # "page_count": widgets.TextInput(attrs={"readonly": True, "disabled": True}),
                "file": widgets.ClearableFileInput(
                    attrs={
                        "placeholder": _("Please upload a file ..."),
                        "data-placeholder": _("Please upload a file ..."),
                        "data-required": 1,
                        "oninvalid": "this.setCustomValidity('%s')"
                        % _("The file is required. Please upload a file ..."),
                        "oninput": "this.setCustomValidity('')",
                        "can_delete": not self.object
                        or self.object.is_wip
                        or round.site_id in [2, 5]
                        and self.object.state in ["new", "darft", "submitted"],
                    }
                ),
            },
        )
        if self.request.method == "POST":
            update_only_referees = self.update_only_referees()
            fs = fsc(
                not update_only_referees and self.request.POST or None,
                not update_only_referees and self.request.FILES or None,
                instance=self.object,
                # initial=initial_documents,
            )
        else:
            fs = fsc(instance=self.object, initial=initial_documents)
        if initial_documents:
            fs.extra = len(initial_documents)
        help_texts = {
            rd.pk: forms.make_help_text(required_document=rd) for rd in required_documents.values()
        }
        if self.request.method in ["POST", "GET"]:
            return fs

        for f in fs.forms:
            rd_id = f.initial.get("required_document", 0)
            if rd_id:
                rd = required_documents.get(rd_id, None)
                if not isinstance(rd_id, int):
                    rd_id = rd_id.pk
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
        # context.update(
        #     {
        #         "formset": formset,
        #         "form_id": self.form_id,
        #         "required_documents": required_documents,
        #     },
        # )
        # return render_to_string(self.template, context)
        return fs

    def delete(self, request, *args, **kwargs):

        a = self.object = self.get_object()
        round = self.object.round
        if pk := int(request.GET.get("delete_document_id")):
            a.documents.filter(pk=pk).delete()

        formset_tag = False
        formset = self.get_document_formset()
        required_documents = {rd.id: rd for rd in round.required_documents.order_by("ordering")}
        return render(self.request, "portal/document_formset.html", locals())


class ApplicationUpdate(ApplicationView, UpdateView):
    pass


@method_decorator(shoud_be_onboarded, name="dispatch")
class ApplicationCreate(ApplicationView, CreateView):
    # class ApplicationCreate(LoginRequiredMixin, CreateWithInlinesView):
    # model = Application
    # # inlines = [MemberInline]
    # template_name = "application.html"
    # form_class = forms.ApplicationForm

    def get(self, request, *args, **kwargs):
        u = request.user
        n = (
            models.Nomination.get(kwargs["nomination"])
            if "nomination" in kwargs
            else (
                models.Nomination.where(
                    (
                        Q(round=kwargs["round"])
                        if "round" in kwargs
                        else Q(round__scheme__current_round=F("round"))
                    ),
                    email__in=self.request.user.email_addresses,
                )
                .order_by("-id")
                .first()
            )
        )
        if "round" in kwargs:
            r = models.Round.get(kwargs["round"])
            if n and n.round != r:
                n = (
                    models.Nomination.where(
                        email__in=self.request.user.email_addresses,
                        round=r,
                    )
                    .order_by("-id")
                    .first()
                )
        else:
            r = n and n.round
        if not r:
            messages.error(
                self.request,
                _("Failed to find any round you could apply for... Please contact adminstrator."),
            )
            return redirect("home")
        if n and n.state == "withdrawn":
            messages.error(request, _("The nominiation was withdrawn."))
            return redirect(self.request.META.get("HTTP_REFERER", "home"))
        if r.panellists.all().filter(user=u).exists():
            messages.error(
                self.request,
                _("You are a panellist for this round. You cannot apply for this round: %s")
                % r.title,
            )
            return redirect("home")

        a = self.model.where(submitted_by=u, round=r).order_by("-id").first()
        if nomination_id := request.GET.get("nomination") or n and n.pk:

            if nom := models.Nomination.get(nomination_id):
                if (
                    u.email != nom.email
                    and not u.emailaddress_set.filter(email=nom.email).exists()
                ):
                    messages.error(
                        self.request,
                        _(
                            "The nomination was not sent to your address. "
                            "Please contact the portal administrators."
                        ),
                    )
                    return redirect("home")

                if a and not (nom == n) and nom.application != a:
                    messages.warning(
                        self.request,
                        _(
                            "You have already created an application for this round. The nomination will be retracted."
                        ),
                    )
                if a and (nom == n) and not n.application:
                    n.application = a
                    models.Nomination.where(application=a).update(application=None)
                    if n.state != "accepted":
                        n.accept(
                            by=u,
                            description="Application in the round was already created; accepted by default",
                        )
                    n.save()
        if a and r.site_id != 2:
            messages.warning(
                self.request, _("You have already created an application. Please update it.")
            )
            return redirect(reverse("application-update", kwargs=dict(pk=a.pk)))

        if (
            not r.direct_application_allowed
            and not nomination_id
            and models.Nomination.where(id=nomination_id).exists()
        ):
            messages.error(
                self.request, _("You cannot apply directly for this round without a nomination.")
            )
            return redirect("home")

        return super().get(request, *args, **kwargs)

    # def get_context_data(self, **kwargs):
    #     context = super().get_context_data(**kwargs)
    #     context["helper"] = forms.MemberFormSetHelper()
    #     if self.object.is_team_application:
    #         if self.request.POST:
    #             context["members"] = forms.MemberFormSet(self.request.POST)
    #         else:
    #             context["members"] = forms.MemberFormSet()
    #     return context

    def form_valid(self, form):
        # Extra layer of protection - to prevent duplicate submission:
        kwargs = self.kwargs
        r = (
            models.Round.get(kwargs["round"])
            if "round" in kwargs
            else (
                models.Nomination.get(kwargs["nomination"]).round
                if "nomination" in kwargs
                else (
                    models.Nomination.get(
                        self.request.GET.get("nomination") or self.request.POST.get("nomination")
                    ).round
                    if "nomination" in self.request.GET or "nomination" in self.request.POST
                    else getattr(form.instance, "round")
                )
            )
        )
        if (
            r
            and r.site_id != 2
            and (a := self.model.where(round=r, submitted_by=self.request.user).last())
        ):
            messages.error(
                self.request,
                _(
                    "Fatal ERROR! You already have a created application. "
                    "Please continue with this application."
                ),
            )
            if a.state == "draft":
                return redirect("application-update", pk=a.id)
            return redirect("application", pk=a.id)

        try:
            with transaction.atomic():
                a = form.instance
                a.organisation = a.org.name
                a.submitted_by = self.request.user
                a.round = self.round
                a.scheme = a.round.scheme
                n = (
                    self.nomination
                    or self.round.user_nominations(self.request.user).order_by("-id").first()
                )
                if a and not a.number:
                    a.number = models.default_application_number(a, nomination=n)

                resp = super().form_valid(form)
                a.save()
                if n and not (n.application and n.user):
                    n.application = self.object
                    if n.state != "accepted":
                        n.accept()
                    if not n.user:
                        n.user = self.request.user
                    n.save(update_fields=["application_id", "state", "user"])
                if (
                    n
                    and (i := models.Invitation.where(type="A", nomination=n).first())
                    and i.state in ["sent", "new", "bounced", "draft", "submitted", "read"]
                ):
                    i.accept(request=self.request, by=self.request.user)
                    i.save()

                u = a.submitted_by
                p = u.person
                if a.title:
                    if not (p.title and p.title == a.title):
                        p.title = a.title
                        p.save(update_fields=["title"])
                    if not (u.title and u.title == a.title):
                        u.title = a.title
                        u.save(update_fields=["title"])

                if u and not (u.first_name and u.last_name and u.middle_names):
                    if not u.first_name and a.first_name:
                        u.first_name = a.first_name
                    if not u.last_name and a.last_name:
                        u.last_name = a.last_name
                    if not u.middle_names and a.middle_names:
                        u.middle_names = a.middle_names
                    u.save()

        except Exception as ex:
            capture_exception(ex)
            form.errors["__all__"] = f"Unhandled except occurred: {ex}"
            return self.form_invalid(form)

        return resp


# class ApplicationTeamMembersStageFormSetView(LoginRequiredMixin, ModelFormSetView):

#     model = models.Member
#     # formset_class = ProfileCareerStageFormSet

#     def get_queryset(self):
#         return self.model.objects.filter(application=self.application)

#     template_name = "profile_section.html"
#     exclude = ()
#     section_views = [
#         "profile-employments",
#         "profile-career-stages",
#         "profile-external-ids",
#         "profile-cvs",
#         "profile-academic-records",
#         "profile-recognitions",
#         "profile-professional-records",
#     ]

#     def dispatch(self, request, *args, **kwargs):
#         if request.user.is_authenticated and not Person.where(user=self.request.user).exists():
#             return redirect("onboard")
#         return super().dispatch(request, *args, **kwargs)

#     def get_defaults(self):
#         """Default values for a form."""
#         return dict(
#                 profile=self.request.profile,
#                 application=self.application
#         )

#     def get_formset(self):

#         klass = super().get_formset()
#         defaults = self.get_defaults()

#         class Klass(klass):
#             def get_form_kwargs(self, index):
#                 kwargs = super().get_form_kwargs(index)
#                 if "initial" not in kwargs:
#                     kwargs["initial"] = defaults
#                 else:
#                     kwargs["initial"].update(defaults)
#                 return kwargs

#         return Klass

#     def get_factory_kwargs(self):
#         kwargs = super().get_factory_kwargs()
#         widgets = kwargs.get("widgets", {})
#         widgets.update({"profile": HiddenInput()})
#         widgets.update({"application": HiddenInput()})
#         kwargs["widgets"] = widgets
#         kwargs["can_delete"] = True
#         return kwargs

#     # def get_initial(self):
#     #     defaults = self.get_defaults()
#     #     initial = super().get_initial()
#     #     if not initial:
#     #         initial = [dict()]
#     #         if self.request.method != "GET":
#     #             initial = initial * int(self.request.POST["form-TOTAL_FORMS"])
#     #     for row in initial:
#     #         row.update(defaults)
#     #     return initial

#     def get_context_data(self, **kwargs):
#         context = super().get_context_data(**kwargs)
#         previous_step = next_step = None
#         if not self.request.user.profile.is_completed:
#             view_idx = self.section_views.index(self.request.resolver_match.url_name)
#             if view_idx > 0:
#                 previous_step = self.section_views[view_idx - 1]
#                 context["previous_step"] = previous_step
#             if view_idx < len(self.section_views) - 1:
#                 next_step = self.section_views[view_idx - 1]
#                 context["next_step"] = next_step
#             context["progress"] = ((view_idx + 2) * 100) / (len(self.section_views) + 1)
#         context["helper"] = ProfileSectionFormSetHelper(
#             previous_step=previous_step, next_step=next_step
#         )
#         return context

#     def get_success_url(self):
#         if not self.request.user.profile.is_completed:
#             view_idx = self.section_views.index(self.request.resolver_match.url_name)
#             if "previous" in self.request.POST:
#                 return reverse(self.section_views[view_idx - 1])
#             if "next" in self.request.POST and view_idx < len(self.section_views) - 1:
#                 return reverse(self.section_views[view_idx + 1])
#             return reverse("profile", kwargs={"pk": self.request.user.profile.id})
#         return super().get_success_url()

#     def formset_valid(self, formset):
#         url_name = self.request.resolver_match.url_name
#         profile = self.request.user.profile
#         if url_name == "profile-employments":
#             profile.is_employments_completed = True
#         if url_name == "profile-professional-records":
#             profile.is_professional_bodies_completed = True
#         if url_name == "profile-career-stages":
#             profile.is_career_stages_completed = True
#         if url_name == "profile-external-ids":
#             profile.is_external_ids_completed = True
#         if url_name == "profile-cvs":
#             profile.is_cvs_completed = True
#         if url_name == "profile-academic-records":
#             profile.is_academic_records_completed = True
#         if url_name == "profile-recognitions":
#             profile.is_recognitions_completed = True
#         profile.save()
#         return super().formset_valid(formset)


class InvitationList(LoginRequiredMixin, SingleTableView):
    table_class = tables.InvitationTable
    model = models.Invitation
    template_name = "table.html"
    extra_context = {"category": "applications"}

    def get_queryset(self, *args, **kwargs):
        queryset = super().get_queryset(*args, **kwargs)
        u = self.request.user
        if not (u.is_superuser or u.is_staff or u.is_site_staff):
            queryset = queryset.filter(Q(inviter=u) | Q(email__in=u.email_addresses))
        return queryset


class ContractList(LoginRequiredMixin, StateInPathMixin, SingleTableMixin, FilterView):
    table_class = tables.ContractTable
    model = models.Contract
    template_name = "table.html"
    extra_context = {"category": "contracts"}
    filterset_class = filters.ContractFilterSet

    def get_table_kwargs(self):
        u = self.request.user
        if u.is_admin:
            return {
                "extra_columns": [
                    (
                        _("Export"),
                        django_tables2.LinkColumn(
                            "contract-export",
                            args=[django_tables2.A("pk")],
                            orderable=False,
                            # kwargs={"format": "pdf", "pk": django_tables2.A("pk")},
                            text=gettext_lazy("Export"),
                            attrs={
                                "a": {
                                    "class": "btn btn-primary btn-sm",
                                    # "target": "_blank",
                                    "data-toggle": "tooltip",
                                    "title": gettext_lazy(
                                        "Export the contract into a consolidated PDF file"
                                    ),
                                },
                                "td": {"class": "text-center"},
                            },
                        ),
                    )
                ]
            }
        return {}

    def get_queryset(self, *args, **kwargs):
        u = self.request.user
        # queryset = queryset.filter(Q(members__isnull=True) | Q(members__role="PI"))
        # if not (u.is_superuser or u.is_site_staff):
        #     queryset = queryset.filter(Q(members__user=u) | Q(org__research_offices__user=u))
        # return queryset.distinct()
        return self.model.user_objects(
            queryset=super().get_queryset(*args, **kwargs), user=u, request=self.request
        ).distinct()


class ContractDetail(FavoriteMixin, DetailView):
    template_name = "portal/contract_detail.html"
    model = models.Contract
    slug_field = "number"
    slug_url_kwarg = "number"

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        u = self.request.user
        o = self.object
        if u.is_admin or (o and (org := o.org or o.application.org) and org.is_ro(user=u)):
            context["can_edit"] = True
            if (
                o.is_current
                and not o.change_requests.filter(
                    state__in=["draft", "submitted", "acknowledged", "accepted"]
                ).exists()
            ):
                change_request_form = forms.ChangeRequestForm(
                    initial={"contract": o, "submitted_by": u},
                )
                change_request_form.fields.pop("categories")
                change_request_form.fields.pop("subcategories")
                change_request_form.fields.pop("tags", None)
                context["change_request_form"] = change_request_form
                if u.is_admin:
                    context["is_admin"] = True
        context["tabbed_ui"] = (
            context.get("tabbed_ui", False)
            or context.get("can_edit", False)
            or o.change_requests.exists()
            or o.reports.exists()
        )
        return context

    def get_queryset(self):
        u = self.request.user
        qs = (
            super()
            .get_queryset()
            .prefetch_related(
                Prefetch(
                    "allocations", queryset=models.Allocation.objects.all().order_by("period")
                ),
                Prefetch(
                    "reporting_schedule",
                    queryset=models.ReportingScheduleEntry.objects.all().order_by(
                        "period", "due_date"
                    ),
                ),
                Prefetch(
                    "change_requests",
                    queryset=models.ChangeRequest.objects.all().order_by("number"),
                ),
            )
        )
        if not (u.is_superuser or u.is_site_staff):
            qs = qs.filter(Q(members__user=u) | Q(org__research_offices__user=u)).distinct()
        return qs


class ContractViewMixin:

    extra_context = {"category": "contracts"}

    def get_queryset(self):
        u = self.request.user
        qs = super().get_queryset()
        if not (u.is_superuser or u.is_site_staff):
            qs = qs.filter(Q(members__user=u) | Q(org__research_offices__user=u)).distinct()
        return qs

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    @cached_property
    def is_ro(self):
        u = self.request.user
        org = self.object and self.object.org or self.application.org
        return org.research_offices.filter(user=u).exists() and not (
            u.is_superuser or u.is_site_staff
        )

    @cached_property
    def application(self):
        if self.object and self.object.application_id:
            return self.object.application
        return get_object_or_404(
            models.Application,
            pk=(
                self.kwargs.get("pk")
                or self.kwargs.get("application_pk")
                or self.kwargs.get("application_id")
                or self.request.GET.get("application_id")
                or self.request.GET.get("application_pk")
            ),
        )

    def get_allocation_formset(self, *args, **kwargs):
        if self.object and self.object.pk:
            extra = 0
            initial_allocations = []
            duration = self.object.duration or 3
        else:
            a = self.application
            duration = a.round.duration or 3
            extra = duration
            initial_allocations = [
                dict(
                    period=p,
                    allocation=0.0,
                )
                for p in range(1, duration + 1)
            ]
        fsc = forms.inlineformset_factory(
            self.model,
            models.Allocation,
            can_delete=False,
            form=forms.AllocationForm,
            extra=extra,
            widgets={
                "period": forms.Select(
                    # choices=[(None, "---"), *((i, _(f"Year {i}")) for i in range(1, duration + 1))]
                    choices=[(i, _(f"Year {i}")) for i in range(1, duration + 1)]
                ),
                # "period": TextInput(attrs={"readonly": "readonly", "style": "text-align: right;"}),
                "allocation": NumberInput(attrs={"style": "text-align: right;", "step": 0.01}),
                "purpose": Textarea(attrs={"rows": 3}),
                "details": Textarea(attrs={"rows": 3}),
            },
        )
        return fsc(
            self.request.POST or None,
            instance=self.object,
            initial=initial_allocations,
            form_kwargs={"is_ro": self.is_ro},
        )

    def get_reporting_schedule_formset(self, *args, **kwargs):
        a = self.application
        duration = self.object and self.object.duration or a.round.duration or 3
        if self.object and self.object.pk:
            initial = None
            extra = 1
        else:
            initial = [
                dict(
                    period=p,
                    type="A" if p != duration else "F",
                    # due_date=timezone.now()+relativedelta(years=p),
                    due_date=a.created_at + relativedelta(years=p),
                )
                for p in range(1, duration + 1)
            ]
            extra = duration
        fsc = forms.inlineformset_factory(
            self.model,
            models.ReportingScheduleEntry,
            can_delete=True,
            can_delete_extra=True,
            # form=forms.AllocationForm,
            # fields="__all__",
            exclude=["request_info_date", "state", "acknowledged_at"],
            extra=extra,
            labels={"date_first_remind": _("First Reminder")},
            widgets={
                "period": forms.Select(
                    choices=[(None, "---"), *((i, _(f"Year {i}")) for i in range(1, duration + 1))]
                ),
                "due_date": forms.DateInput(start_date="-1y", end_date="+10y"),
                "date_first_remind": forms.DateInput(start_date="-1y", end_date="+10y"),
            },
        )
        return fsc(
            self.request.POST or None,
            instance=self.object,
            initial=initial,
            queryset=models.ReportingScheduleEntry._default_manager.order_by("period", "due_date"),
            # form_kwargs={"duration": duration}
        )

    def get_personnel_formset(self, *args, **kwargs):
        a = self.application
        duration = self.object and self.object.duration or a and a.round.duration or 3
        if self.object and self.object.id:
            extra = 1
            initial = []
        else:
            a = self.application
            pi, _ = models.RoleType.objects.get_or_create(
                code="PI",
                defaults={
                    "name": "Principal Investigator",
                    "description": "Principal Investigator",
                },
            )

            initial = [
                dict(
                    email=a.email or a.submitted_by.email,
                    first_name=a.first_name or a.submitted_by and a.submitted_by.first_name,
                    middle_names=a.middle_names,
                    last_name=a.last_name or a.submitted_by and a.submitted_by.last_name,
                    role=pi.code,
                    user=a.submitted_by,
                ),
                *[
                    dict(
                        email=m.email,
                        first_name=m.first_name or m.user and m.user.first_name,
                        middle_names=m.middle_names,
                        last_name=m.last_name or m.user and m.user.last_name,
                        role=m.role and models.RoleType.where(name__icontains=m.role).first(),
                        user=m.user,
                    )
                    for m in a.members.all()
                ],
            ]
            extra = len(initial) + 1
        fsc = forms.inlineformset_factory(
            self.model,
            models.ContractMember,
            can_delete=True,
            form=forms.ContractMemberForm,
            extra=extra,
        )
        return fsc(
            self.request.POST or None,
            instance=self.object,
            initial=initial,
            form_kwargs={"duration": duration},
        )

    def get_document_formset(self, *args, **kwargs):
        round = self.application.round
        exclued_document_roles = [r for _, r in self.form_class.part_fields]

        initial = []
        if not (self.object and self.object.id):
            for d in self.application.documents.filter(
                ~Q(document_type__role__in=exclued_document_roles),
                ~Q(required_document__role__in=exclued_document_roles),
                ~Q(required_document__role="EC"),
            ):
                dt, dtr, df = d.document_type, d.document_type.role, d.file
                role = dtr
                if role in ["AF", "B"]:
                    if role == "AF":
                        role = "AIM"
                    elif role == "B":
                        role = "PB"

                if role == dtr:
                    rcd = round.required_contract_documents.filter(document_type=dt).last()
                    if not rcd:
                        rcd = round.required_contract_documents.create(document_type=dt)
                else:
                    rcd = round.required_contract_documents.filter(document_type__role=role).last()
                    if not rcd:
                        dt = models.DocumentType.where(role=role).last()
                        if not dt:
                            dt = models.DocumentType.create(role=role)
                        rcd = round.required_contract_documents.create(document_type=dt)

                initial.append(
                    dict(
                        application_document=d.pk,
                        required_document=rcd,
                        document_type=rcd.document_type,
                        file=df,
                    )
                )
        elif self.request.method != "POST":
            initial = [
                dict(required_document=rd[0], document_type=rd[1])
                for rd in (
                    round.required_contract_documents.values_list("id", "document_type")
                    .filter(
                        ~Q(id__in=self.object.documents.values("required_document_id")),
                        ~Q(document_type__role__in=exclued_document_roles),
                        ~Q(role__in=exclued_document_roles),
                        ~Q(role="EC"),
                    )
                    .order_by("ordering")
                )
            ]

        class ContractDocumentForm(ModelForm):

            application_document = fields.Field(widget=HiddenInput(), required=False)

            def save(self, commit=True):
                if (
                    self.cleaned_data.get("application_document")
                    and not self.cleaned_data.get("file")
                    and (
                        d := models.ApplicationDocument.get(
                            self.cleaned_data["application_document"]
                        )
                    )
                ):
                    res = super().save(commit=False)
                    res.file = d.file
                    res.save()
                    return res
                elif "file" in self.changed_data and self.cleaned_data.get("file"):
                    res = super().save(*args, **kwargs)
                    return res
                return self.instance

        class Meta:
            model = models.ContractDocument
            exclude = ["converted_file"]

        fsc = forms.inlineformset_factory(
            self.model,
            models.ContractDocument,
            form=ContractDocumentForm,
            extra=len(initial),
            can_delete=False,
            exclude=[
                "converted_file",
            ],
            widgets={
                "application_document": HiddenInput(),
                "required_document": HiddenInput(),
                "state": HiddenInput(),
                "page_count": HiddenInput(),
                "document_type": HiddenInput(),
                # "required_document": widgets.Select(attrs={"disabled": True}),
                # "page_count": widgets.TextInput(attrs={"readonly": True, "disabled": True}),
                "file": widgets.ClearableFileInput(
                    attrs={
                        "placeholder": _("Please upload a file ..."),
                        "data-placeholder": _("Please upload a file ..."),
                        "data-required": 1,
                        "oninvalid": "this.setCustomValidity('%s')"
                        % _("The file is required. Please upload a file ..."),
                        "oninput": "this.setCustomValidity('')",
                    }
                ),
            },
        )

        # exclude budgets
        class fsc(fsc):
            def get_queryset(self):
                qs = (
                    super()
                    .get_queryset()
                    .filter(
                        ~Q(document_type__role__in=exclued_document_roles),
                        ~Q(required_document__role__in=exclued_document_roles),
                        ~Q(required_document__role="EC"),
                    )
                )
                return qs

        # qs = self.object.documents.filter(
        #     ~Q(document_type__role__in=exclued_document_roles),
        #     ~Q(required_document__role="EC"),
        # )
        if self.request.POST:
            fs = fsc(
                self.request.POST or None,
                self.request.FILES or None,
                instance=self.object,
                # queryset=qs,
                # initial=initial,
            )
        else:
            # fs = fsc(instance=self.object, queryset=qs, initial=initial)
            fs = fsc(instance=self.object, initial=initial)
        if initial:
            fs.extra = len(initial)
        return fs

    def get_address_form(self):
        contract = self.object
        application = self.application
        applicant = application and application.submitted_by.person

        a = None
        if contract and contract.address:
            a = contract.address
        if not (contract and contract.pk):
            if not a and applicant:
                a = applicant.address
            if not a and application:
                a = applicant.address

        return forms.AddressForm(
            data=self.request.POST or None,
            instance=a,
            initial=a
            and {
                "address": a.address or "",
                "city": a.city or "",
                "postcode": a.postcode or "",
                "country": a.country,
            }
            or {"country": "NZ"},
        )

    def get_change_request_reply_form(self):
        i = self.object
        u = self.request.user

        if i.is_variation and u.is_admin and (cr := i.originated_by):
            form = model_forms.modelform_factory(
                models.ChangeRequest,
                fields=("reply",),
                widgets={
                    "reply": SummernoteInplaceWidget(
                        attrs={"summernote": {"width": "100%", "height": "200px"}}
                    )
                },
                labels={"reply": _("Reply to the change request")},
            )(self.request.POST or None, instance=cr, prefix="change_request")
            form.helper = forms.FormHelper(form)
            form.helper.form_tag = False
            form.helper.include_media = False
            return form

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        u = self.request.user
        i = self.object
        org = self.object and self.object.org or self.application.org
        if is_ro := org.research_offices.filter(user=u).exists():
            context["is_ro"] = is_ro
        # else:
        #     self.allocations = context["allocations"] = self.get_allocation_formset()
        self.allocations = context["allocations"] = self.get_allocation_formset()

        self.reporting_schedule = context["reporting_schedule"] = (
            self.get_reporting_schedule_formset()
        )
        self.personnel = context["personnel"] = self.get_personnel_formset()
        a = self.application
        context["application"] = a
        # context["nomination"] = models.Nomination.where(application=a).order_by("-pk").first()
        # context["coordinator"] =

        context["application_documents"] = list(
            a.documents.filter(~Q(file=""), file__isnull=False).order_by(
                "required_document__ordering"
            )
        )
        context["round"] = round = a.round
        context["is_pi"] = self.object and self.object.pk and self.object.is_pi(u)
        if self.object and self.object.pk:
            c = self.object
            needs_attention = []
            if not (c.start_date and c.end_date):
                needs_attention = ["summary"]
            if not (c.project_title and c.abstract):
                needs_attention.append("research")
            if not c.members.exists():
                needs_attention.append("personnel")
            if not c.reporting_schedule.exists():
                needs_attention.append("reporting")
            # TODO:
            context["needs_attention"] = needs_attention

        self.documents = context["documents"] = self.get_document_formset()
        context["required_documents"] = {
            rd.id: rd for rd in round.required_contract_documents.order_by("ordering")
        }
        if "address_form" not in kwargs:
            context["address_form"] = self.get_address_form()
        context["state"] = self.object and self.object.state or "draft"
        if i.is_variation and u.is_admin and i.originated_by:
            context["change_request_reply_form"] = self.get_change_request_reply_form()

        return context

    # def post(self, *args, **kwargs):
    #     return super().post(*args, **kwargs)

    # def form_invalid(self, form):
    #     return super().form_invalid(form)

    def form_valid(self, form):
        i = form.instance
        if "start_date" in form.changed_data and i.pk:
            current_start_date = (
                self.model.where(pk=i.pk).values_list("start_date", flat=True).first()
            )

        site = i and i.site or self.request.site
        contract_state = i.state
        if i and i.pk:
            for part in ["cover", "preamble", "schedule1", "schedule2", "file"]:
                if f"delete_{part}" in form.data:
                    getattr(i, part).delete()
                    setattr(i, part, None)
                    i.save(update_fields=[part])
                    return redirect(self.request.META.get("HTTP_REFERER") + "#parts")

        a = self.application
        r = a.round
        request = self.request
        u = request.user
        if not i.submitted_by:
            i.submitted_by = u
        org = i.org or a.org
        if not i.org:
            i.org = org
        if not i.application:
            i.application = a
        if not i.number:
            i.number = models.Contract.new_number(application=a)
        if not i.fund:
            i.fund = models.Fund.last()
        try:
            is_ro = org.is_ro(user=u) and not (u.is_superuser or u.is_site_staff)
            with transaction.atomic():
                action = self.request.POST.get("action", None)
                address_form = self.get_address_form()
                if address_form.changed_data or not self.object.address:
                    if address_form.data.get("address") and form.data.get("address").strip():
                        if not address_form.is_valid():
                            return self.form_invalid(form)
                        address = address_form.save()
                    else:
                        address = None
                    form.instance.address = self.object.address = address

                if "submit_contract" in form.data:
                    i.submitted_by = u
                    # self.instance.state_changed_at = self.instance.submitted_at = timezone.now()
                    i.submit(request=self.request, user=u)
                elif "approve_contract" in form.data or action in [
                    "approve_contract",
                    "approve_variant",
                ]:
                    i.approve(request=self.request, by=u)
                resp = super().form_valid(form)

                fs = self.get_allocation_formset()
                fs.instance = self.object
                if fs.is_valid():
                    fs.save()

                fs = self.get_reporting_schedule_formset()
                if not is_ro:
                    fs.instance = self.object
                    if fs.is_valid():
                        fs.save()

                if "start_date" in form.changed_data and i.pk:
                    if current_start_date and i.start_date and i.start_date != current_start_date:
                        delta = relativedelta(i.start_date, current_start_date)
                        reporting_schedule_changed = False
                        reporting_schedule_changed
                        for rse in i.reporting_schedule.all().order_by("period", "due_date"):
                            if rse.due_date:
                                due_date = (rse.due_date + delta).replace(day=1)
                            else:
                                due_date = (
                                    i.start_date + relativedelta(years=rse.period)
                                ).replace(day=1) + (
                                    relativedelta(days=-1, months=r.final_report_deferral or 3)
                                    if rse.period == i.duration and rse.type == "F"
                                    else relativedelta(days=-1)
                                )
                            if rse.due_date != due_date:
                                rse.due_date = due_date
                                reporting_schedule_changed = True

                            if rse.date_first_remind:
                                date_first_remind = (rse.date_first_remind + delta).replace(day=1)
                            else:
                                date_first_remind = rse.due_date + relativedelta(months=-1)

                            if rse.date_first_remind != date_first_remind:
                                rse.date_first_remind = date_first_remind
                                reporting_schedule_changed = True

                            if reporting_schedule_changed:
                                rse.save(update_fields=["due_date", "date_first_remind"])

                        if reporting_schedule_changed:
                            messages.info(
                                self.request,
                                _(
                                    "The reporting schedule have been updated according to the new contract start date. "
                                    "Please review the reporting schedule."
                                ),
                            )

                fs = self.get_personnel_formset()
                fs.instance = self.object
                if fs.is_valid():
                    fs.save()
                else:
                    for f in fs.forms:
                        if f.errors:
                            form.errors.update(f.errors)
                    return self.form_invalid(form)

                fs = self.get_document_formset()
                fs.instance = self.object
                if fs.is_valid():
                    fs.save(commit=False)
                    for f in fs.forms:
                        if "file" in f.changed_data:
                            i.save_draft(request=request, user=u)
                            if f.instance.file.name.lower().endswith(".pdf"):
                                doc_file = f.instance.file.open()
                                f.instance.update_page_count(doc_file)
                                # f.instance.sarve(update_fields=["page_count"])
                            else:
                                cf = f.instance.update_converted_file()
                                # f.instance.save(update_fields=["page_count", "converted_file"])
                                if cf:
                                    messages.success(
                                        self.request,
                                        _(
                                            "%(document_type)s %(original)s was converted into PDF file. "
                                            "Please review the converted document <a href='%(url)s'>%(name)s</a>."
                                        )
                                        % {
                                            "document_type": f.instance.document_type
                                            or f.instance.required_document
                                            and f.instance.required_document.document_type,
                                            "original": os.path.basename(f.instance.file.name),
                                            "url": cf.file.url,
                                            "name": os.path.basename(cf.file.name),
                                        },
                                    )
                    fs.save(commit=True)

                if "budget" in form.changed_data and (
                    budget := i.documents.filter(required_document__role="B").last()
                ):
                    budget.save_draft(request=request, user=u)
                    budget.converted_file = None
                    budget.save(update_fields=["converted_file", "state", "updated_at"])

                if i.is_variation and u.is_admin and i.originated_by:
                    reply_form = self.get_change_request_reply_form()
                    if reply_form.changed_data and reply_form.is_valid():
                        reply_form.save()

        except Exception as ex:
            capture_exception(ex)
            messages.error(self.request, getattr(ex, "message", str(ex)))
            return super().form_invalid(form)

        is_host = (
            org.research_offices.filter(user=u).exists()
            or i.submitted_by == u
            or a.submitted_by == u
            or i.members.filter(user=u).exists()
            or a.members.filter(user=u).exists()
        )
        if (
            self.request.POST.get("doc_role")
            or self.request.POST.get("doc_type")
            or "post_comment" in self.request.POST
        ):
            if is_host:
                if i.fund and i.fund.email:
                    recipients = [i.fund.email]
                else:
                    recipients = [u for u in site.staff_users.all()] or [
                        u for u in User.where(is_superuser=True)
                    ]
            else:
                if i.host_contact_email:
                    recipients = [i.host_contact_email]
                elif org.email or org.ro_email:
                    recipients = [org.email or org.ro_email]
                else:
                    recipients = [ro.user for ro in a.org.research_offices.all()] or [
                        u for u in User.where(Q(applications=a) | Q(members__application=a))
                    ]
        else:
            recipients = []
        recipient_list = ", ".join(
            [
                r.full_name_with_email if isinstance(r, models.User) else r
                for r in (recipients if isinstance(recipients, (list, tuple)) else [recipients])
            ]
        )
        if (
            self.request.POST.get("doc_role")
            or self.request.POST.get("doc_type")
            or self.request.POST.get("required_doc")
        ):
            document_role = form.data.get("doc_role")
            document_type = form.data.get("doc_type")
            document_action = form.data.get("doc_action")
            required_document = form.data.get("required_doc")
            resolution = (form.data.get("resolution") or "").strip()
            if (document_role in models.DOCUMENT_ROLES or document_type or required_document) and (
                d := (
                    i.documents.filter(required_document=required_document).order_by("-pk").first()
                    if required_document
                    else (
                        i.documents.filter(
                            Q(required_document__document_type__role=document_role)
                            | Q(document_type__role=document_role)
                        )
                        .order_by("-pk")
                        .first()
                        if document_role
                        else (
                            i.documents.filter(
                                Q(document_type=document_type)
                                | Q(required_document__document_type=document_type)
                            )
                            .order_by("id")
                            .last()
                        )
                    )
                )
            ):
                previous_state = d.state
                if document_action in ["approve", "release"]:
                    if is_host:
                        if d.state not in ["accepted", "approved", "released"]:
                            if document_action == "release":
                                d.release(
                                    request=self.request,
                                    description=resolution or f"released by {u}",
                                    user=u,
                                )
                            else:
                                d.approve(
                                    request=self.request,
                                    description=resolution or f"approved by {u}",
                                    user=u,
                                )
                        else:
                            messages.warning(
                                self.request, _("The document was already %s") % _(d.state)
                            )
                    else:
                        if d.state != "accepted":
                            d.accept(
                                request=self.request,
                                description=resolution or f"accepted by {u}",
                                user=u,
                            )
                        else:
                            messages.warning(
                                self.request, _("The document was already %s") % _(d.state)
                            )
                    if d.state != previous_state:
                        messages.info(self.request, _("The document %s was %s") % (d, _(d.state)))
                elif document_action == "accept":
                    if d.state != "accepted":
                        d.accept(
                            request=self.request, description=resolution or f"accepted by {u}"
                        )
                    else:
                        messages.warning(
                            self.request, _("The document was already %s") % _(d.state)
                        )
                elif document_action == "request_correction":
                    d.save_draft(
                        request=self.request,
                        description=resolution or f"requested corrections by {u}",
                    )
                    i.save_draft(
                        self.request,
                        user=self.request.user,
                        description=f"requested corrections of {d} by {u}",
                    )
                    if contract_state != "draft":
                        i.save(update_fields=["state", "state_changed_at", "updated_at"])
                if previous_state != d.state:
                    d.save()

                respond_url = self.request.build_absolute_uri(
                    reverse("contract-update", kwargs=dict(pk=i.pk))
                )
                if document_role in ["B", "PB", "AB"]:
                    respond_url += "#finances"
                # elif document_role in ["AIM", "PT"]:
                #     respond_url += "#research"
                elif document_role or document_type or required_document:
                    respond_url += "#appendices"

                if document_action == "request_correction":
                    html_message = f'<p>The contract record <data value="{i.number}">{i}</data> was update by {u.full_name_with_email}'
                    html_message += f":</p>{resolution}" if resolution else ".</p>"
                    html_message += f'<hr/>To review the entry, please, click here: <a href="{respond_url}">{i}</a>'
                    subject = f"{u.full_name_with_email} requested correction(s) of the contract {i} {d.document_type} {d}"
                    messages.info(
                        self.request,
                        _("The request to amend the %s was sent to %s") % (d, recipient_list),
                    )
                elif document_action in ["request_approval", "awaiting_approval"]:
                    html_message = f'<p>The contract record <data value="{i.number}">{i}</data> was update by {u.full_name_with_email}:'
                    html_message += f":</p>{resolution}" if resolution else ".</p>"
                    html_message += f'<hr/>To review the entry, please, click here: <a href="{respond_url}">{i}</a>'
                    subject = f"{u.full_name_with_email} requested approval of the contract {i} {d.document_type} {d}"
                    messages.info(
                        self.request,
                        _("The request to approve the %s was sent to %s") % (d, recipient_list),
                    )
                else:
                    # if not document_action or document_action in ["approve", "release"]:
                    # TODO: notify about approvals after all documents got approved:
                    html_message = f'<p>The contract record <data value="{i.number}">{i}</data> was update by {u.full_name_with_email}:</p>'
                    html_message += f'<p>Comment posted by {u.full_name_with_email} to <data value="{i.number}">{i}</data>'
                    html_message += f":</p>{resolution}" if resolution else "."
                    html_message += f'<hr/>To review the entry, please, click here: <a href="{respond_url}">{i}</a>'
                    subject = f"Contract {i} {d.document_type} {d} was {d.state} by {u.full_name_with_email}"
                if not document_action or document_action != "accept":
                    send_mail(
                        request=self.request,
                        subject=subject,
                        html_message=html_message,
                        cc=[u.full_email_address],
                        recipients=recipients,
                        thread_index=i.thread_index,
                        thread_topic=i.thread_topic,
                    )
                return redirect("contract-update", pk=i.pk)

        if (
            "save_draft" in self.request.POST
            and (
                form.data.get("current_tab") == "#parts"
                or {"duration", "awarded_amount"}.intersection(form.changed_data)
            )
            or "save" in self.request.POST
        ):
            return redirect(self.request.path)

        if "generate_contract" in self.request.POST:
            output = i.to_pdf(request=self.request)
            if i.file:
                i.file.delete()

            if isinstance(output, (PdfWriter, PdfMerger)):
                pdf_content = io.BytesIO()
                output.write(pdf_content)
                pdf_content.seek(0)
                i.file.save(f"{i.number}.pdf", File(pdf_content))
            else:
                with open(output, "rb") as of:
                    i.file.save(f"{i.number}.pdf", File(of))

            return redirect(self.request.path)

        if "post_comment" in self.request.POST:
            token = models.get_unique_mail_token()
            attachment = form.cleaned_data.get("attachment", None)
            if body := form.cleaned_data.get("comment", None):
                body = body.strip()

            if body or attachment:
                with transaction.atomic():
                    comment = i.comments.model.create(
                        contract=i,
                        submitted_by=u,
                        comment=body,
                        attachment=attachment,
                        token=token,
                    )
                    comment.recipients.model.objects.bulk_create(
                        [
                            (
                                comment.recipients.model(comment=comment, user=r, email=r.email)
                                if isinstance(r, models.User)
                                else comment.recipients.model(comment=comment, email=r)
                            )
                            for r in recipients
                        ]
                    )

                respond_url = (
                    self.request.build_absolute_uri(
                        reverse("contract-update", kwargs=dict(pk=i.pk))
                    )
                    + "#correspondence"
                )
                html_message = f'<p>Comment posted by {u.full_name_with_email} to <data value="{i.number}">{i}</data>'
                html_message += f":</p>{body}" if body else "."
                html_message += f'<hr/>To respond to this message, please, click here: <a href="{respond_url}">REPLY</a>'
                send_mail(
                    request=self.request,
                    from_email="contracts",
                    subject=f"Comment posted by {u.full_name_with_email} to {i}",
                    html_message=html_message,
                    cc=[u.full_email_address],
                    attachments=attachment and [attachment],
                    recipients=recipients,
                    thread_index=i.thread_index,
                    thread_topic=i.thread_topic,
                    token=token,
                )

                return redirect(
                    reverse("contract-update", kwargs=dict(pk=self.object.pk)) + "#correspondence"
                )

        return resp


class ContractCreate(NotesMixin, ContractViewMixin, CreateView):

    model = models.Contract
    form_class = forms.ContractForm

    # def post(self, request, *args, **kwargs):
    #     form = self.get_user_form()
    #     if not form.is_valid():
    #         return self.form_invalid(form)
    #     form.save()
    #     reset_cache(self.request)
    #     return super().post(request, *args, **kwargs)

    # def post(self, request, *args, **kwargs):
    #     self.object = None
    #     form = self.get_form()
    #     if form.is_valid():
    #         allocation_fs = self.get_allocation_formset()
    #         return self.form_valid(form)
    #     else:
    #         return self.form_invalid(form)

    # def get_context_data(self, **kwargs):
    #     data = super().get_context_data(**kwargs)

    #     if "user_form" not in kwargs:
    #         kwargs["user_form"] = self.get_user_form()

    #     return data

    def get_initial(self, *args, **kwargs):
        initial = super().get_initial(*args, **kwargs)
        a = self.application
        r = a.round

        initial["application"] = a
        initial["year"] = a.created_at.year
        initial["org"] = a.org
        initial["project_title"] = a.application_title or a.round.title
        initial["start_date"] = timezone.now()
        if r.duration:
            initial["end_date"] = timezone.now() + relativedelta(years=r.duration)

        initial["user"] = self.request.user
        initial["number"] = models.Contract.new_number(application=a)
        initial["fund"] = a.round.scheme.fund or models.Fund.last()
        if research_aims := a.file and a or a.documents.filter(document_type__role="AF").last():
            initial["research_aims"] = research_aims.file
        if project_timeline := a.documents.filter(document_type__role="PT").last():
            initial["project_timeline"] = project_timeline.file
        if proposal_budget := a.budget and a or a.documents.filter(document_type__role="B").last():
            initial["budget"] = initial["proposal_budget"] = a.budget or proposal_budget.file
        return initial

        # u = self.request.user
        # n = (
        #     models.Nomination.where(user=self.request.user, state="submitted")
        #     .order_by("-id")
        #     .first()
        # )
        # if n:
        #     initial["first_name"] = n.first_name or u.first_name
        #     initial["middle_names"] = n.middle_names or u.middle_names
        #     initial["last_name"] = n.last_name or u.last_name
        #     initial["title"] = n.title or u.title
        return initial


class ContractUpdate(LoginRequiredMixin, NotesMixin, ContractViewMixin, UpdateView):

    model = models.Contract
    form_class = forms.ContractForm


class ApplicationList(
    # LoginRequiredMixin, StateInPathMixin, SingleTableView,
    LoginRequiredMixin,
    StateInPathMixin,
    SingleTableMixin,
    FilterView,
):
    model = models.Application
    table_class = tables.ApplicationTable
    extra_context = {"category": "applications"}
    template_name = "table.html"
    filterset_class = filters.ApplicationFilterSet
    paginator_class = django_tables2.paginators.LazyPaginator

    def get(self, request, *args, **kwargs):
        if "outcome_file" in request.GET:

            filterset_class = self.get_filterset_class()
            filterset = self.get_filterset(filterset_class)

            if not filterset.is_bound or filterset.is_valid() or not self.get_strict():
                object_list = filterset.qs
            else:
                object_list = self.get_queryset()

            response = HttpResponse(
                content_type="text/csv",
                headers={
                    "Content-Disposition": 'attachment; filename="outcomes.csv"',
                    "Cache-Control": "no-cache, must-revalidate, max-age=0, post-check=0, pre-check=0",
                    "X-Content-Type-Options": "nosniff",
                },
            )
            writer = csv.writer(response)
            writer.writerow(["NUMBER", "DECISION", "AMOUNT", "START", "END"])
            # Simulate fetching and writing data in chunks
            for a in object_list:
                row_data = [
                    a.number,
                    "Y",
                    (a.awarded_amount or a.requested_amount) or "",
                    a.proposed_start_date and a.proposed_start_date.isoformat() or "",
                    (
                        (a.proposed_start_date + relativedelta(years=a.round.duration, days=-1))
                        if a.proposed_start_date and a.round.duration
                        else ""
                    ),
                ]
                writer.writerow(row_data)

            return response

        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if {"duration", "awarded_amount", "application"}.issubset(request.POST):
            duration = int(request.POST["duration"])
            application = models.Application.get_or_404(pk=int(request.POST["application"]))
            awarded_amount = request.POST["awarded_amount"] or None
            start_date = request.POST["start_date"] or None
            end_date = request.POST["end_date"] or None
            if start_date:
                start_date = parse_date(start_date)
            if end_date:
                end_date = parse_date(end_date)
            try:
                contract = models.Contract.create_from_application(
                    application=application,
                    duration=duration,
                    awarded_amount=Decimal(awarded_amount) if awarded_amount else None,
                    start_date=start_date,
                    end_date=end_date,
                )
            except Exception as ex:
                capture_exception(ex)
                messages.error(request, getattr(ex, "message", str(ex)))
                return redirect(request.path)
            else:
                reset_cache(self.request)
                url = reverse("contract-update", kwargs={"pk": contract.pk})
                messages.info(
                    request, f'Contract <a href="{url}">{contract.number}</a> was created.'
                )
                return redirect(url)

        if "outcome_file" in request.FILES:
            file = request.FILES["outcome_file"]
            content_type, _ = mimetypes.guess_type(file.name)
            outcomes = tablib.Dataset()
            if file.content_type == "text/csv" or content_type == "text/csv":
                first_line = file.readline().decode()
                file.seek(0)
                outcomes.load(
                    file.read().decode(), format="csv", headers="number" in first_line.lower()
                )
            elif file.content_type == "application/vnd.oasis.opendocument.spreadsheet":
                outcomes.load(file.file, format="ods")
            elif (
                file.content_type
                == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ):
                outcomes.load(file.file, format="xlsx")
            funded_count = 0
            archived_count = 0
            error_messages = []
            contracts = []
            applications = []
            try:
                with transaction.atomic():
                    for line in outcomes:
                        number, decision, *rest = line
                        decision = decision.strip().upper()
                        number = number.strip()
                        a = Application.where(number=number).last()
                        if a:
                            if decision in ["Y", "1", "YES"]:
                                awarded_amount = Decimal(rest[0]) if rest and rest[0] else None
                                start_date = (
                                    parse_date(rest[1]) if len(rest) > 1 and rest[1] else None
                                )
                                end_date = (
                                    parse_date(rest[2]) if len(rest) > 2 and rest[2] else None
                                )
                                if a.state != "funded":
                                    contracts.append(
                                        a.fund(
                                            request=request,
                                            awarded_amount=awarded_amount,
                                            start_date=start_date,
                                            end_date=end_date,
                                            description=f"From '{file.name}' by {request.user}",
                                        )
                                    )
                                    a.save()
                                    funded_count += 1
                                    applications.append(a)
                                if not a.contracts.exists():
                                    contracts.append(
                                        models.Contract.create_from_application(
                                            application=a,
                                            awarded_amount=awarded_amount,
                                            start_date=start_date,
                                            end_date=end_date,
                                        )
                                    )
                            elif decision in ["N", "0", "NO", "NOT"]:
                                if a.state != "archived":
                                    a.archive(
                                        request=request,
                                        description=f"From '{file.name}' by {request.user}",
                                    )
                                    archived_count += 1
                                    a.save()
                            else:
                                error_messages.append(f"Incorrect data: {line}")
                        else:
                            error_messages.append(
                                f"Failed to find the application with the number {number}"
                            )

                if funded_count:
                    contracts = ", ".join(
                        f'<a href="{c.detail_url}" target="_blank">{c.number}</a>'
                        for c in contracts
                    )
                    applications = ", ".join(
                        f'<a href="{a.detail_url}" target="_blank">{a.number}</a>'
                        for a in applications
                    )
                    if funded_count == 1:
                        messages.info(
                            request,
                            (
                                f"{funded_count} application was marked <b>funded</b>: {applications}."
                                + f" New contract initiated: {contracts}"
                                if contracts
                                else ""
                            ),
                        )
                    else:
                        messages.info(
                            request,
                            (
                                f"{funded_count} applications were marked <b>funded</b>: {applications}."
                                + f" New contracts initiated: {contracts}"
                                if contracts
                                else ""
                            ),
                        )
                if archived_count:
                    messages.info(
                        request, f"{archived_count} application(s) were marked <b>archived</b>."
                    )
                for msg in error_messages:
                    messages.error(request, msg)
            except Exception as ex:
                capture_exception(ex)
                messages.error(request, getattr(ex, "message", str(ex)))
                return redirect(request.path)

        if funded_count:
            reset_cache(self.request)
            return redirect("applications-with-state", state="funded")

        return redirect(request.path)

    def get_queryset(self, *args, **kwargs):
        u = self.request.user
        q = super().get_queryset(*args, **kwargs)
        q = models.Application.user_applications(
            u, round=self.request.GET.get("round"), queryset=q, request=self.request
        )
        if u.is_staff or u.is_superuser or u.is_site_staff:
            return q.prefetch_related("contracts")
        return q

    def get_table_kwargs(self):
        if not self.request.user.is_admin:
            return {"exclude": ("contract",)}
        return super().get_table_kwargs()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        request = self.request
        u = request.user
        # if not (
        #     u.is_staff
        #     or u.is_superuser
        #     or (
        #         "round" in self.request.GET
        #         and models.Panellist.where(
        #             round=self.request.GET["round"], user=self.request.user
        #         ).exists()
        #     )
        # ):
        #     context["filter_disabled"] = True
        #     # self.table_pagination = False
        # else:
        #     # update application counts:
        #     # if (filter := context.get("filter")) and filter.is_bound:
        #     if filter := context.get("filter"):
        #         application_draft_count = filter.qs.filter(state__in=["new", "draft"]).count()
        #         application_submitted_count = filter.qs.filter(
        #             state__in=["submitted", "approved", "cancelled"]
        #         ).count()
        #         context["application_count"] = (
        #             application_draft_count + application_submitted_count
        #         )
        #         context["application_draft_count"] = application_draft_count
        #         context["application_submitted_count"] = application_submitted_count

        if (state := self.request.path.split("/")[-1]) and state in [
            "draft",
            "submitted",
            "approved",
            "accepted",
            "cancelled",
        ]:
            context["state"] = state
        if round_id := request.GET.get("round") or request.GET.get("round_filter"):
            context["round"] = models.Round.get(round_id)

        if state == "in_review" and u.is_admin:
            params = self.request.GET.copy()
            params["outcome_file"] = "selected"
            url = f"{self.request.path}?{params.urlencode()}"
            context["outcome_file_url"] = url

        return context


@login_required
def photo_identity(request):
    """Redirect to the application section for a photo identity resubmission."""
    iv = (
        models.IdentityVerification.where(
            ~Q(state="accepted"), user=request.user, application__isnull=False
        )
        .order_by("-id")
        .first()
    )
    if iv and iv.application:
        application = iv.application
    else:
        application = Application.where(
            Q(photo_identity__isnull=True) | Q(photo_identity=""),
            state__in=["new", "draft"],
            submitted_by=request.user,
        ).first()
    url = request.build_absolute_uri(
        reverse("application-update", kwargs=dict(pk=application.id)) + "?verification=1"
    )
    return redirect(url)


class IdentityVerificationFileView(LoginRequiredMixin, PrivateStorageDetailView):
    model = models.IdentityVerification
    model_file_field = "file"

    # def get_queryset(self):
    #     return super().get_queryset().filter(...)

    def can_access_file(self, private_file):
        # When the object can be accessed, the file may be downloaded.
        # This overrides PRIVATE_STORAGE_AUTH_FUNCTION
        return True


class IdentityVerificationView(LoginRequiredMixin, UpdateView):
    model = models.IdentityVerification
    template_name = "form.html"
    form_class = forms.IdentityVerificationForm

    def dispatch(self, request, *args, **kwargs):
        u = request.user
        if u.is_authenticated and not (u.is_staff or u.is_superuser or u.is_site_staff):
            messages.error(request, _("You do not have permissions to access this page."))
            return redirect("index")
        return super().dispatch(request, *args, **kwargs)

    def has_permission(self):
        return self.request.user.is_staff and super().has_permission()

    def get_success_url(self):
        return reverse("index")

    def form_valid(self, form):
        resp = super().form_valid(form)
        iv = self.object
        if "accept" in self.request.POST:
            iv.accept(request=self.request)
            iv.save()
        elif "reject" in self.request.POST:
            iv.request_resubmission(request=self.request)
            iv.save()
            messages.info(
                self.request, _("Request to resubmit the ID sent to <b>%s</b>") % iv.user.email
            )
        return resp


def turn_off_wizard(request):
    if "wizard" in request.session:
        del request.session["wizard"]
    if "wizard-views" in request.session:
        del request.session["wizard-views"]
    request.session.modified = True


class ProfileSectionFormSetView(LoginRequiredMixin, ModelFormSetView):
    template_name = "profile_section.html"
    exclude = ()
    section_views = [
        "profile-employments",
        "profile-career-stages",
        "profile-external-ids",
        "profile-cvs",
        "profile-academic-records",
        "profile-recognitions",
        "profile-professional-records",
        # "profile-protection-patterns",
    ]

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not Person.where(user=self.request.user).exists():
            if not request.session.get("wizard"):
                request.session["wizard"] = True
                if request.site_id in [1, 7]:
                    section_views = self.section_views.copy()
                    request.session["wizard-views"] = section_views
                else:
                    request.session["wizard-views"] = self.section_views.copy()
                request.session.modified = True
            return redirect("onboard")
        return super().dispatch(request, *args, **kwargs)

    def get_defaults(self):
        """Default values for a form."""
        return dict(person=self.request.user.person)

    def get_formset(self):
        klass = super().get_formset()
        defaults = self.get_defaults()

        class Klass(klass):
            def get_form_kwargs(self, index):
                kwargs = super().get_form_kwargs(index)
                if "initial" not in kwargs:
                    kwargs["initial"] = defaults
                else:
                    kwargs["initial"].update(defaults)
                return kwargs

        return Klass

    def get_factory_kwargs(self):
        kwargs = super().get_factory_kwargs()
        widgets = kwargs.get("widgets", {})
        widgets.update(
            {
                "person": HiddenInput(),
                "DELETE": Submit("submit", "DELETE"),
            }
        )
        kwargs["widgets"] = widgets
        kwargs["can_delete"] = True
        return kwargs

    def post(self, request, *args, **kwargs):
        """Check the POST request call"""
        if "load_from_orcid" in request.POST:
            orcidhelper = OrcidHelper(request.user, self.orcid_sections)
            total_records_fetched, user_has_linked_orcid = orcidhelper.fetch_and_load_orcid_data()
            if user_has_linked_orcid:
                messages.success(
                    self.request, _(" %s ORCID records imported") % total_records_fetched
                )
                return HttpResponseRedirect(self.request.path_info)
            else:
                messages.warning(
                    self.request,
                    _(
                        "In order to import ORCID profile, please, "
                        "link your ORCID account to your portal account."
                    ),
                )
                return redirect(
                    reverse("socialaccount_connections")
                    + "?next="
                    + quote(request.get_full_path())
                )
        return super().post(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        person = self.request.user.person
        context["person"] = person
        previous_step = next_step = None
        # if not profile.is_completed:
        #     self.request.session["wizard"] = True
        url_name = self.request.resolver_match.url_name
        context["section_name"] = {
            "profile-employments": _("Organisation Affiliations"),
            "profile-professional-records": _("Professional Bodies"),
            "profile-career-stages": _("Career Stages"),
            "profile-external-ids": _("External IDs"),
            "profile-cvs": _("Curriculum Vitae"),
            "profile-academic-records": _("Academic Records"),
            "profile-recognitions": _("Prizes and/or Medals"),
        }.get(url_name)
        if self.request.session.get("wizard") or self.request.site_id in (1, 7):
            view_idx = self.section_views.index(url_name)
            if view_idx > 0:
                previous_step = self.section_views[view_idx - 1]
                context["previous_step"] = previous_step
            if view_idx < len(self.section_views):
                next_step = self.section_views[view_idx - 1]
                context["next_step"] = next_step
            context["progress"] = ((view_idx + 1) * 100) / (len(self.section_views) + 1)
        context["helper"] = forms.ProfileSectionFormSetHelper(
            person=person,
            previous_step=previous_step,
            next_step=next_step,
            wizard="wizard" in self.request.session,
        )
        return context

    def get_success_url(self):
        if self.request.session.get("wizard") or self.request.site_id in (1, 7):
            view_idx = self.section_views.index(self.request.resolver_match.url_name)
            if "previous" in self.request.POST:
                return reverse(self.section_views[view_idx - 1])
            if "next" in self.request.POST and view_idx < len(self.section_views) - 1:
                return reverse(self.section_views[view_idx + 1])
            if self.request.site_id in (1, 7):
                return reverse("start")
            return reverse("profile-protection-patterns")
        return super().get_success_url()

    def turn_off_wizard(self):
        turn_off_wizard(self.request)

    def formset_invalid(self, formset):
        return super().formset_invalid(formset)

    def formset_valid(self, formset):
        request = self.request
        url_name = request.resolver_match.url_name
        try:
            resp = super().formset_valid(formset)
            success_url = self.success_url
            if "complete" in request.POST:
                self.turn_off_wizard()
                if not success_url:
                    self.success_url = reverse("home")
            elif request.session.get("wizard"):
                if (wizard_views := request.session.get("wizard-views", None)) is None:
                    wizard_views = request.session["wizard-views"] = (
                        ProfileSectionFormSetView.section_views.copy()
                    )
                if url_name in wizard_views:
                    del wizard_views[wizard_views.index(url_name)]
                    if not wizard_views:
                        self.turn_off_wizard()
                    else:
                        request.session["wizard-views"] = wizard_views
                        request.session.modified = True
        except ProtectedError as ex:
            if url_name == "profile-cvs" and hasattr(formset, "deleted_objects"):
                messages.error(
                    request,
                    _(
                        "You cannot delete a CV that has been used as part of an application (%s). "
                        "<br/>If you are trying to update your CV, you can replace the old with a new document. "
                        "If you are trying to delete an old application, please let us know and we can do this for you."
                    )
                    % ", ".join(
                        (
                            o.number
                            if isinstance(o, models.Application)
                            else o.referee.application.number
                        )
                        for o in ex.protected_objects
                    ),
                )
                return redirect(request.path_info)

        if getattr(formset, "deleted_objects", 0):
            if len(formset.deleted_objects) == 1:
                messages.info(
                    request,
                    _("Record deleted: %s") % formset.deleted_objects[0],
                )
            elif len(formset.deleted_objects) > 1:
                messages.info(
                    request,
                    _("%d records deleted") % len(formset.deleted_objects),
                )
        elif wizard_views := request.session.get("wizard-views", []):
            if "profile-employments" in wizard_views:
                msg = _("You have not completed the affiliation section.")
            elif "profile-professional-records" in wizard_views:
                msg = _("You have not completed the professional body section.")
            elif "profile-career-stages" in wizard_views:
                msg = _("You have not completed the career stage section.")
            elif "profile-external-ids" in wizard_views:
                msg = _("You have not completed the external ID section.")
            elif "profile-cvs" in wizard_views:
                msg = _("You have not completed the CV section.")
            elif "profile-academic-records" in wizard_views:
                msg = _("You have not completed the academic record section.")
            elif "profile-recognitions" in wizard_views:
                msg = _("You have not completed the recognition section.")
            messages.info(request, "%s %s" % (msg, _("Please complete or skip it.")))

        check_selected_orgs(request)
        return resp


class ProfileCareerStageFormSetView(ProfileSectionFormSetView):
    model = PersonCareerStage
    formset_class = forms.ProfileCareerStageFormSet
    factory_kwargs = {
        "widgets": {
            "year_achieved": widgets.DateInput(attrs={"class": "yearpicker", "min": 1950}),
            "career_stage": widgets.Select(
                attrs={
                    "data-placeholder": _("Choose a career stage ..."),
                    "placeholder": _("Choose a career stage ..."),
                    "data-required": 1,
                    "oninvalid": "this.setCustomValidity('%s')" % _("Career stage is required"),
                    "oninput": "this.setCustomValidity('')",
                }
            ),
        }
    }

    def get_queryset(self):
        return self.model.where(person=self.request.user.person).order_by("year_achieved")


class ProfilePersonIdentifierFormSetView(ProfileSectionFormSetView):
    model = models.PersonPersonIdentifier
    # formset_class = forms.ProfilePersonIdentifierFormSet
    orcid_sections = ["externalid"]
    form_class = forms.ProfilePersonIdentifierForm

    def get_factory_kwargs(self):
        kwargs = super().get_factory_kwargs()
        kwargs.update(
            {
                "widgets": {
                    "person": HiddenInput(),
                    "code": autocomplete.ModelSelect2(
                        "person-identifier-autocomplete",
                        attrs={
                            "data-placeholder": _("Choose an identifier type or a new one..."),
                            "placeholder": _("Choose an identifier type or a new one ..."),
                            "data-required": 1,
                            "oninvalid": "this.setCustomValidity('%s')"
                            % _("Identifier type is required"),
                            "oninput": "this.setCustomValidity('')",
                        },
                    ),
                    # "code": widgets.Select(
                    #     attrs={
                    #         # "required": True,
                    #         "data-placeholder": _("Choose an identifier type ..."),
                    #         "placeholder": _("Choose an identifier type ..."),
                    #         "data-required": 1,
                    #         "oninvalid": "this.setCustomValidity('%s')"
                    #         % _("Identifier type is required"),
                    #         "oninput": "this.setCustomValidity('')",
                    #     }
                    # ),
                    "value": TextInput(
                        attrs={
                            "placeholder": _("Enter an identifier or a reference ..."),
                            "data-placeholder": _("Choose an identifier value ..."),
                            "data-required": 1,
                            "oninvalid": "this.setCustomValidity('%s')"
                            % _("Identifier value is required"),
                            "oninput": "this.setCustomValidity('')",
                        }
                    ),
                },
            }
        )
        # widgets = {
        #     "person": HiddenInput(),
        #     "code": autocomplete.ModelSelect2(
        #         "person-identifier-autocomplete", attrs={"required": True}
        #     ),
        #     # "code": Select(attrs={"data-placeholder": _("Choose an identifier type ...")}),
        #     "value": TextInput(
        #         attrs={
        #             "placeholder": _("Enter an identifier value ..."),
        #             "data-placeholder": _("Choose an identifier value ..."),
        #         }
        #     ),
        # }
        return kwargs

    def get_queryset(self):
        return self.model.where(person=self.request.user.person).order_by("code")

    def get_context_data(self, **kwargs):
        """Get the context data"""
        context = super().get_context_data(**kwargs)
        context["form_show_errors"] = False
        context.get("helper").add_input(
            Submit(
                "load_from_orcid",
                _("Import from ORCiD"),
                css_class="btn-orcid",
            )
        )
        return context


class ProfileAffiliationsFormSetView(ProfileSectionFormSetView):
    model = models.Affiliation
    # formset_class = forms.modelformset_factory(models.Affiliation, exclude=(), can_delete=True,)
    exclude = ["email"]

    def get_factory_kwargs(self):
        kwargs = super().get_factory_kwargs()
        kwargs.update(
            {
                "widgets": {
                    "org": autocomplete.ModelSelect2(
                        "org-autocomplete",
                        attrs={
                            "data-placeholder": _("Choose an organisation ..."),
                            "placeholder": _("Choose an organisation ..."),
                            "data-required": 1,
                            "oninvalid": "this.setCustomValidity('%s')"
                            % _("Organisation is required"),
                            "oninput": "this.setCustomValidity('')",
                        },
                    ),
                    "role": TextInput(
                        attrs={"placeholder": _("student, postdoc, etc.")},
                    ),
                    "type": HiddenInput(),
                    "person": HiddenInput(),
                    "qualification": HiddenInput(),
                    "start_date": forms.DateInput(),
                    "end_date": forms.DateInput(),
                },
                "labels": {"role": _("Position")},
            }
        )
        return kwargs

    def get_queryset(self):
        # if there is an invitation or nomination reuse it:
        p = self.request.user.person
        q = p.affiliations.all()
        if not q.count() > 0:
            data = (
                models.Invitation.where(email=self.request.user.email).order_by("-id").first()
                or models.Nomination.where(user=self.request.user).order_by("-id").first()
            )
            nomination = getattr(data, "nomination", data)
            if data and data.org:
                models.Affiliation.create(
                    person=p,
                    org=data.org,
                    type=models.AFFILIATION_TYPES.EMP,
                    role=getattr(nomination, "position", ""),
                )

        # return self.model.where(
        #     person=self.request.user.person, type__in=self.affiliation_type.values()
        # ).order_by(
        #     "start_date",
        #     "end_date",
        # )

        return q.filter(type__in=self.affiliation_type.values()).order_by("start_date", "end_date")

    def get_defaults(self):
        """Default values for a form."""
        defaults = super().get_defaults()
        defaults["type"] = next(iter(self.affiliation_type.values()))
        return defaults

    def get_context_data(self, **kwargs):
        """Get the context data"""

        context = super().get_context_data(**kwargs)
        context.get("helper").add_input(
            Submit("load_from_orcid", _("Import from ORCiD"), css_class="btn-orcid")
        )
        return context


class ProfileEmploymentsFormSetView(ProfileAffiliationsFormSetView):
    orcid_sections = ["employment"]
    affiliation_type = {"employment": "EMP"}


class ProfileEducationsFormSetView(ProfileAffiliationsFormSetView):
    affiliation_type = {"education": "EDU"}


class ProfileProfessionalFormSetView(ProfileAffiliationsFormSetView):
    orcid_sections = ["membership", "service"]
    affiliation_type = {"membership": "MEM", "service": "SER"}

    def get_factory_kwargs(self):
        kwargs = super().get_factory_kwargs()
        kwargs.update(
            {
                "widgets": {
                    "org": autocomplete.ModelSelect2(
                        "org-autocomplete",
                        attrs={
                            # "placeholder": _(""),
                            "data-required": 1,
                            "oninvalid": "this.setCustomValidity('%s')"
                            % _("The organisation is required ..."),
                            "oninput": "this.setCustomValidity('')",
                        },
                    ),
                    "type": HiddenInput(),
                    "person": HiddenInput(),
                    "start_date": forms.DateInput(),
                    "end_date": forms.DateInput(),
                },
                "labels": {
                    "role": gettext_lazy("Professional Membership"),
                    "qualification": gettext_lazy("Professional Qualification"),
                },
            }
        )
        return kwargs


class Unaccent(Func):
    function = "unaccent"


class PersonCodeAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):

    def get_queryset(self):
        q = self.model.objects.all()
        if self.q:
            q = q.filter(code__istartswith=self.q)
        return q.order_by("code")

    def has_add_permission(self, request):
        return True

    def get_result_label(self, result):
        if isinstance(result, models.Person):
            return result.code
        return result

    def get_result_value(self, result):
        if isinstance(result, models.Person):
            return result.code
        return result

    def create_object(self, text):
        return text


class DocumentTypeAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):

    def get_queryset(self):
        q = self.model.objects.all()
        if scheme := self.forwarded.get("scheme"):
            q = q.filter(required_documents__round__scheme_id=scheme)
        if (referer := self.request.META.get("HTTP_REFERER")) and (
            m := re.search(r"round/(\d+)/change", referer)
        ):
            q = q.filter(required_documents__round_id=m.group(1))
        if self.q:
            q = q.filter(name__istartswith=self.q)
        return q.order_by("name").distinct()

    def has_add_permission(self, request):
        return False


class TitleAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return models.Title.objects.none()
        if not self.q or not self.request.user.is_authenticated:
            q = models.Title.objects.all()
        else:
            q = models.Title.objects.all().filter(
                Q(name_en__istartswith=self.q) | Q(name_mi__istartswith=self.q)
            )
        lang = self.request.LANGUAGE_CODE
        return q.order_by(f"name_{lang or 'en'}")

    def has_add_permission(self, request):
        # Authenticated users can add new records
        return True  # request.user.is_authenticated


class TagAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):

    # def get_queryset(self):
    #     qs = models.Tag.objects.all()

    #     if self.q:
    #         qs = qs.filter(name__istartswith=self.q)

    #     return qs

    def has_add_permission(self, request):
        return True  # request.user.is_authenticated

    # def get_create_option(self, context, q):
    #     return []


class ResearchPriorityAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):

    def get_queryset(self):
        qs = self.model.objects.all()

        round = self.forwarded.get("round", "")
        if round and isinstance(round, str):
            round = round.strip()
        if not round:
            if application := self.forwarded.get("application", "").strip():
                round = (
                    models.Application.where(pk=application)
                    .values_list("round_id", flat=True)
                    .first()
                )
            elif contract := self.forwarded.get("contract", "").strip():
                round = (
                    models.Contract.where(pk=contract)
                    .values_list("application__round_id", flat=True)
                    .first()
                )

        if round:
            qs = (
                qs.filter(
                    items__content_type=ContentType.objects.get_for_model(models.Round),
                    items__object_id=round,
                )
                .distinct()
                .order_by("name")
            )

        if self.q:
            qs = qs.filter(name__istartswith=self.q)

        return qs

    def has_add_permission(self, request):
        return request.user.is_admin

    # def get_create_option(self, context, q):
    #     return []


class UserAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):

    search_fields = ["^email", "^first_name", "^last_name"]

    def has_add_permission(self, request):
        # Authenticated users can add new records
        return False  # request.user.is_authenticated


class KeywordAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):
    def get_queryset(self):
        # Don't forget to filter out results depending on the visitor !
        if not self.request.user.is_authenticated:
            # return models.Keyword.objects.none()
            return self.model.objects.none()
        if not self.q or not self.request.user.is_authenticated:
            # return models.Keyword.objects.all()
            return self.model.objects.all()

        # return models.Keyword.objects.all().filter(name__istartswith=self.q)
        return self.model.objects.all().filter(name__istartswith=self.q)

    def create_object(self, text):
        for t in [t.strip() for t in text.split(",")][::-1]:
            if t:
                kw, _ = self.model.get_or_create(**{self.create_field: t})
        if t and kw:
            return kw

    def has_add_permission(self, request):
        # Authenticated users can add new records
        return True  # request.user.is_authenticated


class EthnicityAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):
    def has_add_permission(self, request):
        # Authenticated users can add new records
        return False  # request.user.is_authenticated

    def get_queryset(self):
        if self.q:
            if django.db.connection.vendor == "sqlite":
                return models.Ethnicity.where(description__icontains=self.q).order_by(
                    "description"
                )
            else:
                return (
                    models.Ethnicity.objects.annotate(ia_description=Unaccent("description"))
                    .filter(ia_description__icontains=Unaccent(Value(self.q)))
                    .order_by("ia_description")
                )
        return models.Ethnicity.objects.order_by("description")


class IwiGroupAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):
    def has_add_permission(self, request):
        # Authenticated users can add new records
        return False  # request.user.is_authenticated

    def get_queryset(self):
        if self.q:
            if django.db.connection.vendor == "sqlite":
                return models.IwiGroup.where(description__icontains=self.q).order_by("description")
            else:
                return (
                    models.IwiGroup.objects.annotate(ia_description=Unaccent("description"))
                    .filter(ia_description__icontains=Unaccent(Value(self.q)))
                    .order_by("ia_description")
                )
        return models.IwiGroup.objects.order_by("description")


class OrgEmailAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):
    def has_add_permission(self, request):
        # return False
        return True

    def get_result_label(self, result):
        if isinstance(result, EmailAddress):
            return f"{result.user.full_name} <{result.email}>"
        return result

    def get_result_value(self, result):
        if isinstance(result, EmailAddress):
            return result.email
        return result

    def create_object(self, text):
        if referer := self.request.META.get("HTTP_REFERER"):
            if m := re.search(r"contracts/(\d+)/", referer):
                if (
                    contract := models.Contract.where(pk=m.group(1)).first()
                ) and contract.host_contact_email != text:
                    contract.host_contact_email = text
                    contract.save(update_fields=["host_contact_email", "updated_at"])
            elif m := re.search(r"contracts/([A-Za-z0-9:-]+)/", referer):
                if (
                    contract := models.Contract.where(number=m.group(1)).first()
                ) and contract.host_contact_email != text:
                    contract.host_contact_email = text
                    contract.save(update_fields=["host_contact_email", "updated_at"])

        return text

    def get_queryset(self):
        u = self.request.user
        q = EmailAddress.objects.filter(
            Q(
                user__person__affiliations__org__in=Subquery(
                    u.person.affiliations.all().values_list("org")
                )
            )
            | Q(
                user__research_offices__org__in=Subquery(
                    u.person.affiliations.all().values_list("org")
                )
            )
        )
        if self.q:
            q = q.filter(
                Q(email__istartswith=self.q)
                | Q(user__first_name__istartswith=self.q)
                | Q(user__last_name__istartswith=self.q)
            )
        return q.order_by("email").distinct()


class CityAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):
    def has_add_permission(self, request):
        # return False
        return True

    def get_result_label(self, result):
        if isinstance(result, Address):
            return result.city
        return result or ""

    def get_result_value(self, result):
        if isinstance(result, Address):
            return result.city
        return result or ""

    def create_object(self, text):
        return text

    def get_queryset(self):
        q = Address.objects.annotate(city_name=Trim("city")).values_list("city_name", flat=True)
        if country := self.forwarded.get("country", "").strip():
            q = q.filter(country=country)
        if self.q:
            q = q.filter(city_name__istartswith=self.q)
        return q.order_by("city_name").distinct()


class OrgAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):

    def create_object(self, text):
        o, _ = self.model.get_or_create(defaults={"is_active": False}, **{self.create_field: text})
        org_url = self.request.build_absolute_uri(
            reverse("admin:portal_organisation_change", args=[o.pk])
        )
        models.async_task(
            models.notify_site_staff_about_new_org,
            sync=True,
            site_id=self.request.site_id,
            org_id=o.pk,
            by_id=self.request.user.pk,
            org_url=org_url,
        )
        return o

    def has_add_permission(self, request):
        # Authenticated users can add new records
        return not ("nominator" in self.forwarded and self.request.site_id in [2, 4, 5])
        # return True  # request.user.is_authenticated

    def get_result_label(self, result):
        if isinstance(result, models.Organisation):
            return result.name
        return result[1]

    def get_result_value(self, result):
        if isinstance(result, models.Organisation):
            return result.pk
        return result[0]

    def get_queryset(self):
        nominator = self.forwarded.get("nominator") if self.request.site_id in [2, 4, 5] else None
        user = self.forwarded.get("user")
        contract = self.forwarded.get("contract")
        try:
            if not user and contract:
                if not isinstance(contract, models.Contract):
                    contract = models.Contract.get(contract)
                user = contract.pi
        except:
            pass
        q = models.Organisation.search_query(
            self.q, nominator=nominator, user=user, country=self.forwarded.get("country", None)
        )
        return q


class OrgNameAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):

    def has_add_permission(self, request):
        return True

    def get_result_label(self, result):
        if isinstance(result, models.Organisation):
            return result.name
        if isinstance(result, tuple):
            return result[1]
        return result

    def get_result_value(self, result):
        if isinstance(result, models.Organisation):
            return result.name
        if isinstance(result, tuple):
            return result[1]
        return result

    def create_object(self, text):
        return text

    def get_queryset(self):
        nominator = self.forwarded.get("nominator")
        user = self.forwarded.get("user")
        contract = self.forwarded.get("contract")
        try:
            if not user and contract:
                if not isinstance(contract, models.Contract):
                    contract = models.Contract.get(contract)
                user = contract.pi
        except:
            pass
        q = models.Organisation.search_query(self.q, nominator=nominator, user=user)
        if country := self.forwarded.get("country"):
            q = q.filter(
                Q(address__country_id=country)
                | Q(address__country__isnull=True)
                | Q(address__isnull=True)
            )
        return q


class CountryAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):
    def has_add_permission(self, request):
        # Authenticated users can add new records
        return False  # request.user.is_authenticated

    def get_result_label(self, result):
        if isinstance(result, models.Country):
            return result.name
        return result[1]

    def get_result_value(self, result):
        if isinstance(result, models.Country):
            return result.pk
        return result[0]

    def get_queryset(self):
        q = models.Country.objects.values_list("code", "name")
        if self.q:
            q = q.filter(name__icontains=self.q)
        return q.order_by("name")


class AwardAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):
    def has_add_permission(self, request):
        # Authenticated users can add new records
        return True  # request.user.is_authenticated

    def get_queryset(self):
        if self.q:
            return models.Award.where(name__icontains=self.q).order_by("-id", "name")
        return models.Award.objects.order_by("-id", "name")


class QualificationAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):
    def has_add_permission(self, request):
        # Authenticated users can add new records
        return True  # request.user.is_authenticated

    def get_queryset(self):
        if self.q:
            return models.Qualification.where(description__icontains=self.q).order_by(
                "description"
            )
        return models.Qualification.objects.order_by("description")

    def create_object(self, text):
        return self.get_queryset().get_or_create(
            defaults={"is_nzqf": False}, **{self.create_field: text}
        )[0]


class PersonIdentifierAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):
    def has_add_permission(self, request):
        # Authenticated users can add new records
        return True  # request.user.is_authenticated

    def get_queryset(self):
        if self.q:
            return models.PersonIdentifierType.where(description__icontains=self.q).order_by(
                "description"
            )
        return models.PersonIdentifierType.objects.order_by("description")


class FosAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):
    def has_add_permission(self, request):
        # Authenticated users can add new records
        return True  # request.user.is_authenticated

    def get_queryset(self):
        q = models.FieldOfStudy.objects
        if self.q:
            q = q.filter(description__icontains=self.q).order_by("description")
        return q.order_by("description")


class ForAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):
    version = "2.0.0"  # Current version

    def has_add_permission(self, request):
        # Authenticated users can add new records
        return False  # request.user.is_authenticated

    def get_queryset(self):
        if (t := self.forwarded.get("type")) and (pk := self.forwarded.get("pk")):
            q = self.model.objects.filter(
                Q(version=self.version)
                | (Q(applications=pk) if t == "application" else Q(reports=pk))
            )
        else:
            q = self.model.objects.filter(version=self.version)
        if self.q:
            if self.q.isdecimal():
                q = q.filter(code__contains=self.q)
            else:
                q = q.filter(description__icontains=self.q)
            return q.order_by("description")
        return q


class SeoAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):
    version = "2.0.0"  # Current version

    def has_add_permission(self, request):
        # Authenticated users can add new records
        return False  # request.user.is_authenticated

    def get_queryset(self):
        # if country := self.forwarded.get("country", "").strip():

        if (t := self.forwarded.get("type")) and (pk := self.forwarded.get("pk")):
            q = self.model.objects.filter(
                Q(version=self.version)
                | (Q(applications=pk) if t == "application" else Q(reports=pk))
            )
        else:
            q = self.model.objects.filter(version=self.version)
        if self.q:
            if self.q.isdecimal():
                q = q.filter(code__contains=self.q)
            else:
                q = q.filter(description__icontains=self.q)
            return q.order_by("description")
        return q


class PanelAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):
    def has_add_permission(self, request):
        # Authenticated users can add new records
        return False  # request.user.is_authenticated

    def get_queryset(self):
        q = models.Panel.where(state="active")
        if self.q:
            q = q.filter(Q(description__istartswith=self.q) | Q(code__istartswith=self.q))
        return q.order_by("code")


class ReportingScheduleEntryAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):
    def has_add_permission(self, request):
        return False

    def get_queryset(self):

        q = super().get_queryset()
        if contract := self.forwarded.get("contract"):
            # select only people affiliated with the org
            q = q.filter(contract=contract)
        if "exclude_taken" in self.forwarded:
            q = q.filter(report__isnull=True)
        return q


class PersonAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):
    def has_add_permission(self, request):
        return False

    def get_queryset(self):

        q = super().get_queryset()
        if org := self.forwarded.get("org"):
            # select only people affiliated with the org
            q = q.filter(affiliations__org=org).distinct()
        if org_code := self.forwarded.get("org_code"):
            # select only people affiliated with the org
            q = q.filter(affiliations__org__code=org_code).distinct()
        if affiliation_type := self.forwarded.get("affiliation_type"):
            q = q.filter(affiliations__type=affiliation_type).distinct()
        if self.q:
            q = q.filter(
                Q(code__istartswith=self.q)
                | Q(email__istartswith=self.q)
                | Q(last_name__istartswith=self.q)
                | Q(user__last_name__istartswith=self.q)
                | Q(user__email__istartswith=self.q)
            )
        return q


class RequiredDocumentAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):
    def has_add_permission(self, request):
        return False

    def get_queryset(self):

        q = super().get_queryset()
        if scheme := self.forwarded.get("scheme"):
            # select only people affiliated with the org
            q = q.filter(round_scheme=scheme)
        if round := self.forwarded.get("round"):
            # select only people affiliated with the org
            return q.filter(round=round)
        elif (referer := self.request.META.get("HTTP_REFERER")) and (
            m := re.search(r"round/(\d+)/change", referer)
        ):
            q = q.filter(required_documents__round_id=m.group(1))
        return q


class ChangeTypeAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):

    # search_fields = ["description", "definition"]
    search_fields = ["description"]

    def has_add_permission(self, request):
        return False

    # def get_queryset(self):
    #     qs = super().get_queryset()
    #     return qs


class ChangeCategoryAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):
    def has_add_permission(self, request):
        return False

    def get_queryset(self):

        q = super().get_queryset()
        if parents := self.forwarded.get("parents"):
            q = q.filter(parent__in=parents)
        elif types := self.forwarded.get("types"):
            q = q.filter(type__in=types)
        if level := self.forwarded.get("level"):
            if level == "1":
                q = q.filter(parent__isnull=True)
            if level == "2":
                q = q.filter(parent__parent__isnull=True)
            else:
                q = q.filter(parent__parent__parent__isnull=True)
        return q


class ProfileCurriculumVitaeFormSetView(ProfileSectionFormSetView):
    model = models.CurriculumVitae
    # formset_class = forms.modelformset_factory(models.Affiliation, exclude=(), can_delete=True,)
    factory_kwargs = {
        "exclude": ["converted_file"],
        # "labels": {"title": _("Title or name")},
    }

    def get_factory_kwargs(self):
        kwargs = super().get_factory_kwargs()
        kwargs.update(
            {
                "widgets": {
                    "person": HiddenInput(),
                    "owner": HiddenInput(),
                    "file": widgets.ClearableFileInput(
                        attrs={
                            "accept": ".pdf,.odt,.ott,.oth,.odm,.doc,.docx,.docm,.docb,.rtf,.tex",
                            "placeholder": _("Please upload a file ..."),
                            "data-placeholder": _("Please upload a file ..."),
                            "data-required": 1,
                            "oninvalid": "this.setCustomValidity('%s')"
                            % _("The file is required. Please upload a file ..."),
                            "oninput": "this.setCustomValidity('')",
                        }
                    ),
                },
            }
        )
        return kwargs

    def get_queryset(self):
        return self.model.where(owner=self.request.user).order_by("-id")

    def get_defaults(self):
        """Default values for a form."""
        defaults = super().get_defaults()
        defaults["owner"] = self.request.user
        return defaults

    def formset_valid(self, formset):

        try:
            resp = super().formset_valid(formset)
        except RestrictedError:
            if formset.deleted_forms:
                form = formset.deleted_forms.pop()
                form.instance.owner = None
                form.instance.person = None
                form.instance.save(update_fields=["owner", "person"])
                return redirect(self.request.get_full_path())
            else:
                raise

        if not formset.deleted_forms:
            cv = models.CurriculumVitae.where(owner=self.request.user).order_by("-id").first()
            try:
                if cv and (cf := cv.update_converted_file()):
                    cv.save()
                    messages.success(
                        self.request,
                        _(
                            "Your CV was converted into PDF file. Please review "
                            "the converted version <a href='%s'>%s</a>."
                        )
                        % (cf.file.url, os.path.basename(cf.file.name)),
                    )

                if next_url := self.request.GET.get("next"):
                    if (
                        cv := models.CurriculumVitae.where(owner=self.request.user)
                        .order_by("-id")
                        .first()
                    ):
                        message_text = _('A CV successfully uploaded: <a href="%s">%s</a>') % (
                            cv.file.url,
                            cv.filename,
                        )

                        if "testimonials" in next_url or "reviews" in next_url:
                            notes = _("""
                                Now you can complete the submission of your referee report/testimonial.
                                <br/>Please click on the <strong>Submit</strong> button.
                            """)

                            message_text = f"{message_text}.<br/>{notes}"
                        messages.info(self.request, message_text)

                    return redirect(next_url)
            except Exception as ex:
                capture_exception(ex)
                messages.error(
                    self.request,
                    str(ex)
                    or _(
                        "Failed to convert your nomination form into PDF. "
                        "Please save your nomination form into PDF format and try to upload it again."
                    ),
                )
                return redirect(self.request.get_full_path())

        return resp


class ProfileAcademicRecordFormSetView(ProfileSectionFormSetView):
    model = models.AcademicRecord
    # formset_class = forms.modelformset_factory(models.Affiliation, exclude=(), can_delete=True,)
    orcid_sections = ["education", "qualification"]

    def get_factory_kwargs(self):
        kwargs = super().get_factory_kwargs()
        kwargs.update(
            {
                "widgets": {
                    "person": HiddenInput(),
                    "start_year": DateInput(attrs={"class": "yearpicker"}),
                    "qualification": autocomplete.ModelSelect2("qualification-autocomplete"),
                    "awarded_by": autocomplete.ModelSelect2(
                        "org-autocomplete",
                        attrs={
                            "placeholder": _("The organisation that awarded the degree"),
                            "data-required": 1,
                            "oninvalid": "this.setCustomValidity('%s')"
                            % _("The organisation is required ..."),
                            "oninput": "this.setCustomValidity('')",
                        },
                    ),
                    # "awarded_by": ModelSelect2Widget(
                    #     model=models.Organisation, search_fields=["name__icontains"],
                    # ),
                    "discipline": autocomplete.ModelSelect2("fos-autocomplete"),
                    # "discipline": ModelSelect2Widget(
                    #     model=models.FieldOfResearch, search_fields=["description__icontains"],
                    # ),
                    "conferred_on": forms.DateInput(),
                },
            }
        )
        return kwargs

    def get_queryset(self):
        return self.model.where(person=self.request.user.person).order_by("-start_year")

    def get_context_data(self, **kwargs):
        """Get the context data"""

        context = super().get_context_data(**kwargs)
        context.get("helper").add_input(
            Submit("load_from_orcid", _("Import from ORCiD"), css_class="btn-orcid")
        )
        return context


# class ProfileRecognitionForm(ModelForm):

#     award_name = CharField(label=_("Award"))

#     # def get_defaults(self, *args, **kwargs):
#     #     if (
#     #         self.round.letter_of_support_required
#     #         and self.object
#     #         and self.object.letter_of_support
#     #         and self.object.letter_of_support.file
#     #     ):
#     #         initial["letter_of_support_file"] = self.object.letter_of_support.file

#     def __init__(self, *, data=None, initial=None, **kwargs):
#         if instance and instance.award:
#             if not initial:
#                 initial = {"award_name": instance.award.name}
#             elif "award_name" not in initial:
#                 initial["award_name"] =  instance.award.name
#         super().__init__(data=data, initial=initial, **kwargs)

#     class Meta:
#         model = models.Recognition
#         # fields = ["state", "email", "first_name", "middle_names", "last_name", "role"]
#         exclude = ["award"]
#         widgets = {
#             "person": HiddenInput(),
#             "recognized_in": forms.YearInput(),
#             "award": autocomplete.ModelSelect2("award-autocomplete"),
#             "awarded_by": autocomplete.ModelSelect2("org-autocomplete"),
#         }


class ProfileRecognitionFormSetView(ProfileSectionFormSetView):
    model = models.Recognition
    # formset_class = forms.modelformset_factory(models.Affiliation, exclude=(), can_delete=True,)
    orcid_sections = ["funding"]
    # exclude = ["award"]
    # form_class = ProfileRecognitionForm

    def get_factory_kwargs(self):
        kwargs = super().get_factory_kwargs()
        kwargs.update(
            {
                "widgets": {
                    "person": HiddenInput(),
                    "recognized_in": forms.YearInput(),
                    "award": autocomplete.ModelSelect2(
                        "award-autocomplete",
                        attrs={
                            # "placeholder": _(""),
                            "data-required": 1,
                            "oninvalid": "this.setCustomValidity('%s')"
                            % _("The award is required ..."),
                            "oninput": "this.setCustomValidity('')",
                        },
                    ),
                    "awarded_by": autocomplete.ModelSelect2(
                        "org-autocomplete",
                        attrs={
                            "placeholder": _("The organisation that awarded the award"),
                            "data-required": 1,
                            "oninvalid": "this.setCustomValidity('%s')"
                            % _("The organisation is required ..."),
                            "oninput": "this.setCustomValidity('')",
                        },
                    ),
                },
            }
        )
        return kwargs

    def get_queryset(self):
        return self.model.where(person=self.request.user.person).order_by("-recognized_in")

    def get_context_data(self, **kwargs):
        """Get the context data"""

        context = super().get_context_data(**kwargs)
        context.get("helper").add_input(
            Submit("load_from_orcid", _("Import from ORCiD"), css_class="btn-orcid")
        )
        return context

    # def formset_valid(self, *args, **kwargs):
    #     return super().formset_valid(*args, **kwargs)

    # def get_form_class(self):
    #     fc = super().get_form_class()
    #     return fc


class AdminstaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """only Admin staff can access"""

    def test_func(self):
        return (
            self.request.user.is_superuser
            or self.request.user.is_staff
            or self.request.user.is_site_staff
        )


class ProfileSummaryView(AdminstaffRequiredMixin, DetailView):
    """Profile summary view"""

    cache_timeout = 0
    model = models.User
    slug_field = "username"
    slug_url_kwarg = "username"
    template_name = "profile_summary.html"
    context_object_name = "profile_user"
    user = None

    def get_context_data(self, **kwargs):
        """Get the profile summary of user"""

        context = super().get_context_data(**kwargs)
        user = self.object
        if not (person := models.Person.where(user=user).first()):
            messages.warning(
                self.request,
                _(
                    "No Profile summary found or User haven't completed his/her Profile. "
                    "Please come back again!"
                ),
            )

        # context["profile_user"] = user
        context["person"] = person
        context["image_url"] = user.image_url()

        if person:
            try:
                context["qualification"] = models.Affiliation.where(
                    person=person, type__in=["EMP"]
                ).order_by(
                    "start_date",
                    "end_date",
                )
                context["professional_records"] = models.Affiliation.where(
                    person=person, type__in=["MEM", "SER"]
                ).order_by(
                    "start_date",
                    "end_date",
                )
                context["external_id_records"] = models.PersonPersonIdentifier.where(
                    person=person
                ).order_by("code")
                context["academic_records"] = models.AcademicRecord.where(person=person).order_by(
                    "-start_year"
                )
                context["recognitions"] = models.Recognition.where(person=person).order_by(
                    "-recognized_in"
                )
            except Exception as ex:
                capture_exception(ex)

        return context


@require_http_methods(["POST"])
@login_required
@user_passes_test(lambda u: u.is_superuser or u.is_site_staff)
def approve_user(request, user_id=None):
    if not user_id:
        user_id = request.POST.get("user_id")
    u = User.where(id=user_id).first()
    if not u.is_approved:
        u.is_approved = True
        u.save()
        url = request.build_absolute_uri(reverse("index"))
        send_mail(
            request=request,
            recipients=[u.full_email_address],
            subject=f"Confirmation of {u.email} Signup",
            html_message="<p>You have been approved by schema administrators, "
            f"now start submitting an application to the Portal: {url}</p>",
        )
        messages.success(request, f"You have just approved self signed user {u.email}")
    else:
        messages.info(request, f"Self signed user {u.email} is already approved")

    return redirect("profile-summary", username=u.username)


class MemberView(CreateUpdateView):

    model = models.Member
    form_class = forms.MemberForm
    template_name = None

    def get_initial(self, *args, **kwargs):
        # if not is_fs and instance := kwargs.get("instance", None) and instance.user:
        #     initial = kwargs.get("initial", {})
        #     models.CurriculumVitae.last_user_cv(user=instance.user, cut_off_months=site)
        initial = super().get_initial(*args, **kwargs)
        if o := self.object:
            u = o.user
            p = u and u.person
            if not o.title and u:
                initial["title"] = u.person.title
            if not o.first_name and u:
                initial["first_name"] = u.first_name or p and p.first_name
            if not o.middle_names and u:
                initial["middle_names"] = u.middle_names or p and p.middle_names
            if not o.last_name and u:
                initial["last_name"] = u.last_name or p and p.last_name

            site_id = self.request.site_id
            cv = o.cv or models.CurriculumVitae.last_user_cv(
                user=o.user, cut_off_months=site_id == 2 and 3
            )
            if cv:
                if not o.cv:
                    o.cv = cv
                    # instance.save(model_fields=["cv"])
                initial["cv_file"] = cv.file
                if self.request.method == "GET":
                    pass
        return initial


class NominationView(CreateUpdateView):
    model = models.Nomination
    form_class = forms.NominationForm
    template_name = "nomination.html"

    def dispatch(self, request, *args, **kwargs):
        self.user = u = self.request.user
        if u.is_authenticated and not (u.is_superuser or u.is_staff or u.is_site_staff):
            n = self.get_object()
            if n:
                if not (
                    n.nominator
                    and n.nominator == u
                    or n.org
                    and n.org.research_offices.filter(user=u).exists()
                ):
                    messages.error(
                        request, _("You do not have permissions to access this nomination.")
                    )
                    return redirect(self.request.META.get("HTTP_REFERER", "index"))
                if n.state == "accepted":
                    contact_email = models.site_contact_email()
                    messages.warning(
                        request,
                        _(
                            "You cannot alter a nomination that has been submitted and accepted.  "
                            f"If you feel a need to do this, please email {contact_email} "
                            "with a reason and we may be able to enable."
                        ),
                    )
            elif request.site_id == 5 and not (models.ResearchOffice.where(user=u).exists()):
                messages.error(
                    request,
                    _(
                        "Only Research Office can nominate you for this round. Please contact your Research Office."
                    ),
                )
                return redirect("home")

        return super().dispatch(request, *args, **kwargs)

    @cached_property
    def round(self):
        return (
            models.Round.get(self.kwargs.get("round") or self.request.GET.get("round"))
            if "round" in self.kwargs or "round" in self.request.GET
            else self.object and self.object.round or None
        )

    def get_initial(self):
        initial = super().get_initial()

        initial["round"] = self.round.pk if self.round else None
        if self.request.method == "GET" and not (self.object and not self.object.pk):
            org = None
            if (
                latest := self.request.user.nominations.filter(
                    ~Q(contact_phone__isnull=True), ~Q(contact_phone="")
                )
                .order_by("pk")
                .last()
            ):
                initial["contact_phone"] = latest.contact_phone
                org = latest.org
            elif (
                ro := self.request.user.research_offices.filter(
                    ~Q(org__contact_phone__isnull=True), ~Q(org__contact_phone="")
                )
                .order_by("pk")
                .last()
            ):
                initial["contact_phone"] = ro.org.contact_phone
                org = ro.org

            if not org:
                org = (
                    self.request.user.person.affiliations.filter(end_date__isnull=True)
                    .order_by("-start_date", "-id")
                    .first()
                )

            if not org:
                a = (
                    models.Application.all_objects.filter(
                        submitted_by=self.request.user, org__isnull=False
                    )
                    .order_by("-id")
                    .first()
                )
                if a:
                    org = a.org
            if org:
                initial["org"] = org.pk

        return initial

    def form_valid(self, form):
        n = form.instance

        if not n.pk:
            if not n.nominator:
                n.nominator = self.request.user
            if not n.round_id:
                n.round = self.round
            if not n.site:
                n.site = Site.objects.get_current()
            if not n.org:
                n.org = n.get_nominator_orgs().last()

        resp = super().form_valid(form)
        check_selected_orgs(self.request)

        if self.request.method == "POST":
            reset_cache(self.request)

        if self.request.method == "POST" and "file" in form.changed_data and n.file:
            try:
                if cf := n.update_converted_file():
                    messages.success(
                        self.request,
                        _(
                            "Your nomination form was converted into PDF file. "
                            "Please review the converted nomination form version <a href='%s'>%s</a>."
                        )
                        % (cf.file.url, os.path.basename(cf.file.name)),
                    )

            except Exception as ex:
                capture_exception(ex)
                messages.error(
                    self.request,
                    _(
                        "Failed to convert your nomination form into PDF. "
                        "Please save your nomination form into PDF format and try to upload it again."
                    ),
                )
                return redirect(self.request.get_full_path())

        if (
            self.request.method == "POST"
            and self.round.nominator_cv_required
            and "cv_file" in form.changed_data
        ):
            try:
                if (
                    self.round.nominator_cv_required
                    and n.cv
                    and "cv_file" in form.changed_data
                    and (cv_cf := n.cv.update_converted_file())
                ):
                    n.cv.save(update_fields=["converted_file"])
                    messages.success(
                        self.request,
                        _(
                            "Your CV was converted into PDF file. Please review "
                            "the converted version <a href='%s'>%s</a>."
                        )
                        % (cv_cf.file.url, os.path.basename(cv_cf.file.name)),
                    )
            except Exception as ex:
                capture_exception(ex)
                messages.error(
                    self.request,
                    _(
                        "Failed to convert your CV into PDF. "
                        "Please save your CV into PDF format and try to upload it again."
                    ),
                )
                return redirect(self.request.get_full_path())

        if "submit" in self.request.POST or self.request.POST.get("action") == "submit":
            if (
                self.request.site_id not in [2, 4, 5]
                and self.round.nomination_form_required
                and not n.file
            ):
                messages.error(
                    self.request,
                    _(
                        "Missing the nomination form. Please attach a nomination form and re-submit"
                    ),
                )
                # return self.form_invalid(form)
                return resp

            if n.state == "accepted":
                contact_email = models.site_contact_email()
                messages.warning(
                    self.request,
                    _(
                        "You cannot alter a nomination that has been submitted and accepted.  "
                        f"If you feel a need to do this, please email {contact_email} "
                        "with a reason and we may be able to enable."
                    ),
                )
                return resp

            if self.round.nominator_cv_required:
                if not n.cv:
                    if (
                        cv := models.CurriculumVitae.where(owner=self.request.user)
                        .order_by("-id")
                        .first()
                    ):
                        n.cv = cv
                    else:
                        next_url = reverse("nomination-update", kwargs={"pk": n.id})
                        messages.error(
                            self.request,
                            _(
                                "To complete the nomination, you must provide a CV, please add a current CV "
                                "to your profile. Otherwise the Prize nomination cannot be considered."
                            ),
                        )
                        return redirect(reverse("profile-cvs") + "?next=" + next_url)

            try:
                invitation, created = n.submit(request=self.request)
                messages.info(
                    self.request,
                    (
                        _(
                            "An invitation to submit an application has been sent to %s (your nominee)."
                        )
                        % invitation.email
                        if created
                        else _(
                            "An invitation to submit an application has been resent to %s (your nominee)."
                        )
                        % invitation.email
                    ),
                )
                n.save()
                reset_cache(self.request)
                if return_url := self.request.GET.get("return_url"):
                    return redirect(f"{return_url}?selected_round={self.round.pk}")
                return redirect("index")
            except Exception as ex:
                capture_exception(ex)
                contact_email = models.site_contact_email()
                messages.error(
                    self.request,
                    _(
                        f"Failed to submit the nomination: {ex}. "
                        f"Please contact administration: {contact_email}."
                    ),
                )
        elif (
            self.request.method == "POST"
            and "save_draft" in self.request.POST
            and n.state != "draft"
        ):
            n.save_draft()
        n.save()

        return resp

    def get_form_kwargs(self):
        """Return the keyword arguments for instantiating the form."""
        kwargs = super().get_form_kwargs()
        if (
            self.request.method == "GET"
            and not (self.object and self.object.org)
            and "initial" in kwargs
        ):
            a = (
                self.request.user.person.affiliations.filter(type="EMP", end_date__isnull=True)
                .order_by("-id")
                .first()
            )
            if a:
                kwargs["initial"]["org"] = a.org
            elif ro := models.ResearchOffice.where(user=self.user).order_by("-id").first():
                kwargs["initial"]["org"] = ro.org

            kwargs["initial"]["round"] = self.round
            kwargs["initial"]["round_id"] = self.round.id if self.round else None
            kwargs["initial"]["nominator"] = self.request.user

        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["round"] = self.round
        context["nominator"] = (
            self.object.nominator if hasattr(self, "object") and self.object else self.request.user
        )
        return context

    def get_close_url(self):
        referer = self.request.META.get("HTTP_REFERER")
        if "return_url" in self.request.GET:
            return f"{self.request.GET.get('return_url')}?selected_round={self.round.pk}"
        return (
            self.request.GET.get("next")
            or self.request.GET.get("return_url")
            or (
                referer
                if referer and not referer.endswith(self.request.path)
                else reverse("nominations")
            )
        )


class TestimonialView(FavoriteMixin, CreateUpdateView):
    model = models.Testimonial
    form_class = forms.TestimonialForm
    template_name = "testimonial.html"

    def dispatch(self, request, *args, **kwargs):
        u = self.request.user
        if u.is_authenticated and not (u.is_superuser or u.is_staff or u.is_site_staff):
            t = self.get_object()
            if t and t.referee and t.referee.user and t.referee.user != u:
                messages.error(
                    request, _("You do not have permissions to access this testimonial.")
                )
                return redirect(self.request.META.get("HTTP_REFERER", "index"))
        if u.is_authenticated and "application" in self.kwargs:
            r = models.Referee.where(
                Q(user=u) | Q(email=u.email), application_id=self.kwargs["application"]
            ).last()
            if r:
                if (
                    testimonial_submission_closes_at := r.application.round.testimonial_submission_closes_at
                ) and testimonial_submission_closes_at < timezone.now():
                    messages.error(
                        request,
                        mark_safe(
                            _(
                                "The referee report submission was closed on "
                                f"<b>{testimonial_submission_closes_at.date().isoformat()}</b> "
                                f"at <b>{testimonial_submission_closes_at.time()}</b>."
                            )
                        ),
                    )
                    return redirect("home")

                t = models.Testimonial.where(referee=r).last()
                if t:
                    return redirect("testimonial-update", pk=t.pk)

        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        if a := self.application:
            initial.update({"application": a, "referee": self.referee})

        return initial

    @property
    def application(self):
        return (
            models.Application.get(self.kwargs["application"])
            if "application" in self.kwargs
            else self.object.referee.application
        )

    @property
    def referee(self):
        u = self.request.user
        t = self.get_object()
        if a := self.application:
            return (
                t
                and t.referee
                and t.referee.has_testified
                and t.referee
                or a.referees.filter(
                    Q(user=u) | Q(email__lower__in=u.emailaddress_set.values_list("email__lower"))
                ).last()
            )

    def form_valid(self, form):
        t = form.instance
        u = self.request.user
        reset_cache(self.request)
        site_id = self.request.site_id
        a = t and t.referee_id and t.referee.application or self.application

        if not t.pk:
            q = models.Referee.where(Q(user=u) | Q(email__in=u.email_addresses))
            if a:
                q = q.filter(application=a)
            if not (r := q.last()):
                form.errors.append(_("Referee entry is absent. Please contact Administrator"))
                capture_message(
                    "Referee entry is absent for referee/user: "
                    f"{u} (ID: {u.id}), {a} (ID: {a.id})",
                    level="error",
                )
                return self.form_invalid(form)

            if not r.user:
                r.user = u
                r.save(update_fields=["user"])
            t.referee = r

        if "file" in form.changed_data and t.file and t.converted_file:
            t.converted_file = None

        resp = super().form_valid(form)

        if r := t.referee:
            invitations = list(models.Invitation.where(~Q(state="accepted"), type="R", referee=r))
            if invitations:
                for i in invitations:
                    i.accept(self.request, by=u, description="Testimonial submitted", commit=False)
                models.Invitation.objects.bulk_update(
                    invitations, fields=["state", "state_changed_at", "accepted_at"]
                )

        round = t.application.round
        if "file" in form.changed_data and t.file and not t.file.name.lower().endswith(".pdf"):
            try:
                if t.file and (cf := t.update_converted_file()):
                    t.save(update_fields=["converted_file"])
                    messages.success(
                        self.request,
                        _(
                            "Your referee report/testimonial was converted into PDF file. Please review "
                            "the converted version <a href='%s'>%s</a>."
                        )
                        % (cf.file.url, os.path.basename(cf.file.name)),
                    )
            except Exception as ex:
                capture_exception(ex)
                messages.error(
                    self.request,
                    _(
                        "Failed to convert your report/testimonial into PDF. "
                        "Please save the file into PDF format and try to upload it again."
                    ),
                )
                return redirect(self.request.get_full_path())

        if (
            self.request.method == "POST"
            and round.referee_cv_required
            and "cv_file" in form.changed_data
        ):
            try:
                if round.referee_cv_required and t.cv and (cv_cf := t.cv.update_converted_file()):
                    t.cv.save(update_fields=["converted_file"])
                    messages.success(
                        self.request,
                        _(
                            "Your CV was converted into PDF file. Please review "
                            "the converted version <a href='%s'>%s</a>."
                        )
                        % (cv_cf.file.url, os.path.basename(cv_cf.file.name)),
                    )
            except Exception as ex:
                capture_exception(ex)
                messages.error(
                    self.request,
                    _(
                        "Failed to convert your CV into PDF. "
                        "Please save your CV into PDF format and try to upload it again."
                    ),
                )
                return redirect(self.request.get_full_path())

        if t.state != "submitted":
            if self.request.method == "POST" and "file" in form.changed_data and t.file:
                try:
                    if cf := t.update_converted_file():
                        messages.success(
                            self.request,
                            (
                                _(
                                    "Your referee report form was converted into PDF file. "
                                    "Please review the converted referee report form version <a href='%s'>%s</a>."
                                )
                                if site_id in [2, 4, 5]
                                else _(
                                    "Your testimonial form was converted into PDF file. "
                                    "Please review the converted testimonial form version <a href='%s'>%s</a>."
                                )
                            )
                            % (cf.file.url, os.path.basename(cf.file.name)),
                        )

                except Exception as ex:
                    capture_exception(ex)
                    messages.error(
                        self.request,
                        _(
                            "Failed to convert your testimonial form into PDF. "
                            "Please save your testimonial form into PDF format and try to upload it again."
                        ),
                    )
                    return resp

            if "submit" in self.request.POST or self.request.POST.get("action") == "submit":
                if self.application.round.referee_cv_required:
                    if (
                        cv := models.CurriculumVitae.where(owner=self.request.user)
                        .order_by("-id")
                        .first()
                    ):
                        t.cv = cv
                    else:
                        next_url = self.request.get_full_path()
                        messages.error(
                            self.request,
                            _(
                                "To complete the testimonial, you must provide a CV, please add a current CV "
                                "to your profile. Otherwise the Prize application cannot be considered."
                            ),
                        )
                        return redirect(reverse("profile-cvs") + "?next=" + next_url)

                if round.testimonials_required and not t.file:
                    messages.error(
                        self.request,
                        _("You haven't uploaded your testimonial, please do and then submit."),
                    )
                    return resp

                t.submit(request=self.request)
                t.save()

                # All testimonials are completed:
                if (
                    (a := t.application)
                    and not models.Testimonial.where(
                        ~Q(state="submitted"), referee__application=a
                    ).exists()
                    and not a.referees.filter(~Q(state="testified")).exists()
                ):
                    if t.site_id in [2, 5] and a.state == "in_review":
                        pass
                        # a.submit(request=self.request)
                        # a.save()
                    else:
                        url = self.request.build_absolute_uri(
                            reverse("application-update", kwargs={"pk": a.id})
                        )
                        recipients = [a.submitted_by, *a.members.all()]
                        params = {
                            "user_display": ", ".join(r.full_name for r in recipients),
                            "number": a.number,
                            "title": a.application_title or a.round.title,
                            "url": url,
                        }
                        send_mail(
                            __("All testimonials were completed"),
                            __(
                                "Tēnā koe %(user_display)s\n\n"
                                "All invited referees have now responded.\n\n"
                                "Please log into the portal to confirm that you have enough, "
                                "and where relevant the correct types, of referees.\n\n"
                                "If you do need to replace a referee, please do so and you'll "
                                "receive a new notification whenever they reply.\n\n"
                                "If all members have agreed, and you have the full compliment of referees, "
                                "you may now submit your completed application %(number)s: %(title)s here: %(url)s"
                            )
                            % params,
                            html_message=__(
                                "<p>Tēnā koe %(user_display)s</p>"
                                "<p>All invited referees have now responded.</p>"
                                "<p>Please log into the portal to confirm that you have enough, "
                                "and where relevant the correct types, of referees.</p>"
                                "<p>If you do need to replace a referee, please do so and you'll "
                                "receive a new notification whenever they reply.</p>"
                                "<p>If all members have agreed, and you have the full compliment of referees, "
                                'you may now submit your completed application <a href="%(url)s">%(number)s: '
                                "%(title)s</a></p>"
                            )
                            % params,
                            recipients=recipients,
                            fail_silently=False,
                            request=self.request,
                            reply_to=settings.DEFAULT_FROM_EMAIL,
                        )

                if t.site_id in (2, 4, 5):
                    # TODO: ????
                    messages.info(
                        self.request,
                        _(
                            "Your referee report has been submitted. The fellowship secretariat will be in touch "
                            "if there is anything more needed. Thank you for your participation."
                        ),
                    )
                else:
                    messages.info(
                        self.request,
                        _(
                            "Your testimonial has been submitted. The Prize secretariat will be in touch "
                            "if there is anything more needed. Thank you for your participation."
                        ),
                    )

            elif "save_draft" in self.request.POST:
                if t.state != "draft":
                    t.save_draft(request=self.request)
                    t.save()
            elif "turn_down" in self.request.POST:
                t.referee.opt_out(user=u, request=self.request)
                t.referee.save()
                reset_cache(self.request)
                return redirect("testimonials")
        else:
            messages.warning(
                self.request,
                _("Testimonial is already submitted."),
            )
        return redirect("testimonial", pk=t.id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        a = context["application"] = self.application
        if a and a.site_id in [2, 5]:
            context["documents"] = a.user_documents_dict(self.request.user)

        if not self.referee:
            messages.info(
                self.request,
                _("Please submit your review."),
            )
        return context


class NominationList(LoginRequiredMixin, StateInPathMixin, SingleTableMixin, FilterView):
    model = models.Nomination
    table_class = tables.NominationTable
    filterset_class = filters.NominationFilterSet
    paginator_class = django_tables2.paginators.LazyPaginator
    template_name = "nominations.html"

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        if self.request.user.is_ro:
            all_rounds = models.Round.where(
                Q(opens_on__isnull=True) | Q(opens_on__lte=timezone.now()),
                Q(closes_at__isnull=True) | Q(closes_at__gte=timezone.now()),
                scheme__current_round=F("pk"),
            )
            if all_rounds.exists():
                context["all_rounds"] = all_rounds
                self.has_actions = True
        return context

    def get_queryset(self, *args, **kwargs):
        qs = super().get_queryset(*args, **kwargs)
        state = self.request.path.split("/")[-1]
        u = self.request.user
        if state == "draft":
            state = [state, "new"]
        return self.model.user_nominations(user=u, request=self.request, state=state, queryset=qs)


class NominationDetail(DetailView):
    model = models.Nomination
    template_name = "nomination_detail.html"

    def post(self, request, *args, **kwargs):
        resp = super().post(request, *args, **kwargs)
        if (
            request.POST.get("action") in ["accept", "accept_nomination"]
            and self.object.state == "accepted"
        ):
            return redirect("nomination-application-create", nomination=self.object.pk)
        return resp

    @property
    def can_start_applying(self):
        u = self.request.user
        return (
            self.object.user == u or u.emailaddress_set.filter(email=self.object.email).exists()
        ) and not self.object.application

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()

        u = self.request.user
        if u.is_authenticated and not u.is_admin:
            n = self.object
            if not (
                n.nominator == u
                or n.user == u
                or u.emailaddress_set.filter(email=n.email).exists()
            ):
                messages.error(request, _("You do not have permissions to view this nomination."))
                return redirect(self.request.META.get("HTTP_REFERER", "nominations"))
            if n.state == "withdrawn":
                messages.error(request, _("The nominiation was withdrawn."))
                return redirect(self.request.META.get("HTTP_REFERER", "nominations"))

        if self.can_start_applying:
            nominator = self.object.nominator
            button_label = (
                _("Start Application")
                if self.request.site_id in [2, 4, 5]
                else _("Start Prize Application")
            )
            messages.info(
                request,
                _(
                    "You have been nominated for %(round)s by %(inviter)s. "
                    'To accept this nomination, please <b>"%(button_label)s"</b>'
                )
                % dict(
                    inviter=nominator.full_name_with_email,
                    round=self.object.round,
                    button_label=button_label,
                ),
            )
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if not (return_url := self.request.META.get("HTTP_REFERER")):
            state = self.object.state
            if not state or state in ["new", "draft"]:
                return_url = "nominations-draft"
            elif state == "submitted":
                return_url = "nominations-submitted"
            elif state == "accepted":
                return_url = "nominations-accepted"
            else:
                return_url = "nominations"
        context["return_url"] = return_url
        context["category"] = "nominations"
        context["exclude"] = [
            "id",
            "created_at",
            "updated_at",
            "site",
        ]
        if self.can_start_applying:
            context["start_applying"] = reverse(
                "nomination-application-create", kwargs=dict(nomination=self.object.pk)
            )
        return context


class TestimonialList(
    LoginRequiredMixin,
    StateInPathMixin,
    SingleTableMixin,
    FilterView,
):
    model = models.Testimonial
    table_class = tables.TestimonialTable
    template_name = "testimonials.html"
    filterset_class = filters.TestimonialFilterSet
    paginator_class = django_tables2.paginators.LazyPaginator
    limesurvey_admin_url = (
        f"{settings.DEBUG and settings.LIMESURVEY_SERVER_URL or '/limesurvey/'}admin/"
    )

    def get_queryset(self, *args, **kwargs):
        state = self.state
        return self.model.user_testimonials(user=self.request.user, state=state).order_by(
            "referee__application__number"
        )

    def get_table_kwargs(self):
        kwargs = super().get_table_kwargs()
        if self.request.user.is_admin:
            # if "extra_columns" in kwargs:
            return {
                "extra_columns": [
                    (
                        _("Survey Token"),
                        django_tables2.Column(
                            _("Survey Token"),
                            "referee__survey_token",
                            linkify=lambda record: (
                                f"{self.limesurvey_admin_url}tokens/sa/edit/iSurveyId/{survey_id}/iTokenId/{token_id}"
                                if (ref := record.referee)
                                and (token_id := ref.survey_token_id)
                                and (survey_id := ref.application.round.survey_id)
                                else None
                            ),
                        ),
                    ),
                    (
                        _("Survey Completed"),
                        django_tables2.Column(
                            _("Survey Completed"), "referee__survey_completed_at"
                        ),
                    ),
                    (
                        _("Export"),
                        tables.SafeTemplateColumn(
                            verbose_name=gettext_lazy("Export"),
                            template_name="partials/export_testimonial.html",
                            attrs={
                                "td": {
                                    "class": "text-center",
                                },
                            },
                        ),
                    ),
                ]
            }
        return kwargs


class TestimonialDetail(FavoriteMixin, DetailView):
    model = models.Testimonial
    template_name = "testimonial_detail.html"

    def get(self, request, *args, **kwargs):
        u = self.request.user
        if not u.is_admin:
            t = self.get_object()
            if t.referee.user != u:
                messages.error(request, _("You do not have permissions to view this testimonial."))
                return redirect(self.request.META.get("HTTP_REFERER", "index"))
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        t = self.get_object()
        referee = t.referee
        a = referee.application
        r = a and a.round or referee.application.round

        testimonial_submission_closes_at = r and r.testimonial_submission_closes_at
        if testimonial_submission_closes_at and testimonial_submission_closes_at < timezone.now():
            context["reviewing_closed"] = True

        if a:
            context["extra_object"] = a
            context["application"] = a
            if a.site_id in [2, 5]:
                context["documents"] = a.documents_dict
            if r.survey_id and referee.survey_token_id and referee.survey_completed_at:
                context["export_url"] = reverse(
                    "survey-response", kwargs={"referee_id": referee.pk}
                )
                context["export_tooltip"] = _(f"Export survey response")
            elif not (t and t.file):  ## and not referee.survey_completed_at:
                context["export_url"] = reverse("application-export", kwargs={"pk": a.pk})
                context["export_tooltip"] = _(f"Export application {a}")
            # elif (
            #     r.survey_id
            #     and referee.survey_token
            #     and referee.survey_token_id
            #     and (api := r.survey_api)
            #     and (
            #         survey_response_ids := api.query(
            #             "get_response_ids",
            #             params={
            #                 "sSessionKey": api.session_key,
            #                 "iSurveyID": r.survey_id,
            #                 "sToken": referee.survey_token,
            #             },
            #         )
            #     )
            # ):
            #     context["export_url"] = (
            #         f"/limesurvey/responses/viewquexmlpdf?surveyId={r.survey_id}&id={max(survey_response_ids)}&browseLang="
            #     )
            #     context["export_tooltip"] = _(f"Export referee report/survey {t}")
            elif t and t.file:
                if a.site_id in [2, 5]:
                    context["export_tooltip"] = _(f"Export referee report {t}")
                else:
                    context["export_tooltip"] = _(f"Export testimonial {t}")

        survey_url = (
            r and r.survey_id and reverse("survey-referee", kwargs={"referee_id": referee.id})
        )
        if survey_url:
            context["survey_url"] = survey_url
        if (
            a.site_id not in [2, 5]
            or r.testimonials_required
            or r.required_submitted_testimonials
            and not r.survey_id
            and not survey_url
        ):
            if t.state == "new":
                context["update_view_name"] = f"{self.model.__name__.lower()}-create"
                context["update_button_name"] = (
                    mark_safe(_("Add <strong>Referee Report</strong>"))
                    if t.site_id in [2, 4, 5]
                    else _("Add Testimonial")
                )
            else:
                context["update_button_name"] = (
                    mark_safe(_("Edit <strong>Referee Report</strong>"))
                    if t.site_id in [2, 4, 5]
                    else _("Edit Testimonial")
                )

        if not referee.has_testified:
            if r and r.survey_id:
                site = models.Site.objects.get_current()
                messages.info(
                    self.request,
                    (
                        f'<span class="badge badge-primary">{_("New")}</span> '
                        f"{_('You have a request to review a %s application to act on')}."
                        f"""<a href="{survey_url}" class="alert-link">
                        {_('Please click here to complete the referee report')}!
                      </a>"""
                    )
                    % site.name,
                )
            else:
                closes_at = r.closes_at
                if t.file and (not r.referee_cv_required or t.cv):
                    context["can_submit_testimonial"] = True

                if (
                    testimonial_submission_closes_at
                    and testimonial_submission_closes_at < timezone.now()
                ):
                    messages.warning(
                        self.request,
                        mark_safe(
                            _(
                                "The referee report submission was closed on "
                                f"<b>{testimonial_submission_closes_at.date().isoformat()}</b> "
                                f"at <b>{testimonial_submission_closes_at.time()}</b>."
                            )
                        ),
                    )
                elif (
                    r.site_id not in [2, 5]
                    or (closes_at and closes_at <= timezone.now())
                    or (a and a.state == "in_review")
                ):
                    messages.info(
                        self.request,
                        (
                            _("Please review the application details and submit referee report.")
                            if t.site_id in [2, 4, 5]
                            else _("Please review the application details and submit testimonial.")
                        ),
                    )
                else:
                    context["reviewing_disabled"] = True
                    closes_at_date = closes_at and closes_at.date().isoformat()
                    messages.warning(
                        self.request,
                        (
                            _(
                                "The application reviewing will be open after the application "
                                f"submission is closed (on <b>{closes_at_date}</b>)."
                            )
                            if closes_at_date
                            else _(
                                "The application reviewing will be open after the application submission is closed."
                            )
                        ),
                    )

        return context


class ApplicationExportView(ExportView):
    """Application PDF export view"""

    model = models.Application
    permission_denied_message = _("Only the round panellist and staff can export the application")

    def test_func(self):
        u = self.request.user
        # staff, superuser, or a panellist of the round
        if not u.is_authenticated or u.is_anonymous:
            return False
        return u.is_admin or (
            (a := self.get_object())
            and (
                a.submitted_by == u
                or a.members.all().filter(user=u).exists()
                or (self.request.site_id not in [4] and a.referees.all().filter(user=u).exists())
                or a.round.panellists.all().filter(user=u).exists()
                or a.org.research_offices.filter(user=u).exists()
            )
        )

    def get_objects(self, pk=None, number=None):
        app = self.model.get(id=pk)
        objects = super().get_objects(pk)
        testimonials = app.get_testimonials()
        objects.extend(testimonials)
        return objects

    def get_attachments(self, pk=None, number=None):
        attachments = []
        app = self.model.get(id=pk)
        u = self.request.user
        if app.site_id in [2, 4, 5] and app.is_applicant(u):
            return attachments

        if app.file:
            attachments.append(settings.PRIVATE_STORAGE_ROOT + "/" + str(app.pdf_file))
        if app.cv and app.cv.file:
            attachments.append(settings.PRIVATE_STORAGE_ROOT + "/" + str(app.cv.pdf_file))

        testimonials = (
            app.get_testimonials()
            if u.is_superuser or u.is_site_staff
            else app.get_testimonials(user=u)
        )
        for t in testimonials:
            if t.file:
                # attachments.append(settings.PRIVATE_STORAGE_ROOT + "/" + str(t.pdf_file))
                attachments.append(t.pdf_file.path)
            if t.cv and t.cv.file:
                # attachments.append(settings.PRIVATE_STORAGE_ROOT + "/" + str(t.cv.pdf_file))
                attachments.append(t.cv.pdf_file.path)

        return attachments

    def get_filename(self, pk):
        return self.model.get(id=pk).number

    def get(self, request, pk=None, number=None, filename=None, *args, **kwargs):
        # a = get_object_or_404(models.Application, pk=pk)
        a = self.get_object()
        if not filename:
            return redirect(a.export_url)
        pdf_content = io.BytesIO()
        merger = a.to_pdf(
            request=request,
            user=request.user,
            for_panellists=request.GET.get("for_panellists", False),
        )
        merger.write(pdf_content)
        # pdf_response = HttpResponse(pdf_content.getvalue(), content_type="application/pdf")
        pdf_content.seek(0)
        pdf_response = FileResponse(pdf_content, content_type="application/pdf")
        pdf_response["Cache-Control"] = (
            "no-cache, must-revalidate, max-age=0, post-check=0, pre-check=0"
        )
        pdf_response["Content-Disposition"] = f'inline; filename="{a.number}.pdf"'
        pdf_response["X-Content-Type-Options"] = "nosniff"
        return pdf_response


class ContractExportView(ExportView):
    """Contract PDF export view"""

    model = models.Contract
    # permission_denied_message = _("Only the round panellist and staff can export the application")

    def test_func(self):
        u = self.request.user
        return (
            u.is_superuser
            or u.is_staff
            or u.is_site_staff
            or (c := self.get_object_or_404())
            and (
                c.members.filter(user=u, role="PI").exists()
                or c.org.research_offices.filter(user=u).exists()
            )
        )

    def get(self, request, pk):
        c = self.get_object_or_404(pk)
        format = request.GET.get("format") or "pdf"
        for_download = request.GET.get("for_download", False)
        part = request.GET.get("part")
        if not format or format in ["html", "htm"]:
            content = c.get_document(request=self.request, format=format or "html", part=part)
            resp = HttpResponse(
                content,
                content_type="text/html; charset=utf-8",
            )
            if not for_download:
                return resp
            resp["Content-Length"] = len(content.encode("utf-8"))
        else:
            if not part and format == "pdf":
                output = c.to_pdf(request=self.request)
            else:
                output = c.get_document(request=self.request, format=format, part=part)
            if isinstance(output, PdfReader):
                resp = FileResponse(output.stream, content_type="application/pdf")
                resp["Content-Length"] = len(output.stream.getbuffer())
                output.stream.seek(0)
            else:
                content_type, _ = mimetypes.guess_type(output)
                if settings.DEBUG:
                    resp = StreamingHttpResponse(
                        FileWrapper(open(output, "rb")), content_type=content_type
                    )
                else:
                    # works with nginx:
                    resp = HttpResponse(content_type="application/force-download")
                    resp["X-Sendfile"] = output
                    resp["X-Accel-Redirect"] = output
                resp["Content-Length"] = os.path.getsize(output)

        if part:
            resp["Content-Disposition"] = f'attachment; filename="{c.number}_{part}.{format}"'
        else:
            resp["Content-Disposition"] = f'attachment; filename="{c.number}.{format}"'
        resp["Cache-Control"] = "no-cache, must-revalidate, max-age=0, post-check=0, pre-check=0"
        resp["X-Content-Type-Options"] = "nosniff"
        return resp


class RoundExportView(ExportView):
    """Round (all applications within the round) PDF export view"""

    model = models.Round
    permission_denied_message = _("Only the round panellist and staff can export the application")

    @property
    def round(self):
        return get_object_or_404(models.Round, pk=self.kwargs["pk"])

    def test_func(self):
        u = self.request.user
        # staff, superuser, or a panellist of the round
        return u.is_authenticated and (
            u.is_staff
            or u.is_superuser
            or self.round.panellists.filter(user=u).exists()
            or u.is_site_staff
        )

    @property
    def filename(self):
        return (self.round.title or self.round.scheme.title).lower().replace(" ", "-")

    def get(self, request, pk):
        round = self.round
        site_id = round and round.site_id or int(settings.SITE_ID)
        sync = request.GET.get("sync", None)
        file_format = request.GET.get("format", "pdf")
        regenerate = request.GET.get("regenerate", False)
        regenerate = regenerate and regenerate != "0"
        u = request.user
        for_panellists = request.GET.get("for_panellists", False) and u.is_admin

        if for_panellists or round.panellists.filter(user=u).exists():
            prefix = "panellists"
        elif u.is_superuser or u.is_site_staff:
            prefix = "admins"
        else:
            prefix = u.username

        # prefix = os.path.join(tempfile.gettempdir(), prefix)
        prefix_url = os.path.join(
            "rounds", f"{round.scheme.code}", f"{round.opens_on.year}", prefix
        )
        prefix = os.path.join(settings.PRIVATE_STORAGE_ROOT, prefix_url)
        if not os.path.exists(prefix):
            os.makedirs(prefix)

        output_filename = os.path.join(
            prefix, f"{round.scheme.code}-{round.opens_on.year}.{file_format}"
        )

        response, sync_output = round.export(
            request=request,
            by=u,
            file_format=file_format,
            sync=sync,
            regenerate=regenerate,
            for_panellists=for_panellists,
        )
        if sync_output:
            return response
        return redirect(request.META.get("HTTP_REFERER") or "start")


class NominationExportView(ExportView, NominationDetail):
    """Nomination PDF export view"""

    model = models.Nomination

    def get_metadata(self, pk):
        obj = self.model.get(pk)
        metadata = super().get_metadata(pk)
        metadata.update(
            {
                "/Author": obj.nominator.full_name_with_email,
                "/Subject": f"Nomination of {obj.user} for {obj.round} by {obj.nominator}",
                "/Number": f"{obj.pk}",
                "/URL": obj.get_full_detail_url(request=self.request),
            }
        )
        return metadata

    def get_filename(self, pk):
        obj = self.model.get(pk)
        return f"{obj.round.code}-{obj.user and obj.user.full_name_with_email or obj.email}"

    def test_func(self):
        u = self.request.user
        # staff, superuser, or a panellist of the round
        return (
            u.is_staff
            or u.is_superuser
            or u.is_site_staff
            or (
                "pk" in self.kwargs
                and (t := get_object_or_404(self.model, pk=self.kwargs["pk"]))
                and t.nominator == u
            )
        )

    def get_attachments(self, pk):
        obj = self.model.get(id=pk)
        attachments = []
        if obj.file:
            attachments.append(
                (
                    f"{obj} {_('Form')}",
                    settings.PRIVATE_STORAGE_ROOT + "/" + str(obj.pdf_file),
                )
            )
        if cv := obj.cv or models.CurriculumVitae.last_user_cv(obj.nominator):
            attachments.append(
                (
                    f"{cv} {_('Curriculum Vitae')}",
                    settings.PRIVATE_STORAGE_ROOT + "/" + str(cv.pdf_file),
                )
            )
        return attachments


class TestimonialExportView(ExportView, TestimonialDetail):
    """Testimonial PDF export view"""

    model = models.Testimonial

    def get_metadata(self, pk):
        testimonial = self.model.get(pk)
        metadata = super().get_metadata(pk)
        metadata.update(
            {
                "/Author": testimonial.referee.full_name_with_email,
                "/Subject": (
                    testimonial.application.application_title
                    or testimonial.application.round.title
                ),
                "/Number": testimonial.application.number,
            }
        )
        return metadata

    def get_filename(self, pk):
        testimonial = self.model.get(pk)
        return f"{testimonial.application.number}-{testimonial.referee.full_name_with_email}"

    def test_func(self):
        u = self.request.user
        # staff, superuser, or a panellist of the round
        return u.is_admin or (
            "pk" in self.kwargs
            and (t := get_object_or_404(models.Testimonial, pk=self.kwargs["pk"]))
            and t.referee.user == u
        )

    def get_attachments(self, pk):
        # testimonial = self.model.get(id=pk)
        testimonial = (
            self.model.where(pk=pk)
            .prefetch_related("referee", "referee__application", "referee__application__round")
            .last()
        )
        attachments = []
        if testimonial.file:
            attachments.append(
                (
                    f"{testimonial} {_('Form')}",
                    settings.PRIVATE_STORAGE_ROOT + "/" + str(testimonial.pdf_file),
                )
            )
        if testimonial.referee.application.round.referee_cv_required and (
            referee_cv := testimonial.cv
            or models.CurriculumVitae.last_user_cv(testimonial.referee.user)
        ):
            attachments.append(
                (
                    f"{testimonial.cv} {_('Curriculum Vitae')}",
                    settings.PRIVATE_STORAGE_ROOT + "/" + str(referee_cv.pdf_file),
                )
            )
        return attachments


class PanellistView(AdminRequiredMixin, ModelFormSetView):
    model = models.Panellist
    form_class = forms.PanellistForm
    formset_class = forms.PanellistFormSet
    template_name = "panellist.html"
    exclude = (
        "user",
        "site",
        "state_changed_at",
    )

    def get_initial(self):
        if (
            (r := self.round)
            and self.request.method == "GET"
            and "copy" in self.request.GET
            and (pr := models.Round.where(~Q(pk=r.pk), scheme=r.scheme).last())
        ):
            return [
                dict(round=r.pk, **p)
                for p in pr.panellists.filter(~Q(email__in=r.panellists.values("email")))
                .values("email", "first_name", "middle_names", "last_name")
                .order_by("email", "first_name")
            ]
        return super().get_initial()

    @cached_property
    def round(self):
        return models.Round.get(self.kwargs["round"]) if "round" in self.kwargs else self.round

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["helper"] = forms.PanellistFormSetHelper
        context["round"] = self.round
        return context

    def get_queryset(self, *args, **kwargs):
        return (
            super()
            .get_queryset(*args, **kwargs)
            .filter(round=self.round)
            .prefetch_related("conflict_of_interests", "evaluations")
        )

    def post(self, request, *args, **kwargs):
        if "cancel" in request.POST:
            return HttpResponseRedirect(reverse("home"))

        self.object_list = self.get_queryset()
        formset = self.construct_formset()
        if not formset.is_valid():
            return self.formset_invalid(formset)

        if deleted_forms := formset.deleted_forms:
            deleted_panellist = deleted_forms[0].cleaned_data.get("id")

        resp = self.formset_valid(formset)

        count = invite_panellist(self.request, self.round)
        if count > 0:
            messages.success(
                self.request,
                _("%d invitation(s) to panellist sent.") % count,
            )
        if deleted_forms and deleted_panellist:
            messages.success(
                self.request,
                _(
                    "Panellist <b>%s</b> with related entries - CoI statement(s) and review(s) - "
                    "was successfully deleted."
                )
                % deleted_panellist.full_name_with_email,
            )

        return resp

    def formset_valid(self, formset):
        for form in formset.forms[:]:
            # remove the duplicates for newly added entries
            email = form.instance.email.lower()
            if not form.instance.id and self.model.where(email=email, round=self.round).exists():
                messages.warning(
                    self.request,
                    _("The panellist %s was already invited once.") % email,
                )
                formset.forms.remove(form)

        return super().formset_valid(formset)

    def get_factory_kwargs(self):
        kwargs = super().get_factory_kwargs()
        widgets = kwargs.get("widgets", {})
        widgets.update(
            {
                "panellist": HiddenInput(),
                "DELETE": Submit("submit", "DELETE"),
                "round": HiddenInput(),
                "state": forms.InvitationStateInput(),
            }
        )
        kwargs["widgets"] = widgets
        kwargs["can_delete"] = True
        if (
            (r := self.round)
            and self.request.method == "GET"
            and "copy" in self.request.GET
            and (pr := models.Round.where(~Q(pk=r.pk), scheme=r.scheme).last())
        ):
            kwargs["extra"] = (
                pr.panellists.filter(~Q(email__in=r.panellists.values("email"))).count() + 1
            )
        return kwargs

    def get_defaults(self):
        """Default values for a form."""
        return dict(round=self.round)

    def get_formset(self):
        klass = super().get_formset()
        defaults = self.get_defaults()

        class Klass(klass):
            def get_form_kwargs(self, index):
                kwargs = super().get_form_kwargs(index)
                if "initial" not in kwargs:
                    kwargs["initial"] = defaults
                else:
                    kwargs["initial"].update(defaults)
                return kwargs

        return Klass


class RoundList(LoginRequiredMixin, StateInPathMixin, SingleTableView):
    model = models.Round
    table_class = tables.RoundTable
    template_name = "rounds.html"

    def get_table_kwargs(self):
        kwargs = super().get_table_kwargs()
        if (u := self.request.user) and (u.is_staff or u.is_superuser or u.is_site_staff):
            return kwargs
        kwargs.update(
            {
                "exclude": (
                    "evaluation_count",
                    "site",
                )
            }
        )
        return kwargs

    def get_queryset(self, *args, **kwargs):
        queryset = super().get_queryset(*args, **kwargs)
        queryset = queryset.filter(id__in=models.Scheme.objects.values("current_round"))

        user = self.request.user
        if not (user.is_staff or user.is_superuser or user.is_site_staff):
            queryset = queryset.filter(panellists__user=user).distinct()
        else:
            queryset = queryset.annotate(evaluation_count=Count("panellists__evaluations"))
        return queryset


class ScoreSheetList(AdminRequiredMixin, StateInPathMixin, SingleTableView):
    model = models.ScoreSheet
    table_class = tables.ScoreSheetTable
    template_name = "score_sheets.html"

    def get_table_kwargs(self):
        kwargs = super().get_table_kwargs()
        if (u := self.request.user) and (u.is_staff or u.is_superuser or u.is_site_staff):
            return kwargs
        kwargs.update({"exclude": ("evaluation_count",)})
        return kwargs

    def get_queryset(self, *args, **kwargs):
        # queryset = super().get_queryset(*args, **kwargs)
        return models.ScoreSheet.user_score_sheets(self.request.user)


class RoundApplicationList(LoginRequiredMixin, SingleTableView):
    model = models.Application
    table_class = tables.RoundApplicationTable
    template_name = "rounds.html"

    def get_table_kwargs(self):
        kwargs = super().get_table_kwargs()
        if (u := self.request.user) and (u.is_staff or u.is_superuser or u.is_site_staff):
            return kwargs
        kwargs.update({"exclude": ("evaluation_count",)})
        return kwargs

    @property
    def round(self):
        return get_object_or_404(models.Round, pk=self.kwargs.get("round_id"))

    @property
    def state(self):
        if (
            state := self.kwargs.get("state")
            or self.request.GET.get("state")
            or self.request.path.split("/")[-1]
        ) and state in ["new", "draft", "submitted", "archived"]:
            return state

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if round := self.round:
            context["round"] = round
            if panellist := round.panellists.filter(user=self.request.user).last():
                context["is_panellist"] = True
                context["panellist"] = panellist
        if state := self.state:
            context["state"] = state
        context["rounds"] = (
            models.Round.current_rounds()
            .order_by("title")
            .values("id", "title")
            .annotate(total_applications=Count("applications"))
        )
        return context

    def get(self, request, *args, **kwargs):
        user = self.request.user
        if r := self.round:
            if not (r.has_online_scoring or user.is_admin):
                if not r.panellists.filter(user=user).exists():
                    messages.error(self.request, _(f"You were not invited to this round ({r})"))
                    return redirect(self.request.META.get("HTTP_REFERER") or reverse("start"))
                elif not r.all_coi_statements_given_by(request.user):
                    return redirect("round-coi", round=r.id)
                return redirect("score-sheet", round=r.id)
            elif (
                not r.all_coi_statements_given_by(request.user)
                or not models.ConflictOfInterest.where(
                    has_conflict=False,
                    has_conflict__isnull=False,
                    panellist__user=user,
                    application__round=r,
                ).exists()
            ):
                return redirect("round-coi", round=r.id)
        return super().get(request, *args, **kwargs)

    def get_queryset(self, *args, **kwargs):
        queryset = super().get_queryset(*args, **kwargs)
        if r := self.round:
            queryset = queryset.filter(round=r)

        if state := self.state:
            if state == "draft":
                queryset = queryset.filter(evaluations__state__in=["new", "draft"])
            else:
                queryset = queryset.filter(evaluations__state=state)

        user = self.request.user
        if not (user.is_staff or user.is_superuser or user.is_site_staff):
            queryset = queryset.filter(round__panellists__user=user, state="submitted").annotate(
                coi=FilteredRelation(
                    "conflict_of_interests",
                    condition=Q(conflict_of_interests__panellist__user=user),
                )
            )
        else:
            queryset = queryset.annotate(evaluation_count=Count("evaluations"))

        return queryset.distinct()


class EvaluationListView(LoginRequiredMixin, StateInPathMixin, SingleTableView):
    model = models.Evaluation
    table_class = tables.EvaluationTable
    template_name = "rounds.html"

    def get_queryset(self, *args, **kwargs):
        queryset = super().get_queryset(*args, **kwargs)
        if pk := self.kwargs.get("pk"):
            if a := get_object_or_404(models.Application, pk=pk):
                queryset = queryset.filter(application=a)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if pk := self.kwargs.get("pk"):
            if a := get_object_or_404(models.Application, pk=pk):
                context["application"] = a
                context["round"] = a.round
                context["object_state"] = a.state
        return context


class ConflictOfInterestView(CreateUpdateView):
    model = models.ConflictOfInterest
    form_class = forms.ConflictOfInterestForm
    template_name = "conflict_of_interest.html"

    def dispatch(self, request, *args, **kwargs):
        u = self.request.user
        if u.is_authenticated and not (u.is_superuser or u.is_staff or u.is_site_staff):
            coi = self.get_object()
            if coi and coi.panellist and coi.panellist.user and coi.panellist.user != u:
                messages.error(request, _("You do not have permissions to access this page."))
                return redirect(self.request.META.get("HTTP_REFERER", "index"))
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        if coi := self.get_object():
            initial["application"] = coi.application
        elif "application_id" in self.kwargs and (
            a := models.Application.where(id=self.kwargs["application_id"]).first()
        ):
            initial["application"] = a
            initial["has_conflict"] = True
        return initial

    def get(self, request, *args, **kwargs):
        if "pk" in kwargs and (coi := models.ConflictOfInterest.where(pk=kwargs["pk"]).first()):
            if (
                coi.has_conflict is False
                and models.Evaluation.where(
                    panellist__user=self.request.user, application=coi.application
                ).exists()
            ):
                messages.warning(
                    self.request,
                    _(
                        "You have already submitted a evaluation of the application "
                        "and cannot change the submitted statement of conflict of interest."
                    ),
                )
                return redirect("application", pk=coi.application_id)

        if "application_id" in kwargs and (
            a := models.Application.where(id=kwargs["application_id"]).first()
        ):
            if a.state != "submitted":
                messages.warning(self.request, _("The application has not been yet submitted."))
                return redirect("application", pk=a.pk)
            if coi := models.ConflictOfInterest.where(
                application=a, panellist__user=self.request.user
            ).first():
                # return redirect("coi-update", pk=coi.pk)
                return redirect("round-coi", round=a.round_id)

        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        n = form.instance
        try:
            application = n.application
        except:
            application = models.Application.where(id=self.kwargs["application_id"]).first()
        round = application.round
        n.application = application
        n.panellist = models.Panellist.where(round=round, user=self.request.user).first()
        resp = super().form_valid(form)

        if n.has_conflict:
            messages.warning(
                self.request, _("You have conflict of interest for this application.")
            )
            return redirect("round-application-list", round_id=round.pk)
        else:
            return redirect("application-evaluation-create", application=application.pk)
        return resp

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if application_id := self.kwargs.get("application_id"):
            application = models.Application.where(id=application_id).first()
        else:
            application = self.object.application
        # context["object"] = application
        context["application"] = application
        context["members"] = application.members.all()
        context["include"] = [
            "number",
            "application_title",
            "team_name",
            "email",
            "first_name",
            "last_name",
        ]
        context["member_include"] = ["first_name", "last_name", "email"]
        return context


class ScoreInline(InlineFormSetFactory):
    model = models.Score
    form_class = forms.ScoreForm
    factory_kwargs = {
        "max_num": None,
        "can_order": False,
        "can_delete": False,
        "widgets": dict(
            criterion=forms.CriterionWidget(),
        ),
    }
    fields = [
        "criterion",
        "value",
        "comment",
    ]

    def get_entries(self):
        if "application" in self.kwargs:
            a = models.Application.get(self.kwargs.get("application"))
            # return a.get_score_entries(user=self.request.user).distinct()
            return a.round.criteria.all()
        else:
            pass

    def get_factory_kwargs(self):
        kwargs = super().get_factory_kwargs()
        if "application" in self.kwargs and (
            a := get_object_or_404(models.Application, pk=self.kwargs["application"])
        ):
            if self.request.method == "GET":
                kwargs["extra"] = self.get_entries().count()
            else:
                extra_entry_count = a.round.criteria.count()
                if self.object and self.object.id:
                    extra_entry_count -= self.object.scores.count()
                kwargs["extra"] = extra_entry_count
        else:
            extra_entry_count = self.object.application.round.criteria.count()
            if self.object and self.object.id:
                extra_entry_count -= self.object.scores.count()
            kwargs["extra"] = extra_entry_count
        return kwargs

    def get_initial(self):
        if self.request.method == "GET":
            if "application" in self.kwargs:
                return [dict(criterion=e, value=e.min_score) for e in self.get_entries()]
            evaluation = self.object
            return [
                dict(criterion=e, value=e.min_score)
                for e in evaluation.application.round.criteria.filter(
                    ~Q(id__in=evaluation.scores.values("criterion"))
                )
            ]
        return super().get_initial()


# class EditEvaluation(InlineFormSetView):
#     model = models.Evaluation
#     inline_model = models.Score


class EvaluationMixin:
    model = models.Evaluation
    inline_model = models.Score
    inlines = [
        ScoreInline,
    ]
    fields = ["comment"]

    def forms_valid(self, form, inlines):
        reset_cache(self.request)
        try:
            with transaction.atomic():
                resp = super().forms_valid(form, inlines)
                e = self.object
                if "save_draft" in self.request.POST:
                    e.save_draft()
                else:
                    e.submit()
                e.save()
        except Exception as ex:
            capture_exception(ex)
            messages.error(self.request, getattr(ex, "message", str(ex)))
            return super().forms_invalid(form, inlines)
        return resp

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        if application := (
            models.Application.get(self.kwargs.get("application"))
            if "application" in self.kwargs
            else self.object.application
        ):
            data["application"] = application
            data["round"] = application.round
            data["coi"] = application.conflict_of_interests.filter(
                panellist__user=self.request.user
            ).last()

        return data


@login_required
def application_contract(request, pk):
    if c := models.Contract.where(application_id=pk).last():
        return redirect("contract-detail", number=c.number)
    return redirect(f'{reverse("contract-create")}?application_pk={pk}')


@login_required
def edit_evaluation(request, pk):
    """Redirect either to create or update an evaluation."""
    if e := models.Evaluation.where(application=pk, panellist__user=request.user).first():
        return redirect(reverse("evaluation-update", kwargs=dict(pk=e.id)))
    return redirect(reverse("application-evaluation-create", kwargs=dict(application=pk)))


class CreateEvaluation(LoginRequiredMixin, EvaluationMixin, CreateWithInlinesView):
    def dispatch(self, request, *args, **kwargs):
        u = self.request.user
        if u.is_authenticated and not (u.is_superuser or u.is_staff or u.is_site_staff):
            a = self.application
            if not (a and models.Panellist.where(round=a.round, user=u).exists()):
                messages.error(
                    request,
                    _("You do not have permissions to create an evaluation for this application."),
                )
                return redirect(self.request.META.get("HTTP_REFERER", "index"))
        return super().dispatch(request, *args, **kwargs)

    @property
    def application(self):
        if pk := self.kwargs.get("application"):
            return get_object_or_404(models.Application, pk=pk)

    def get(self, *args, **kwargs):
        if "application" in self.kwargs:
            e = models.Evaluation.where(
                application=self.kwargs.get("application"), panellist__user=self.request.user
            ).first()
            if e:
                messages.warning(
                    self.request,
                    _("Evaluation scoring was already created"),
                )
                return redirect(reverse("evaluation-update", kwargs=dict(pk=e.id)))
        return super().get(*args, **kwargs)

    def form_valid(self, form):
        a = models.Application.get(self.kwargs.get("application"))
        p = models.Panellist.where(round=a.round, user=self.request.user).first()
        form.instance.application = a
        form.instance.panellist = p
        return super().form_valid(form)


class UpdateEvaluation(LoginRequiredMixin, EvaluationMixin, FavoriteMixin, UpdateWithInlinesView):
    def dispatch(self, request, *args, **kwargs):
        u = self.request.user
        if u.is_authenticated and not (u.is_superuser or u.is_staff or u.is_site_staff):
            e = self.get_object()
            if e and e.panellist and e.panellist.user and e.panellist.user != u:
                messages.error(request, _("You do not have permissions to access this page."))
                return redirect(self.request.META.get("HTTP_REFERER", "index"))
        return super().dispatch(request, *args, **kwargs)

    def get(self, *args, **kwargs):
        resp = super().get(*args, **kwargs)
        if self.object.state == "submitted":
            messages.error(
                self.request,
                _(
                    "Evaluation has been already submitted. "
                    "It cannot be changed after it was submitted"
                ),
            )
            return redirect(reverse("evaluation", kwargs=dict(pk=kwargs.get("pk"))))

        return resp


class EvaluationDetail(FavoriteMixin, DetailView):
    model = models.Evaluation
    template_name = "evaluation.html"

    def get(self, request, *args, **kwargs):
        if not (u := request.user) and not u.is_admin:
            if (e := self.get_object()) and e.panellist and e.panellist.user != u:
                messages.error(request, _("You do not have permission to access this review."))
                return self.handle_no_permission()
        return super().get(request, *args, **kwargs)

    def get_context_data(self, *args, **kwargs):
        u = self.request.user
        context = super().get_context_data(*args, **kwargs)
        q = models.Application.where(
            conflict_of_interests__panellist__user=u,
            # conflict_of_interests__has_conflict=False,
            round=F("round__scheme__current_round"),
        ).prefetch_related(
            Prefetch("evaluations", queryset=models.Evaluation.objects.filter(panellist__user=u)),
            Prefetch(
                "conflict_of_interests",
                queryset=models.ConflictOfInterest.objects.filter(
                    panellist__user=u, has_conflict=False
                ),
            ),
        )
        if q.count() > 0:
            # context["applications"] = q.all()
            q = q.annotate(evaluation_count=Count("evaluations"))
            context["application_table"] = tables.RoundApplicationTable(
                q.all(), request=self.request, exclude=("evaluation_count",), order_by="number"
            )

        return context

    # def post(self, request, *args, **kwargs):

    #     self.object = self.get_object()
    #     member = self.object.members.filter(
    #         has_authorized__isnull=True, user=self.request.user
    #     ).first()
    #     if "authorize_team_lead" in request.POST:
    #         member.has_authorized = True
    #         member.state = "authorized"
    #         # member.authorized_at = datetime.now()
    #         member.save()
    #     elif "turn_down" in request.POST:
    #         member.has_authorized = False
    #         member.state = "opted_out"
    #         member.save()
    #         if self.object.submitted_by.email:
    #             send_mail(
    #                 _("A team member opted out of application"),
    #                 _("Your team member %s has opted out of application") % member,
    #                 settings.DEFAULT_FROM_EMAIL,
    #                 recipients=[self.object.submitted_by.email],
    #                 fail_silently=False,
    #                 request=self.request,
    #                 reply_to=settings.DEFAULT_FROM_EMAIL,
    #             )

    #     return self.get(request, *args, **kwargs)

    # def get_context_data(self, **kwargs):
    #     context = super().get_context_data(**kwargs)
    #     return context


class RoundConflictOfInterestFormSetView(LoginRequiredMixin, ModelFormSetView):
    model = models.ConflictOfInterest
    form_class = forms.RoundConflictOfInterestForm
    exclude = []

    @property
    def round(self):
        return get_object_or_404(models.Round, pk=self.kwargs["round"])

    def get(self, *args, **kwargs):

        user = self.request.user
        if not (self.panellist or user.is_admin):
            messages.error(self.request, _(f"You were not invited to this round ({self.round})"))
            return redirect(self.request.META.get("HTTP_REFERER") or reverse("start"))
        return super().get(*args, **kwargs)

    def post(self, *args, **kwargs):
        reset_cache(self.request)
        resp = super().post(*args, **kwargs)
        return resp

    def formset_valid(self, formset):
        resp = super().formset_valid(formset)
        if "submit" in self.request.POST:
            r = get_object_or_404(models.Round, pk=self.kwargs["round"])
            messages.success(
                self.request,
                _(
                    "Your conflicts of interest statements have been recorded. "
                    "You can now evaluate the application(s) and submit scores."
                ),
            )
            if r.has_online_scoring:
                return redirect("round-application-list", round_id=r.pk)
            else:
                return redirect("score-sheet", round=r.pk)
        return resp

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context["yes_label"] = _("Yes")
        context["no_label"] = _("No")

        round_id = self.kwargs.get("round")
        if round_id and (
            p := models.Panellist.where(user=self.request.user, round_id=round_id).first()
        ):
            if p.has_all_coi_statements_submitted_for(round_id):
                context["is_all_coi_statements_sumitted"] = True

            for row in (
                models.ConflictOfInterest.where(
                    panellist=p,
                    application__round_id=round_id,
                )
                .values("has_conflict")
                .annotate(count=Count("*"))
            ):
                context[f"has_conflict_{row['has_conflict']}"] = row["count"] != 0

        if round_id:
            context["round"] = models.Round.get(round_id)

        return context

    def get_queryset(self):
        round_id = self.kwargs["round"]
        return (
            super()
            .get_queryset()
            .filter(application__round=round_id, panellist__user=self.request.user)
            .filter(~Q(application__state__in=["new", "draft", "archived"]))
            .prefetch_related("application")
            .order_by("application__number")
        )

    @property
    def panellist(self):
        if "round" in self.kwargs and (
            p := models.Panellist.where(round=self.kwargs["round"], user=self.request.user).first()
        ):
            return p
        else:
            return None

    def get_initial_queryset(self):
        from django.db.models import Exists, OuterRef

        if (panellist := self.panellist) and self.request.method == "GET":
            return (
                models.Application.objects.select_related("round")
                .filter(round=self.kwargs["round"], round__panellists=panellist)
                .filter(~Q(state__in=["new", "draft", "archived"]))
                .filter(
                    ~Q(
                        Exists(
                            models.ConflictOfInterest.where(
                                application=OuterRef("pk"), panellist=panellist
                            )
                        )
                    )
                )
                .order_by("number")
            )
        else:
            return models.Application.objects.none()

    def get_initial(self):
        if (
            "round" in self.kwargs
            and self.request.method == "GET"
            and (panellist := self.panellist)
        ):
            return [
                dict(application=a, has_conflict=True, panellist=panellist)
                for a in self.get_initial_queryset()
            ]
        return super().get_initial()

    def get_factory_kwargs(self):
        kwargs = super().get_factory_kwargs()
        kwargs["extra"] = self.get_initial_queryset().count()
        # if "application" in self.kwargs and self.request.method == "GET":
        #     kwargs["extra"] = self.get_entries().count()
        # else:
        #     kwargs["extra"] = 0
        kwargs.update(
            {
                "widgets": {
                    "application": forms.HiddenInput(),
                    "has_conflict": forms.HiddenInput(),
                    "panellist": forms.HiddenInput(),
                    # "file": widgets.FileInput(
                    #     attrs={
                    #         "data-placeholder": _("Choose a career stage ..."),
                    #         "placeholder": _("Choose a career stage ..."),
                    #         "data-required": 1,
                    #         "oninvalid": "this.setCustomValidity('%s')"
                    #         % _("Career stage is required"),
                    #         "oninput": "this.setCustomValidity('')",
                    #     }
                    # ),
                }
            }
        )
        return kwargs


@login_required
@shoud_be_onboarded
def export_score_sheet(request, round):
    file_type = request.GET.get("type", "xlsx")
    r = (
        models.Round.where(id=round)
        .order_by("-id")
        .prefetch_related("criteria", "applications")
        .first()
    )

    book = tablib.Databook()
    title = r.title or r.scheme.title
    if file_type != "ods":
        if len(title) > 31:
            if file_type == "xls":
                title = title[:31]
            else:
                title = title[:27] + "..."

    headers = [
        _("Proposal/Application"),
        _("Lead"),
        _("Overall Comment"),
        _("Total"),
        *(v for (c,) in r.criteria.values_list("definition") for v in (c, f"{c} {_('Comment')}")),
    ]
    dummy = ("",) * (len(headers) - 2)

    data = [
        (
            a.number,
            a.lead,
            *dummy,
        )
        for a in r.applications.all().order_by("number")
        if request.user.is_staff
        or request.user.is_superuser
        or request.user.is_site_staff
        or (
            not a.conflict_of_interests.all()
            .filter(panellist__user=request.user, has_conflict=True)
            .exists()
        )
    ]

    book.add_sheet(
        tablib.Dataset(
            *data,
            title=title,
            headers=headers,
        )
    )

    if file_type == "xls":
        content_type = "application/vnd.ms-excel"
    elif file_type == "xlsx":
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif file_type == "ods":
        content_type = "application/vnd.oasis.opendocument.spreadsheet"

    filename = f'{r.scheme.code}-{request.person.code or request.user.username or "scoresheet"}.{file_type}'
    response = HttpResponse(book.export(file_type), content_type=content_type)
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Cache-Control"] = (
        "no-cache, must-revalidate, max-age=0, post-check=0, pre-check=0"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


class RoundConflictOfInterstStatementList(LoginRequiredMixin, ExportMixin, SingleTableView):
    export_formats = ["xls", "xlsx", "csv", "json", "latex", "ods", "tsv", "yaml"]
    model = models.ConflictOfInterest
    table_class = tables.RoundConflictOfInterestStatementTable
    paginator_class = django_tables2.paginators.LazyPaginator
    template_name = "table.html"

    @property
    def round(self):
        return models.Round.get(self.kwargs.get("round"))

    @property
    def show_only_conflicts(self):
        show_only_conflicts = self.request.GET.get("show_only_conflicts")
        return show_only_conflicts != "0" and bool(show_only_conflicts)

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        data["show_only_conflicts"] = self.show_only_conflicts
        data["add_show_only_conflicts_filter"] = True
        data["rounds"] = (
            models.Round.objects.all().order_by("-opens_on", "title").values("id", "title")
        )
        data["round"] = self.round
        return data

    @property
    def title(self):
        if "round" in self.kwargs:
            return models.Round.get(self.kwargs.get("round")).title

    @property
    def export_name(self):
        return (
            models.Round.get(self.kwargs.get("round")).title
            if "round" in self.kwargs
            else "export"
        )

    def get_queryset(self, *args, **kwargs):
        queryset = (
            self.model.where(application__round=self.kwargs.get("round"))
            .select_related("application", "panellist")
            .annotate(
                number=F("application__number"),
                first_name=Coalesce("panellist__first_name", "panellist__user__first_name"),
                middle_names=Coalesce("panellist__middle_names", "panellist__user__middle_names"),
                last_name=Coalesce("panellist__last_name", "panellist__user__last_name"),
                email=Coalesce("panellist__email", "panellist__user__email"),
            )
        )
        if self.show_only_conflicts:
            queryset = queryset.filter(Q(has_conflict=True) | Q(has_conflict=1))
        return queryset


@login_required
def score_sheet(request, round):
    if (
        (round := models.Round.where(pk=round).first())
        and (panellist := models.Panellist.where(user=request.user, round_id=round).first())
        and panellist.has_all_coi_statements_submitted_for(round.id)
    ):
        score_sheet = models.ScoreSheet.where(panellist=panellist, round=round).first()
        form = forms.ScoreSheetForm(
            request.POST or None,
            request.FILES or None,
            instance=score_sheet,
            initial={"round": round, "panellist": panellist},
        )
        form.round = round
        form.panellist = panellist
        if form.is_valid():
            form.save(commit=False)
            form.instance.round = round
            form.instance.panellist = panellist
            score_sheet = form.save()

            if score_sheet:
                reset_cache(request)
                return redirect(request.get_full_path())

        return render(request, "score_sheet.html", locals())

    messages.error(
        request,
        _(
            "You have not yet stated your conflict of interest statement for all applications. "
            "Please submit the statements for all the applications submitted in the round."
        ),
    )
    return redirect(
        reverse("round-coi", kwargs=dict(round=round.id))
        + "?next="
        + quote(request.get_full_path())
    )


class RoundScoreList(AdminRequiredMixin, ExportMixin, SingleTableView):
    export_formats = ["xls", "xlsx", "csv", "json", "latex", "ods", "tsv", "yaml"]
    model = models.Application
    # table_class = tables.RoundConflictOfInterestStatementTable
    paginator_class = django_tables2.paginators.LazyPaginator
    # template_name = "rounds_conflict_of_interest.html"
    template_name = "table.html"

    @property
    def show_only_conflicts(self):
        show_only_conflicts = self.request.GET.get("show_only_conflicts")
        return show_only_conflicts != "0" and bool(show_only_conflicts)

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        data["show_only_conflicts"] = self.show_only_conflicts
        return data

    @property
    def title(self):
        if "round" in self.kwargs:
            return models.Round.get(self.kwargs.get("round")).title

    @property
    def export_name(self):
        return (
            models.Round.get(self.kwargs.get("round")).title
            if "round" in self.kwargs
            else "export"
        )

    def get_queryset(self, *args, **kwargs):
        round_id = self.kwargs.get("round")
        # criteria = models.Criterion.where(round_id=round_id)
        # definitions = {c.id: c.definition for c in criteria}
        # scales = {c.id: c.scale for c in criteria}

        q = self.model.where(
            Q(round_id=round_id),
            Q(round_id=F("round__panellists__round_id")),
            Q(evaluations__id=F("evaluations__scores__evaluation__id"))
            | Q(evaluations__id__isnull=True),
        ).annotate(
            # panellist_first_name=Coalesce(
            #     "round__panellist__first_name", "round__panellist__user__first_name"
            # ),
            # panellist_middle_names=Coalesce(
            #     "round__panellist__middle_names", "round__panellist__user__middle_names"
            # ),
            # panellist_last_name=Coalesce("round__panellist__last_name", "round__panellist__user__last_name"),
            # panellist_email=Coalesce("round__panellist__email", "round__panellist__user__email"),
            value=F("evaluations__scores__value"),
            comment=F("evaluations__scores__comment"),
            scale=F("evaluations__scores__criterion__scale"),
        )
        # data = groupby(q, lambda r: (r.id, r.round__panellists__id))
        # data = [
        #         k[0], k[1],
        #     groupby(q, lambda r: (r.id, r.round__panellists__id))
        # ]

        return q


@login_required
def round_scores_export(request, round):
    file_type = request.GET.get("type", "xlsx")
    round = get_object_or_404(models.Round, pk=round)
    criteria = models.Criterion.where(round=round)

    book = tablib.Databook()

    titles = []
    for p in round.scores:
        title = p.full_name

        if file_type != "ods":
            if len(title) > 31:
                if file_type == "xls":
                    title = title[:31]
                else:
                    title = title[:27] + "..."

            for i in range(1, 10):
                if title.lower() not in titles:
                    break
                title = f"{title[:-2]}_{i}"
            titles.append(title.lower())

        data = (
            (
                e.application.number,
                e.application.lead,
                e.comment,
                e.total,
                *(
                    v
                    for s in e.all_scores(criteria)
                    for v in (("", "") if isinstance(s, dict) else (s.value, s.comment))
                ),
            )
            for e in p.evaluations.all()
        )

        book.add_sheet(
            tablib.Dataset(
                *data,
                title=title,
                headers=[
                    _("Application"),
                    _("Lead"),
                    _("Overall Comment"),
                    _("Total"),
                    *(
                        v
                        for (c,) in criteria.values_list("definition")
                        for v in (c, f"{c} {_('Comment')}")
                    ),
                ],
            )
        )

    sheet = tablib.Dataset(
        title=_("Total"), headers=[_("Application"), _("Lead"), _("Total Scores")]
    )
    for row in round.avg_scores:
        sheet.append((row.number, row.lead, row.total))
    book.add_sheet(sheet)

    if file_type == "xls":
        content_type = "application/vnd.ms-excel"
    elif file_type == "xlsx":
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif file_type == "ods":
        content_type = "application/vnd.oasis.opendocument.spreadsheet"

    filename = str(round).replace(" ", "-").lower() + "-scores." + file_type
    response = HttpResponse(book.export(file_type), content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "no-cache, must-revalidate, max-age=0, post-check=0, pre-check=0"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
def round_scores(request, round):
    round = get_object_or_404(models.Round, pk=round)
    rounds = (
        models.Round.current_rounds()
        .order_by("title")
        .values("id", "title")
        .annotate(total_applications=Count("applications"))
    )
    criteria = models.Criterion.where(round_id=round)

    return render(request, "round_scores.html", locals())


def status(request):
    """Check the application health status attempting to connect to the DB.

    NB! This entry point should be protected and accessible
    only form the application monitoring servers.
    """
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_timestamp" if cursor.db.vendor == "sqlite" else "SELECT now()"
            )
            now = cursor.fetchone()[0]
        total, used, free = shutil.disk_usage(__file__)
        free = round(free * 100 / total)
        return JsonResponse(
            {
                "status": "OK" if free > 5 else "FAIL",
                "db-timestamp": now if isinstance(now, str) else now.isoformat(),
                "free-storage-percent": free,
            },
            status=200 if free > 5 else 418,
        )
    except Exception as ex:
        capture_exception(ex)
        return JsonResponse(
            {
                "status": "Error",
                "message": str(ex),
            },
            status=503,
        )


class RoundSummary(AdminRequiredMixin, ExportMixin, SingleTableView):
    export_formats = ["xls", "xlsx", "csv", "json", "latex", "ods", "tsv", "yaml"]
    model = models.Application
    table_class = tables.RoundSummaryTable
    template_name = "table.html"
    extra_context = {"category": "applications"}
    paginator_class = django_tables2.paginators.LazyPaginator

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)
        data["rounds"] = (
            models.Round.current_rounds()
            .order_by("title")
            .values("id", "title")
            .annotate(total_applications=Count("applications"))
        )
        data["round"] = self.round
        return data

    @property
    def title(self):
        return self.round.title or self.round.scheme.title

    @property
    def round(self):
        return get_object_or_404(models.Round, pk=self.kwargs.get("round"))

    @property
    def export_name(self):
        return (
            models.Round.get(self.kwargs.get("round")).title
            if "round" in self.kwargs
            else "export"
        ) + "-summary"

    def get_queryset(self, *args, **kwargs):
        # round = get_object_or_404(models.Round, pk=self.kwargs.get("round"))
        return self.round.summary

        # queryset = queryset.filter(round=F("round__scheme__current_round"))
        # queryset = queryset.prefetch_related("round")
        # return queryset


def application_summary(request, number, lang=None):
    number = vignere.decode(number)
    a = get_object_or_404(models.Application, number=number)
    return HttpResponse(a.summary)


@login_required
def agent_declaration(request, lang=None):
    user = request.user
    if (
        (pks := request.GET.getlist("pk"))
        and (applications := models.Application.where(pk__in=pks).order_by("number"))
        and (
            round := models.Round.where(
                applications__in=applications.values_list("pk"), agent_declaration__isnull=False
            ).first()
        )
    ):
        org = models.Organisation.where(
            Q(pk__in=applications.values_list("org")),
            Q(pk__in=user.research_offices.values_list("org")),
        ).last()
        if applications.count() == 1:
            application = applications.first()
            pi = application.pi
        return HttpResponse(jinja2.Template(round.agent_declaration).render(locals()))
    return HttpResponse("")


def application_exported_view(request, number, lang=None):
    # remote_addr = request.META.get("REMOTE_ADDR")
    # if not remote_addr.startswith("127.0.0."):
    #     return remote_addr
    if not request.user.is_authenticated:
        number = vignere.decode(number)

    if number and number.isdecimal():
        application = get_object_or_404(models.Application, pk=number)
    else:
        application = get_object_or_404(models.Application, number=number)

    for_panellists = request.GET.get("for_panellists", False)
    round = application.round
    site = Site.objects.get_current()
    domain = site.domain
    site_id = site.pk

    logo = None
    if site_id == 2:
        logo = f"{settings.STATIC_URL}images/{domain}/alt_logo_small.png"
    elif site_id in [2, 4, 5]:
        # logo_1 = request.build_absolute_uri(f"{settings.STATIC_URL}images/MBIE_logo.jpg")
        # logo_2 = request.build_absolute_uri(f"{settings.STATIC_URL}images/RS_logo.png")
        logo_1 = f"{settings.STATIC_URL}images/MBIE_logo.jpg"
        logo_2 = f"{settings.STATIC_URL}images/RS_logo.png"
    elif site_id == 7:
        logo = f"{settings.STATIC_URL}images/pmspace-logo_small.jpg"

    if site_id in [2, 5]:
        referees = application.referees.order_by("testified_at")
        if round.required_referees:
            referees = referees[: round.required_referees]

    objects = application.get_testimonials()

    for_pdf_export = True
    return render(request, "application-export.html", locals())


@login_required
def user_files(request):
    if "error" in request.GET:
        raise Exception(request.GET["error"])

    # EthicsStatementForm = model_forms.modelform_factory(models.EthicsStatement, fields=["file"])

    EthicsStatementFormSet = modelformset_factory(
        models.EthicsStatement,
        fields=["file"],
        # form=EthicsStatementForm,
        extra=0,
        can_delete=True,
    )
    ethics_statement_queryset = models.EthicsStatement.where(
        application__submitted_by=request.user
    )
    ethics_statement_formset = EthicsStatementFormSet(
        request.POST or None,
        request.FILES or None,
        queryset=ethics_statement_queryset,
        prefix="es",
    )
    ethics_statement_formset.helper = FormHelper()
    ethics_statement_formset.helper.help_text_inline = True
    ethics_statement_formset.helper.html5_required = True
    ethics_statement_formset.helper.layout = Layout(
        forms.Div(
            forms.TableInlineFormset("ethics_statement_formset"),
            css_id="ethics_statements",
        )
    )

    identity_verification_queryset = models.IdentityVerification.where(user=request.user)
    IdentityVerificationFormSet = modelformset_factory(
        models.IdentityVerification,
        fields=["file"],
        # form=EthicsStatementForm,
        extra=0,
        can_delete=True,
    )
    identity_verification_formset = IdentityVerificationFormSet(
        request.POST or None,
        request.FILES or None,
        queryset=identity_verification_queryset,
        prefix="iv",
    )
    identity_verification_formset.helper = FormHelper()
    identity_verification_formset.helper.layout = Layout(
        forms.Div(
            forms.TableInlineFormset("identity_verification_formset"),
            css_id="identity_verifications",
        )
    )

    return render(request, "user_files.html", locals())


class SummaryReportList(LoginRequiredMixin, SingleTableMixin, FilterView):
    model = models.Application
    table_class = tables.SummaryReportTable
    template_name = "table.html"
    extra_context = {"category": "applications"}
    filterset_class = filters.ApplicationFilterSet
    paginator_class = django_tables2.paginators.LazyPaginator

    def get_queryset(self, *args, **kwargs):
        queryset = super().get_queryset(*args, **kwargs)
        queryset = queryset.filter(round=F("round__scheme__current_round"))
        queryset = queryset.prefetch_related("round")
        return queryset


def headers(request, application_id, page_count=1, output_type="pdf"):
    page_count = int(page_count)
    application = models.Application.get(application_id)
    if output_type != "pdf":
        return render(request, "headers.html", locals())
    template = get_template("headers.html")
    html = HTML(string=template.render(locals()))
    pdf_object = html.write_pdf()
    response = HttpResponse(pdf_object, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="headers.pdf"'
    response["Cache-Control"] = "no-cache, must-revalidate, max-age=0, post-check=0, pre-check=0"
    response["X-Content-Type-Options"] = "nosniff"
    return response


# class FTEInlineFormset(forms.TableInlineFormset):
#     template = "portal/application_document_formset.html"

#     def render(self, form, form_style, context, template_pack=TEMPLATE_PACK):
#         formset = context[self.formset_name_in_context]

#         required_documents = context["required_documents"]
#         round = context["round"]
#         ordering = dict(
#             round.required_documents.values_list("id", "ordering").order_by("ordering")
#         )
#         formset.forms.sort(key=lambda f: ordering.get(f.initial.get("required_document"), 0))
#         help_texts = {
#             rd_id: make_help_text(
#                 required_document=round.required_documents.filter(id=rd_id).first()
#             )
#             for rd_id in ordering.keys()
#         }
#         for f in formset.forms:
#             rd_id = f.initial.get("required_document", 0)
#             if rd_id:
#                 # f.file.help_text = help_texts.get(rd_id)
#                 f.fields["file"].help_text = help_texts.get(rd_id)
#                 f.form_label = f"{required_documents.get(rd_id, _('Document'))}"

#         return render_to_string(
#             self.template,
#             {
#                 "formset": formset,
#                 "form_id": self.form_id,
#                 "required_documents": required_documents,
#             },
#         )


class MemberFTEForm(ModelForm):
    # application = IntegerField(label="Application ID", required=False, widget=HiddenInput())

    def __init__(self, *args, **kwargs):
        duration = 3
        super().__init__(*args, **kwargs)
        for i in range(1, duration + 1):
            self.fields[f"FTE:{i}"] = IntegerField(required=False, initial=0)

    class Meta:
        model = models.Member
        # exclude = ["state"]
        fields = ["email", "first_name", "last_name", "user", "role"]


# inlineformset_factory(
#     models.Application, models.Member, form=MemberForm, extra=1, can_delete=True
# )


# class ReportList(LoginRequiredMixin, SingleTableView):
#     table_class = tables.ReportTable
#     model = models.Report
#     template_name = "table.html"
#     # extra_context = {"category": "applications"}

#     # def get_queryset(self, *args, **kwargs):
#     #     queryset = super().get_queryset(*args, **kwargs)
#     #     u = self.request.user
#     #     if not (u.is_superuser or u.is_staff):
#     #         queryset = queryset.filter(Q(inviter=u) | Q(email__in=u.email_addresses))
#     #     return queryset


class AffiliationForm(ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    class Meta:
        model = models.Affiliation
        fields = ["org", "type", "role", "qualification", "start_date", "end_date", "email"]

        # exclude = ["state"]
        # fields = ["email", "first_name", "middle_names", "last_name", "user", "role"]
        widgets = {
            "org": forms.TextInput(attrs={"class": "form-control"}),
            "type": forms.TextInput(attrs={"class": "form-control"}),
            "role": forms.TextInput(attrs={"class": "form-control"}),
            "qualification": forms.TextInput(attrs={"class": "form-control"}),
            "start_date": forms.TextInput(attrs={"class": "form-control"}),
            "end_date": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.TextInput(attrs={"class": "form-control"}),
        }


# class DemoForm(ModelForm):
#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#
#     class Meta:
#         model = models.Person
#         fields = ["code", "first_name", "last_name"]
#         # exclude = ["state"]
#         # fields = ["email", "first_name", "middle_names", "last_name", "user", "role"]
#         widgets = {
#             "code": forms.TextInput(attrs={"class": "form-control"}),
#             "first_name": forms.TextInput(attrs={"class": "form-control"}),
#             "last_name": forms.TextInput(attrs={"class": "form-control"}),
#         }
#
#     # class DemoForm(Form):
#     # field1 = fields.CharField(max_length=100, required=True)
#     # field2 = fields.CharField(max_length=50, required=True)
#     # field3 = fields.CharField(max_length=50, required=True)


# @login_required
# def demo_create(request):
#     form = DemoForm()
#     if request.method == "POST":
#         pass
#
#     return render(request, "partials/form.html", locals())


class PublicationList(LoginRequiredMixin, StateInPathMixin, SingleTableView):

    table_class = tables.PublicationTable
    model = models.Publication
    template_name = "table.html"
    extra_context = {"category": "reports"}
    template_name = "table.html"
    # filterset_class = filters.ReportFilterSet

    def get_queryset(self, *args, **kwargs):
        queryset = super().get_queryset(*args, **kwargs)
        if report_id := (self.request.GET.get("report") or self.request.GET.get("report_id")):
            queryset = queryset.filter(reports__id=report_id)
        return queryset


class PublicationViewMixin:

    model = models.Publication
    fields = "__all__"
    exclude = ["updated_at", "created_at"]
    widgets = {
        "status_date": forms.DateInput(),
        "citations_date": forms.DateInput(),
        "impact_year": forms.DateInput(attrs={"class": "yearpicker"}),
        "url": URLInput(),
        # "org": autocomplete.ModelSelect2("org-autocomplete"),
    }

    def get(self, *args, **kwargs):
        return super().get(*args, **kwargs)

    @cached_property
    def report_id(self):
        if report_id := (
            self.request.GET.get("report")
            or self.request.POST.get("report")
            or self.object.reports.order_by("-pk").values_list("pk", flat=True).first()
        ):
            return int(report_id)

    def ger_autor_formset(self):
        fsc = forms.inlineformset_factory(
            self.model,
            models.PublicationAuthor,
            fields=["name", "type"],
            extra=1,
            can_delete=True,
            # widgets={
            #     "name": forms.TextInput(attrs={"class": "form-control"}),
            #     "type": forms.NumberInput(attrs={"class": "form-control"}),
            # },
        )
        fs = fsc(self.request.POST or None, instance=self.object, prefix="authors")
        return fs

    def ger_link_formset(self):
        fsc = forms.inlineformset_factory(
            self.model,
            models.PublicationLink,
            fields=["link", "type"],
            extra=1,
            can_delete=True,
            # widgets={
            #     "name": forms.TextInput(attrs={"class": "form-control"}),
            #     "type": forms.NumberInput(attrs={"class": "form-control"}),
            # },
        )
        fs = fsc(self.request.POST or None, instance=self.object, prefix="links")
        return fs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.GET.get("_modal_dialog"):
            context["modal_dialog"] = True
        if report_id := self.report_id:
            context["report"] = report_id
        context["authors"] = self.ger_autor_formset()
        context["links"] = self.ger_link_formset()
        return context

    def get_template_names(self):
        if self.request.GET.get("_modal_dialog") or self.request.GET.get("_popup"):
            return ["partials/publication_form.html"]
        return super().get_template_names()

    def get_form_class(self):
        """Return the form class to use in this view."""
        return model_forms.modelform_factory(
            self.model, fields=self.fields, exclude=self.exclude, widgets=self.widgets
        )

    def get_form(self, form_class=None):
        form = super().get_form(form_class=form_class)
        form.helper = FormHelper()

        if self.request.GET.get("_modal_dialog"):
            form.helper.form_tag = False
        form.helper.layout = Layout(
            bootstrap.TabHolder(
                bootstrap.Tab(
                    _("Details"),
                    "title",
                    "title2",
                    "doi",
                    Row(Column("rsnz_ref"), Column("type")),
                    Row(Column("status"), Column("status_date")),
                    "host",
                    "journal",
                    "publisher",
                    "editor",
                    "location",
                    "url",
                    "volume",
                    "year_ref",
                    "page_ref",
                    "host_ref",
                    Row(Column("citations"), Column("citations_date")),
                    "abstract",
                    "uid",
                    Row(Column("impact_factor"), Column("impact_year")),
                    "xcr",
                    "isi_loc",
                    css_id="id_detail_tab",
                ),
                bootstrap.Tab(
                    _("Authors and links"),
                    forms.Fieldset(
                        _("Authors"),
                        forms.TableInlineFormset("authors"),
                    ),
                    forms.Fieldset(
                        _("Links"),
                        forms.TableInlineFormset("links"),
                    ),
                    css_id="id_authors_and_links_tab",
                ),
            )
        )
        if not self.request.GET.get("_modal_dialog"):
            form.helper.layout.append(
                bootstrap.FormActions(
                    layout.Submit("save", "Save changes"),
                    layout.Button("cancel", "Cancel", css_class="btn btn-secondary"),
                    css_class="float-right",
                ),
            )
        return form

    def get_success_url(self):
        if self.request.GET.get("_modal_dialog") or self.request.POST.get("_modal_dialog"):
            return self.request.path + f"?_modal_dialog=1&report={self.report_id}"
        if report_id := self.report_id:
            return reverse("publication-list") + f"?report={report_id}"
        return reverse("publication-update", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        resp = super().form_valid(form)
        authors = self.ger_autor_formset()
        if authors.is_valid():
            # authors.instance = self.object
            authors.save()
        links = self.ger_link_formset()
        if links.is_valid():
            links.save()
        if (
            self.object.pk
            and (report_id := self.report_id)
            and (report := get_object_or_404(models.Report, pk=report_id))
        ):
            if not report.publications.contains(self.object):
                report.publications.through.objects.create(report=report, publication=self.object)
            if self.request.GET.get("_modal_dialog") or self.request.POST.get("_modal_dialog"):
                return render(self.request, "partials/report_publication_list.html", locals())
        return resp


class PublicationUpdateView(PublicationViewMixin, UpdateView):
    pass


class PublicationCreateView(PublicationViewMixin, CreateView):
    pass


class ReportedFundingList(LoginRequiredMixin, StateInPathMixin, SingleTableView):
    table_class = tables.ReportedFundingTable
    model = models.ReportedFunding
    template_name = "table.html"
    extra_context = {"category": "reports"}
    template_name = "table.html"
    # filterset_class = filters.ReportFilterSet


class OrgWidget(s2forms.ModelSelect2Widget):

    theme = "bootstrap4"
    model = models.Organisation
    search_fields = ["name__icontains"]

    def filter_queryset(self, request, term, queryset=None, **dependent_fields):
        return self.model.search_query(term, queryset=queryset)

    def result_from_instance(self, obj, request):
        return {
            "id": obj[0],
            "text": obj[1],
            # 'extra_data': obj.extra_data,
        }


class ReportedFundingViewMixin:

    model = models.ReportedFunding
    fields = "__all__"
    exclude = ["updated_at", "created_at"]
    widgets = {
        "agency_name": forms.ModelSelect2NoPK(
            "org-name-autocomplete",
            attrs={"data-placeholder": _("Choose an agency or create a new one ...")},
        ),
        # "agency": autocomplete.ModelSelect2("org-autocomplete"),
        # "agency": s2forms.ModelSelect2Widget(
        #     model=models.Organisation,
        #     search_fields=["name__icontains"],
        #     attrs={"class": "form-control custom-select", "with": "100%"}
        # ),
        # "agency": OrgWidget(
        #     attrs={"class": "form-control custom-select", "with": "100%"},
        #     model=models.Organisation,
        # ),
        "end_date": forms.DateInput(),
        "report": HiddenInput(),
        "start_date": forms.DateInput(),
        "url": URLInput(),
    }

    @cached_property
    def report_id(self):
        if report_id := (self.request.GET.get("report") or self.request.POST.get("report")):
            return int(report_id)

    @property
    def report(self):
        if self.object and self.object.report:
            return self.object.report
        if self.report_id:
            return models.Report.where(pk=self.report_id).first()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.GET.get("_modal_dialog"):
            context["modal_dialog"] = True
        if report_id := self.report_id:
            context["report"] = report_id
        return context

    def get_initial(self):
        initial = super().get_initial() or {}
        initial["report"] = self.report_id
        initial["title"] = self.report.contract.project_title
        return initial

    def get_template_names(self):
        if self.request.GET.get("_modal_dialog") or self.request.GET.get("_popup"):
            return ["partials/reported_funding_form.html"]
        return super().get_template_names()

    def get_form_class(self):
        """Return the form class to use in this view."""
        return model_forms.modelform_factory(
            self.model, fields=self.fields, exclude=self.exclude, widgets=self.widgets
        )

    def get_form(self, form_class=None):
        form = super().get_form(form_class=form_class)
        form.helper = FormHelper()

        if self.request.GET.get("_modal_dialog"):
            form.helper.form_tag = False
        form.helper.layout = Layout(
            Row(Column("type"), Column("status")),
            "subtype",
            "title",
            "url",
            Row(Column("currency"), Column("amount"), Column("share")),
            Row(
                Column("agency_name", css_class="col-8"),
                # Column("agency", css_class="col-8"),
                Column("start_date", css_class="col-2"),
                Column("end_date", css_class="col-2"),
            ),
            "description",
        )
        if not self.request.GET.get("_modal_dialog"):
            form.helper.layout.append(
                bootstrap.FormActions(
                    layout.Submit("save", "Save changes"),
                    layout.Button("cancel", "Cancel", css_class="btn btn-secondary"),
                    css_class="float-right",
                ),
            )
        return form

    def form_valid(self, form):
        if (
            (i := form.instance)
            and i.agency_name
            and (
                org := models.Organisation.where(
                    Q(name=i.agency_name) | Q(legal_name=i.agency_name)
                )
                .order_by("-pk")
                .last()
            )
        ):
            i.org = org
        resp = super().form_valid(form)
        if self.request.GET.get("_modal_dialog") or self.request.POST.get("_modal_dialog"):
            report = self.report
            return render(self.request, "partials/report_funding_list.html", locals())
        return resp


class ReportedFundingUpdateView(ReportedFundingViewMixin, UpdateView):
    pass


class ReportedFundingCreateView(ReportedFundingViewMixin, CreateView):
    pass


class ReportedActivityViewMixin:

    # model = models.ReportedActivity
    fields = "__all__"
    exclude = ["updated_at", "created_at", "agency"]
    widgets = {
        # "agency": autocomplete.ModelSelect2("org-autocomplete"),
        # "agency": s2forms.ModelSelect2Widget(
        #     model=models.Organisation,
        #     search_fields=["name__icontains"],
        #     attrs={"class": "form-control custom-select", "with": "100%"}
        # ),
        "org": OrgWidget(
            attrs={"class": "form-control custom-select", "with": "100%"},
            model=models.Organisation,
        ),
        "end_date": forms.DateInput(),
        "report": HiddenInput(),
        "start_date": forms.DateInput(),
        "url": URLInput(),
    }

    def get_success_url(self):
        return ""

    @cached_property
    def report_id(self):
        if report_id := (self.request.GET.get("report") or self.request.POST.get("report")):
            return int(report_id)

    @property
    def report(self):
        if self.object and self.object.report:
            return self.object.report
        if self.report_id:
            return models.Report.where(pk=self.report_id).first()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.GET.get("_modal_dialog"):
            context["modal_dialog"] = True
        if report_id := self.report_id:
            context["report"] = report_id
        return context

    def get_initial(self):
        initial = super().get_initial() or {}
        initial["report"] = self.report_id
        initial["title"] = self.report.contract.project_title
        return initial

    def get_template_names(self):
        if self.request.GET.get("_modal_dialog") or self.request.GET.get("_popup"):
            return ["partials/reported_activity_form.html"]
        return super().get_template_names()

    def get_form_class(self):
        """Return the form class to use in this view."""
        return model_forms.modelform_factory(
            self.model, fields=self.fields, exclude=self.exclude, widgets=self.widgets
        )

    def get_form(self, form_class=None):
        form = super().get_form(form_class=form_class)
        form.helper = FormHelper()
        if self.request.GET.get("_modal_dialog") or self.request.POST.get("_modal_dialog"):
            form.helper.form_tag = False
        return form

    def form_valid(self, form):
        resp = super().form_valid(form)
        if self.request.GET.get("_modal_dialog") or self.request.POST.get("_modal_dialog"):
            report = self.report
            return render(self.request, "partials/reported_activity_list.html", locals())
        return resp


class ReportedAwardViewMixin(ReportedActivityViewMixin):

    model = models.ReportedAward
    fields = ["member", "description", "report"]

    def get_form(self, form_class=None):
        form = super().get_form(form_class=form_class)
        form.fields["member"].queryset = self.report.efforts.all().order_by("full_name", "role")
        form.fields["member"].label = _("Researcher")
        form.fields["member"].required = True
        form.fields["description"].label = _("Award")
        form.fields["description"].required = True
        # form.helper = FormHelper()

        # if self.request.GET.get("_modal_dialog"):
        #     form.helper.form_tag = False
        # form.helper.layout = Layout(
        #     Field("member", label=_("Researcher")), Field("description", label=_("Award"))
        # )
        # if not self.request.GET.get("_modal_dialog"):
        #     form.helper.layout.append(
        #         bootstrap.FormActions(
        #             layout.Submit("save", "Save changes"),
        #             layout.Button("cancel", "Cancel", css_class="btn btn-secondary"),
        #             css_class="float-right",
        #         ),
        #     )
        return form


class ReportedAwardUpdateView(ReportedAwardViewMixin, UpdateView):
    pass


class ReportedAwardCreateView(ReportedAwardViewMixin, CreateView):
    pass


class ReportedPublicityViewMixin(ReportedActivityViewMixin):

    model = models.ReportedPublicity
    fields = ["type", "description", "report"]

    def get_form(self, form_class=None):
        form = super().get_form(form_class=form_class)
        form.fields["description"].label = _("Details")
        form.fields["description"].required = True
        form.fields["type"].label = _("Activity")
        form.fields["type"].required = True
        form.fields["type"].widget = widgets.Select(
            choices=models.Choices(
                "Conference",
                "Newsletter",
                "Newspaper",
                "Outreach",
                "Popular Article",
                "Public Lecture",
                "Radio",
                "TV",
                "Other",
            )
        )
        return form


class ReportedPublicityUpdateView(ReportedPublicityViewMixin, UpdateView):
    pass


class ReportedPublicityCreateView(ReportedPublicityViewMixin, CreateView):
    pass


class ReportedCollaborationViewMixin(ReportedActivityViewMixin):

    model = models.ReportedCollaboration
    fields = ["full_name", "organisation", "country", "description", "report"]

    def get_form(self, form_class=None):
        form = super().get_form(form_class=form_class)
        form.fields["description"].label = _("Nature of Collaboration")
        form.fields["full_name"].label = _("Collaborator")
        form.fields["organisation"].label = _("Institution")
        return form


class ReportedCollaborationUpdateView(ReportedCollaborationViewMixin, UpdateView):
    pass


class ReportedCollaborationCreateView(ReportedCollaborationViewMixin, CreateView):
    pass


class ReportedVisitViewMixin(ReportedActivityViewMixin):

    model = models.ReportedVisit
    fields = ["member", "full_name", "organisation", "country", "description", "report"]

    def get_form(self, form_class=None):
        form = super().get_form(form_class=form_class)
        form.fields["member"].label = _("Visitor")
        form.fields["member"].required = True
        form.fields["member"].queryset = self.report.efforts.all().order_by("full_name", "role")
        form.fields["description"].label = _("Purpose")
        form.fields["description"].required = True
        form.fields["full_name"].label = _("Host")
        form.fields["organisation"].label = _("Institution")
        form.fields["organisation"].required = True
        return form


class ReportedVisitUpdateView(ReportedVisitViewMixin, UpdateView):
    pass


class ReportedVisitCreateView(ReportedVisitViewMixin, CreateView):
    pass


class ReportedHostedVisitViewMixin(ReportedActivityViewMixin):

    model = models.ReportedHostedVisit
    fields = ["organisation", "country", "visitor", "description", "report"]

    def get_form(self, form_class=None):
        form = super().get_form(form_class=form_class)
        form.fields["visitor"].label = _("Visitor")
        form.fields["visitor"].required = True
        form.fields["description"].label = _("Purpose")
        form.fields["description"].required = True
        form.fields["organisation"].label = _("External Institution")
        return form


class ReportedHostedVisitUpdateView(ReportedHostedVisitViewMixin, UpdateView):
    pass


class ReportedHostedVisitCreateView(ReportedHostedVisitViewMixin, CreateView):
    pass


class ReportedActivityView(View):

    award_view = staticmethod(ReportedAwardCreateView.as_view())
    publicity_view = staticmethod(ReportedPublicityCreateView.as_view())
    collaboration_view = staticmethod(ReportedCollaborationCreateView.as_view())
    visit_view = staticmethod(ReportedVisitCreateView.as_view())
    hosted_visit_view = staticmethod(ReportedHostedVisitCreateView.as_view())
    # bar_view = staticmethod(BarView.as_view())

    def dispatch(self, request, *args, **kwargs):
        category = request.GET.get("activity_category")

        if category == "A":
            return self.award_view(request, *args, **kwargs)
        elif category == "P":
            return self.publicity_view(request, *args, **kwargs)
        elif category == "C":
            return self.collaboration_view(request, *args, **kwargs)
        elif category == "V":
            return self.visit_view(request, *args, **kwargs)
        elif category == "H":
            return self.hosted_visit_view(request, *args, **kwargs)
        # else:
        #     return self.bar_view(request, *args, **kwargs)
        return super().dispatch(request, *args, **kwargs)


class ChangeRequestViewMixin:

    model = models.ChangeRequest
    # template_name = "profile_form.html"
    form_class = forms.ChangeRequestForm
    extra_context = {"category": "change_requests"}

    def get_form(self, form_class=None):
        form = super().get_form(form_class=form_class)
        form.helper.include_media = False

        if (contract := self.contract) and (pi := contract.pi):
            form.fields["new_host"].widget.forward.append(forward.Const(pi.pk, "user"))
        return form

    @cached_property
    def is_modal(self):
        return (
            self.request.GET.get("modal")
            or self.request.GET.get("_modal_dialog")
            or self.request.GET.get("_popup")
            or self.request.POST.get("_modal_dialog")
            or self.request.POST.get("_popup")
        )

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        if self.is_modal:
            context["modal_dialog"] = True
            context["modal"] = True
        context["is_transfer"] = (
            self.object and self.object.pk and self.object.types.filter(code="TR").exists()
        )
        return context

    def get_template_names(self):
        if self.is_modal:
            return ["partials/change_request_form.html"]
        return super().get_template_names()

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    @cached_property
    def contract(self):
        if hasattr(self.object, "contract"):
            return self.object.contract
        contract_pk = self.kwargs.get("pk")
        return get_object_or_404(models.Contract, pk=contract_pk)

    # def post(self, request, *args, **kwargs):
    #     return super().post(request, *args, **kwargs)

    def form_valid(self, form):

        u = self.request.user
        request = self.request
        contract = self.object and self.object.contract or self.contract
        org = contract and contract.org
        is_ro = org and org.is_ro(user=u) or not u.is_admin

        try:
            with transaction.atomic():

                i = form.instance
                if not i.contract_id:
                    i.contract = contract
                if i and not i.submitted_by and is_ro:
                    i.submitte_by = u
                resp = super().form_valid(form)

                if action := form.data.get("action"):
                    action = action.lower()
                    if action == "submit":
                        if i.state == "submitted" and u.is_admin:
                            i.request_resubmit(by=u, request=request)
                        else:
                            i.submit(user=u, by=u, request=request)
                    elif action == "approve":
                        i.approve(by=u, request=request)
                    elif action == "accept":
                        i.accept(by=u, request=request)
                    elif action == "reject":
                        i.reject(by=u, request=request)
                    elif action == "cancel":
                        i.cancel(by=u, request=request)
                    elif action in ["request_resubmit", "request_resubmission", "resubmit"]:
                        i.request_resubmit(by=u, request=request)
                    i.save()

                    #############################################
                    # if action in [
                    #     "accept",
                    #     "approve",
                    #     "cancel",
                    #     "reject",
                    #     "request_resubmission",
                    #     "resubmit",
                    #     "submit",
                    # ]:
                    #     if not org:
                    #         org = i.contract.org
                    #         is_ro = org.is_ro(user=u)

                    #     if is_ro:
                    #         fund = i.contract.fund
                    #         recipients = (
                    #             [fund.email]
                    #             if fund and fund.email
                    #             else i.contract.site.staff_users.all()
                    #         )
                    #     else:
                    #         recipients = (
                    #             [i.submitted_by]
                    #             if i.submitted_by
                    #             else i.contract.application.ro_recipients
                    #         )
                    #     url = reverse("change-request-update", args=[i.pk])
                    #     url = request.build_absolute_uri(url)
                    #     contract_url = request.build_absolute_uri(
                    #         reverse("contract", args=[i.contract.pk])
                    #     )
                    #     if action == "submit" and not (i.state == "submitted" and u.is_admin):
                    #         subject = f"Change Request {i.number} submitted by {u}"
                    #     elif action in ["request_resubmission", "resubmit", "reject", "cancel"] or (
                    #         i.state == "submitted" and u.is_admin
                    #     ):
                    #         subject = f"Change Request {i.number} required resubmission"
                    #     elif action == "approved":
                    #         subject = f"Change Request {i.number} approved by {u}"
                    #     else:
                    #         subject = f"Change Request {i.number} updated by {u}"

                    #     if action == "submit" and not (i.state == "submitted" and u.is_admin):
                    #         html_body = (
                    #             "<p>Tēnā koe,</p>"
                    #             f'<p>{u} has submitted a change request <a href="{url}">{i.number}</a> '
                    #             f'of the contract <a href="{contract_url}">{i.contract}</a></p>'
                    #             "<p>Please review the change request.</p>"
                    #         )
                    #     else:
                    #         html_body = (
                    #             "<p>Tēnā koe,</p>"
                    #             f'<p>{u} has update the change request <a href="{url}">{i.number}</a> '
                    #             f'of the contract <a href="{contract_url}">{i.contract}</a></p>'
                    #             "<p>Please review the changes and update the request.</p>"
                    #         )

                    #     send_mail(
                    #         subject,
                    #         html_message=html_body,
                    #         recipients=recipients,
                    #         cc=(
                    #             i.contract.application.ro_recipients
                    #             if not is_ro
                    #             and i.submitte_by
                    #             and i.contract.application.round.notify_ro_on_application_submission
                    #             else None
                    #         ),
                    #         fail_silently=False,
                    #         from_email="contracts",
                    #         request=request,
                    #         reply_to=u.email if u else settings.DEFAULT_FROM_EMAIL,
                    #         thread_index=i.contract.thread_index,
                    #         thread_topic=i.contract.thread_topic,
                    #     )

                    #     emails = [getattr(r, "email", r) or str(r) for r in recipients]
                    #     messages.success(
                    #         request,
                    #         f"Notification of change request {i.number} sent to {', '.join(emails)}.",
                    #     )
                    #########

                    reset_cache(request)
                    if action == "accept":
                        return redirect(reverse("contract-update", args=[i.derivative.pk]))

            return resp

        except Exception as ex:
            form.add_error(None, ex)
            return self.form_invalid(form)


class ChangeRequestCreateView(ChangeRequestViewMixin, CreateView):

    def get_initial(self):
        initial = super().get_initial()
        initial["contract"] = self.contract
        initial["submitted_by"] = self.request.user
        return initial


class ChangeRequestUpdateView(LoginRequiredMixin, ChangeRequestViewMixin, UpdateView):
    pass


class ChangeRequestList(LoginRequiredMixin, StateInPathMixin, SingleTableMixin, FilterView):
    table_class = tables.ChangeRequestTable
    model = models.ChangeRequest
    template_name = "table.html"
    extra_context = {"category": "change_requests"}
    filterset_class = filters.ChangeRequestFilterSet

    # def get_table_kwargs(self):
    #     u = self.request.user
    #     if u.is_staff or u.is_site_staff:
    #         return {
    #             "extra_columns": [
    #                 (
    #                     _("Export"),
    #                     django_tables2.LinkColumn(
    #                         "contract-export",
    #                         args=[django_tables2.A("pk")],
    #                         orderable=False,
    #                         # kwargs={"format": "pdf", "pk": django_tables2.A("pk")},
    #                         text=gettext_lazy("Export"),
    #                         attrs={
    #                             "a": {
    #                                 "class": "btn btn-primary btn-sm",
    #                                 # "target": "_blank",
    #                                 "data-toggle": "tooltip",
    #                                 "title": gettext_lazy(
    #                                     "Export the contract into a consolidated PDF file"
    #                                 ),
    #                             },
    #                             "td": {"class": "text-center"},
    #                         },
    #                     ),
    #                 )
    #             ]
    #         }
    #     return {}

    # def get(self, *args, **kwargs):
    #     resp = super().get(*args, **kwargs)
    #     return resp

    def get_queryset(self, *args, **kwargs):
        u = self.request.user
        return self.model.user_objects(
            queryset=super().get_queryset(*args, **kwargs), user=u, request=self.request
        ).distinct()


class ChangeRequestDetail(DetailView):
    template_name = "detail.html"
    model = models.ChangeRequest
    # slug_field = "number"
    # slug_url_kwarg = "number"

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        u = self.request.user
        if (
            u.is_superuser
            or u.is_staff
            or u.is_site_staff
            or (
                self.object
                and (org := self.object.contract.org or self.object.contract.application.org)
                and org.research_offices.filter(user=u).exists()
            )
        ):
            context["can_edit"] = True
        context["category"] = "change_requests"
        context["extra_details"] = {
            "PI": self.object.contract.pi,
            _("Project Title"): self.object.contract.project_title,
        }
        return context

    # def get_queryset(self):
    #     u = self.request.user
    #     qs = (
    #         super()
    #         .get_queryset()
    #         .prefetch_related(
    #             Prefetch(
    #                 "allocations", queryset=models.Allocation.objects.all().order_by("period")
    #             ),
    #             Prefetch(
    #                 "reporting_schedule",
    #                 queryset=models.ReportingScheduleEntry.objects.all().order_by(
    #                     "period", "due_date"
    #                 ),
    #             ),
    #         )
    #     )
    #     if not (u.is_superuser or u.is_site_staff):
    #         qs = qs.filter(Q(members__user=u) | Q(org__research_offices__user=u)).distinct()
    #     return qs


@login_required
def survey_response(request, referee_id):
    r = get_object_or_404(models.Referee, pk=referee_id)
    u = request.user
    survey_id = r.survey_id

    if not (u.is_admin or r.user != u):
        messages.error(request, _("You have no permission to view this referee report"))
        return redirect(request.META.get("HTTP_REFERER") or "start")
    if not r.survey_completed_at:
        messages.error(request, _("The survey has not yet been completed..."))
        return redirect(request.META.get("HTTP_REFERER") or "start")
    exclude_confidential = request.GET.get("exclude_confidential", False)
    exclude_scores = request.GET.get("exclude_scores", False)
    output_format = request.GET.get("format", "html")
    filename = f"{r}.{output_format}"
    mime_type, _encoding = mimetypes.guess_type(filename)
    output = r.get_response(
        output_format=output_format,
        exclude_confidential=exclude_confidential,
        exclude_scores=exclude_scores,
    )
    if isinstance(output, dict) and (status := output.get("status")):
        messages.error(request, status)
        return redirect(request.META.get("HTTP_REFERER") or "start")
    if not output_format or output_format in ["html", "htm"]:
        return HttpResponse(output, content_type="text/html; charset=utf-8")

    output.seek(0)
    response = FileResponse(output, content_type=mime_type)
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    response["Cache-Control"] = "no-cache, must-revalidate, max-age=0, post-check=0, pre-check=0"
    response["X-Content-Type-Options"] = "nosniff"
    return response


# @api_view(["GET", "PUT", "POST"])
# @authentication_classes([TokenAuthentication])
# @permission_classes([IsAuthenticated])
# def handle_email(request):
#     data = json.loads(request.body)
#     # https://puanga.prodata.nz/limesurvey/printanswers/view?surveyid=655512
#     # https://puanga.prodata.nz/limesurvey/statistics_user/655512?language=en
#     # capture_message(f"incoming request form lime survey:\n{request.body}\n\n\n{data}")
#     pass


@login_required
@require_http_methods(["PUT", "POST"])
def toggle_favorite(request, content_type_id, object_id):
    content_type = get_object_or_404(ContentType, id=content_type_id)
    # Basic security check to prevent favoring unauthorized models
    if content_type.model not in ["post", "product"]:
        return HttpResponse("Invalid content type", status=400)

    try:
        obj = content_type.get_object_for_this_type(id=object_id)
    except obj.DoesNotExist:
        return HttpResponse("Object not found", status=404)

    favorite, created = models.Favorite.objects.get_or_create(
        user=request.user, content_type=content_type, object_id=object_id
    )

    if not created:
        # If it already existed, unfavorite it
        favorite.delete()
        is_favorited = False
    else:
        # If it was created, it is now favorited
        is_favorited = True

    # Render a small template fragment to update the UI
    context = {
        "is_favorited": is_favorited,
        "object_id": object_id,
        "content_type_id": content_type_id,
        # You might also want to pass the count of favorites
    }
    return HttpResponse(
        render_to_string("partials/favorite_button.html", context, request=request)
    )


# @login_required
# def demo(request, pk=None):
#     # a = Application.get(1683)
#     a = Application.where(pk=pk).last() if pk else Application.last()
#     obj = models.Person.where(pk=pk).last() if pk else models.Person.last()
#
#     duration = 3
#     MemberFTEFormSet = forms.inlineformset_factory(
#         models.Application,
#         models.Member,
#         form=MemberFTEForm,
#         formset=forms.MandatoryApplicationFormInlineFormSet,
#         exclude=["state"],
#         edit_only=True,
#         can_delete_extra=False,
#     )
#     AffiliationFormSet = forms.inlineformset_factory(
#         models.Person,
#         models.Affiliation,
#         # form=MemberFTEForm,
#         # formset=forms.MandatoryApplicationFormInlineFormSet,
#         exclude=["put_code"],
#         edit_only=True,
#         can_delete_extra=False,
#     )
#     if request.method == "POST":
#         # form = DemoForm(number_of_fields=5, data=request.POST, prefix="demo")
#         # formset = MemberFTEFormSet(request.POST, instance=a, prefix="demo")
#         formset = AffiliationFormSet(request.POST, instance=obj, prefix="demo")
#         form = DemoForm(data=request.POST or None, instance=obj)
#
#         if formset.is_valid():
#             pass
#     else:
#         form = DemoForm(instance=obj)
#         # formset = MemberFTEFormSet(instance=a, prefix="demo")
#         formset = AffiliationFormSet(instance=obj, prefix="demo")
#
#     form.helper = FormHelper()
#     form.helper.help_text_inline = True
#     form.helper.html5_required = True
#     form.helper.layout = Layout(
#         forms.Div(
#             forms.TableInlineFormset("formset"),
#             css_id="demo",
#         )
#     )
#
#     # # formset.helper = FormHelper()
#     # # formset.helper.help_text_inline = True
#     # # formset.helper.html5_required = True
#     # # formset.helper.layout = Layout(
#     # #     forms.Div(
#     # #         forms.TableInlineFormset("formset"),
#     # #         css_id="demo",
#     # #     )
#     # # )
#     #
#     # return render(request, "demo.html", locals())


# def accel(request):
#     "/home/app/prod/portal/media/rounds/test.txt"
#     return

# def send_notification(registration_ids=None, message_title="TEST TITLE", message_desc="You are welcome!"):
#     fcm_api = ""
#     url = "https://fcm.googleapis.com/fcm/send"

#     headers = {
#         "Content-Type":"application/json",
#         "Authorization": 'key=fzVeTUir8hFXNE2tT-5117:APA91bHdLd1UFWqlATjOuz3YyHeBI8UonoudJkKoYfAz4sdxHIenxsXBkUXeuTomns-LJMz1B6-OTSBaW_I25zFi6d5l8Z9WTgT2tVcNVVSxwq00YnCtW4aMUBB8mQV7lUHD1NX22MgF'
#     }

#     payload = {
#         "registration_ids" :registration_ids,
#         "priority" : "high",
#         "notification" : {
#             "body" : message_desc,
#             "title" : message_title,
#             "image" : "https://i.ytimg.com/vi/m5WUPHRgdOA/hqdefault.jpg?sqp=-oaymwEXCOADEI4CSFryq4qpAwkIARUAAIhCGAE=&rs=AOn4CLDwz-yjKEdwxvKjwMANGk5BedCOXQ",
#             "icon": "https://yt3.ggpht.com/ytc/AKedOLSMvoy4DeAVkMSAuiuaBdIGKC7a5Ib75bKzKO3jHg=s900-c-k-c0x00ffffff-no-rj",

#         }
#     }

#     result = requests.post(url,  data=json.dumps(payload), headers=headers )
#     print(result.json())


# def FirebaseJS(request):
#     return HttpResponse(
#         """
# importScripts('https://www.gstatic.com/firebasejs/8.10.1/firebase-app.js');
# importScripts('https://www.gstatic.com/firebasejs/8.10.1/firebase-messaging.js');
# const firebaseConfig = {
#     apiKey: "AIzaSyB_8gnIoL0HZ82UZiKQREJ17RRRtkM0bX4",
#     authDomain: "pmspp-273112.firebaseapp.com",
#     projectId: "pmspp-273112",
#     storageBucket: "pmspp-273112.appspot.com",
#     messagingSenderId: "505794998992",
#     appId: "1:505794998992:web:54350149a523eef0c764d5",
#     measurementId: "G-FHVXYJD580"
# };
# firebase.initializeApp(firebaseConfig);
# const messaging = firebase.messaging();

# messaging.onBackgroundMessage((payload) => {
#   console.log(
#     '[firebase-messaging-sw.js] Received background message ',
#     payload
#   );
#   // Customize notification here
#   const notificationTitle = 'Background Message Title';
#   const notificationOptions = {
#     body: 'Background Message body.',
#     icon: '/firebase-logo.png'
#   };

#   self.registration.showNotification(notificationTitle, notificationOptions);
# });

# /*
# messaging.setBackgroundMessageHandler(function (payload) {
#     console.log(payload);
#     const notification=JSON.parse(payload);
#     const notificationOption={
#         body:notification.body,
#         icon:notification.icon
#     };
#     return self.registration.showNotification(payload.notification.title,notificationOption);
# })
# */
# """,
#         content_type="text/javascript",
#     )


# vim:set ft=python.django:
