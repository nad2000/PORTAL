import io
import json
import os
import shutil
import traceback
from functools import wraps
from urllib.parse import quote

import django.utils.translation
import django_filters
import django_tables2
import tablib
from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount, SocialApp
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Field, Layout
from dal import autocomplete
from dateutil.parser import parse
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import (
    AccessMixin,
    LoginRequiredMixin,
    UserPassesTestMixin,
)
from django.contrib.flatpages.models import FlatPage
from django.contrib.flatpages.views import flatpage
from django.contrib.sites.models import Site
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.db.models import (
    Count,
    Exists,
    F,
    FilteredRelation,
    Func,
    OuterRef,
    Prefetch,
    ProtectedError,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.forms import (
    DateInput,
    Form,
    HiddenInput,
    ModelForm,
    TextInput,
    ValidationError,
    modelformset_factory,
)
from django.forms import models as model_forms
from django.forms import widgets
from django.http import FileResponse, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render, reverse
from django.template.loader import get_template
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.functional import cached_property
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views import View
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_http_methods
from django.views.generic import DetailView as _DetailView
from django.views.generic import TemplateView
from django.views.generic.edit import CreateView as _CreateView
from django.views.generic.edit import UpdateView
from django_filters.views import FilterView
from django_tables2 import SingleTableMixin, SingleTableView
from django_tables2.export import ExportMixin
from extra_views import (
    CreateWithInlinesView,
    InlineFormSetFactory,
    ModelFormSetView,
    UpdateWithInlinesView,
)
from limesurveyrc2api.limesurvey import LimeSurvey
from private_storage.views import PrivateStorageDetailView
from PyPDF2 import PdfFileMerger
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import IsAuthenticated
from sentry_sdk import capture_exception, capture_message, last_event_id
from weasyprint import HTML

from . import forms, models, tables
from .forms import Submit
from .models import Application, Profile, ProfileCareerStage, Subscription, User
from .pyinfo import info
from .utils import send_mail, vignere
from .utils.orcid import OrcidHelper

# from .tasks import notify_user


def __(s):
    """Temporarily disabale 'gettex'"""
    return s


def reset_cache(request):
    cache.delete(f"{request.user.username}:{settings.SITE_ID}")


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
    site_id = settings.SITE_ID
    if site_id == 3 or site_id == 4:
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
    site_id = settings.SITE_ID
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


@user_passes_test(lambda u: u.is_superuser or u.is_staff)
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


def shoud_be_onboarded(function):
    """
    Check if the authentication user has a profile.  If it is missing,
    the user gets redirected to 'on-board' to create a profile.

    If the user is on-board, add the profile to the request object.
    """

    @wraps(function)
    def wrap(request, *args, **kwargs):
        user = request.user
        profile = Profile.where(user=user).first()
        if not profile or not profile.is_completed:
            view_name = "profile-create"
            if profile:
                if not profile.is_employments_completed:
                    view_name = "profile-employments"
                elif not profile.is_career_stages_completed:
                    view_name = "profile-career-stages"
                elif not profile.is_external_ids_completed:
                    view_name = "profile-external-ids"
                elif not profile.is_cvs_completed:
                    view_name = "profile-cvs"
                elif not profile.is_academic_records_completed:
                    view_name = "profile-academic-records"
                elif not profile.is_recognitions_completed:
                    view_name = "profile-recognitions"
                elif not profile.is_professional_bodies_completed:
                    view_name = "profile-professional-records"
            messages.info(
                request,
                _(
                    "Your profile is not completed yet. "
                    "Please complete your profile or skip it."
                ),
            )
            return redirect(reverse(view_name) + "?next=" + quote(request.get_full_path()))
        request.profile = profile
        return function(request, *args, **kwargs)

    return wrap


@login_required
def logout(request):
    account_logout = reverse("account_logout")

    if request.user.has_rapidconnect_account:
        return_url = request.build_absolute_uri(account_logout)
        if (
            sa := SocialApp.objects.filter(
                sites__id=settings.SITE_ID, provider="rapidconnect"
            ).first()
        ) and (id_value := sa.client_id.split("/")[-1]):
            return redirect(f"{settings.RAPIDCONNECT_LOGOUT}?id={id_value}&return={return_url}")
        return redirect(f"{settings.RAPIDCONNECT_LOGOUT}?return={return_url}")

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


class AdminRequiredMixin(AccessMixin):
    """Verify that the current user is admin or staff."""

    def dispatch(self, request, *args, **kwargs):
        if not (u := request.user) or not u.is_authenticated or not (u.is_superuser or u.is_staff):
            messages.error(request, _("Only the administrator can access this page"))
            return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)


class StateInPathMixin:
    @property
    def state(self):
        if (
            state := self.request.GET.get("state") or self.request.path.split("/")[-1]
        ) and state in ["new", "draft", "submitted", "archived", "approved", "cancelled"]:
            return state

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if state := self.state:
            context["state"] = state
        return context

    def get_queryset(self, *args, **kwargs):
        queryset = super().get_queryset(*args, **kwargs)
        if state := self.state:
            if self.model is models.Testimonial:
                if state == "draft":
                    queryset = queryset.filter(evaluations__state__in=["draft", "new"])
                else:
                    queryset = queryset.filter(evaluations__state=state)
            if self.model is models.Nomination:
                if state == "draft":
                    queryset = queryset.filter(status__in=["draft", "new"])
                else:
                    queryset = queryset.filter(status=state)
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
                else:
                    # queryset = queryset.filter(state=state)
                    u = self.request.user
                    if (site_id := settings.SITE_ID == 4) and (
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


class AccountView(LoginRequiredMixin, TemplateView):
    template_name = "account.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        u = self.request.user
        context["user"] = u
        context["emails"] = list(EmailAddress.objects.filter(~Q(email=u.email), user=u))
        context["accounts"] = list(SocialAccount.objects.filter(user=u))
        return context


class CreateUpdateView(LoginRequiredMixin, UpdateView):
    """A trick to make create and update view in a single view."""

    template_name = "form.html"

    def get_object(self, queryset=None):
        try:
            return super().get_object(queryset)
        except AttributeError:
            return None

    def get_success_url(self):
        try:
            return super().get_success_url()
        except:
            return (
                self.request.GET.get("next")
                or self.request.META.get("HTTP_REFERER")
                or reverse("home")
            )


class DetailView(LoginRequiredMixin, _DetailView):
    template_name = "detail.html"

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context["exclude"] = [
            "id",
            "created_at",
            "updated_at",
            "org",
            "site",
        ]
        context["update_view_name"] = f"{self.model.__name__.lower()}-update"
        context["update_button_name"] = _("Edit")
        if self.model and self.model in (models.Application, models.Testimonial):
            context["export_button_view_name"] = f"{self.model.__name__.lower()}-export"
        return context


class CreateView(LoginRequiredMixin, _CreateView):
    def get_success_url(self):
        try:
            return super().get_success_url()
        except:
            return (
                self.request.GET.get("next")
                or self.request.META.get("HTTP_REFERER")
                or reverse("home")
            )


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
    # capture_message(f"incoming reeust form lime survey:\n{request.body}\n\n\n{data}")
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
                        or User.where(Q(email=r.email) | Q(emailaddress__email=r.email)).first()
                    )
                    for t in models.Testimonial.where(referee=r):
                        if t.state != "submitted":
                            t.submit(by=by, description=description)
                            t._change_reason = description
                            t.save()
                            break
                    else:
                        if models.Referee.get(r.pk).status != "testified":
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
def complete_survey(request):
    """Handle complition of the surervy"""
    # capture_message(f"COMPLETED:\n{request.GET}\n\n\n{request}")
    q = (
        models.Referee.where(
            Q(user=request.user) | Q(email=request.user.email),
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
    instance = Subscription.where(email=email).order_by("-id").first()

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
            recipient_list=[email],
            fail_silently=False,
            token=token,
            request=request,
        )

    return render(request, "account/verification_sent.html", locals())


@require_http_methods(["GET", "POST"])
def confirm_subscription(request, token):
    log_entry = get_object_or_404(models.MailLog, token=token)
    subscription = get_object_or_404(models.Subscription, email=log_entry.recipient)
    if request.method == "POST":
        is_confirmed = bool(request.POST.get("subscribe"))
        subscription.is_confirmed = is_confirmed
        subscription.save()
        messages.info(
            request,
            _("Thank you for subscribing to our newsletter.")
            if is_confirmed
            else _("We will miss you"),
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
    if "error" in request.GET:
        raise Exception(request.GET["error"])
    user = request.user
    round = get_object_or_404(models.Round, id=round)
    applications = Application.where(round=round).values("state").annotate(total=Count("state"))
    total_applications = sum(a["total"] for a in applications)

    nominations = (
        models.Nomination.where(round=round).values("status").annotate(total=Count("status"))
    )
    total_nominations = sum(n["total"] for n in nominations)

    return render(request, "round_detail.html", locals())


def get_survey_api_url():
    if "LIMESURVEY_API_URL" in dir(settings):
        return settings.LIMESURVEY_API_URL
    elif server_url := settings.LIMESURVEY_SERVER_URL:
        return f"{server_url}/admin/remotecontrol"
    else:
        site = Site.objects.get_current()
        return f"https://{site.domain}/limesurvey/admin/remotecontrol"


def do_survey(request, survey_id=None, token=None, referee_id=None):
    if not request.user.is_authenticated:
        if token := request.GET.get("token"):
            if i := models.Invitation.where(token=token).first():
                if i.status == "revoked":
                    messages.warning(
                        request,
                        _("The invitation has been revoked and is not any more valid."),
                    )
                else:
                    request.session["invitation_token"] = token

        user_exists = (
            i and User.objects.filter(Q(email=i.email) | Q(emailaddress__email=i.email)).exists()
        )
        if request.user and not request.user.is_authenticated:
            return redirect(
                reverse("account_login" if user_exists else "account_signup")
                + f"?next={quote(request.get_full_path())}"
            )

    profile = Profile.where(user=request.user).last()
    if not profile or not profile.is_completed:
        return redirect(reverse("check-profile") + f"?next={quote(request.get_full_path())}")

    reset_cache(request)
    if referee_id:
        if (
            r := models.Referee.objects.prefetch_related("application", "application__round")
            .filter(id=referee_id)
            .first()
        ):
            survey_id = r.application.round.survey_id
        else:
            messages.warning(
                request,
                _("You have been removed from the list of the application referees."),
            )
            return redirect("index")

    if not r.survey_completed_at:
        api = r.survey_api
        if not r.survey_token_id:
            r.add_to_survey(api)
            r.save()

        properties = api.token.get_participant_properties(survey_id, r.survey_token_id)
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
                    if r.status != "testified":
                        r.testify(request=request)
                    r.save()

    if r.survey_completed_at:
        messages.warning(
            request,
            _(f"The referee report has been already completed at <b>{r.survey_completed_at}</b>."),
        )
        return redirect(request.META.get("HTTP_REFERER", "index"))

    return redirect(r.survey_url)


@login_required
@shoud_be_onboarded
@csrf_protect
def index(request):
    site_id = settings.SITE_ID
    if request.resolver_match.view_name == "start":
        reset_cache(request)
    if "error" in request.GET:
        raise Exception(request.GET["error"])
    user = request.user
    is_ro = models.ResearchOffice.where(user=user).exists()
    has_ro = models.ResearchOffice.where(
        Q(
            org__in=Subquery(
                models.Affiliation.where(profile__user=user, end_date__isnull=True).values(
                    "org_id"
                )
            )
        )
    ).exists()
    outstanding_invitations = models.Invitation.outstanding_invitations(user)
    if request.user.is_approved:
        if is_ro and site_id != 4 and request.resolver_match.view_name == "index0":
            return render(request, "research_office_index.html", locals())
        outstanding_authorization_requests = models.Member.outstanding_requests(user)
        outstanding_testimonial_requests = models.Referee.outstanding_requests(user)
        outstanding_review_requests = models.Panellist.outstanding_requests(user)
        outstanding_nominations = models.Nomination.where(
            status__in=["sent", "submitted"], user=user
        )
        draft_applications = models.Application.user_draft_applications(user).filter(
            ~Q(round__panellists__user=user),
            round__in=models.Scheme.objects.values("current_round"),
        )
        current_applications = models.Application.user_applications(
            user, ["submitted", "review", "accepted"]
        ).filter(
            ~Q(round__panellists__user=user),
            round__in=models.Scheme.objects.values("current_round"),
        )
        if user.is_staff or user.is_superuser:
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
        schemes = models.SchemeApplication.get_data(user)
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
            site_id == 4
            and request.method == "POST"
            and (message := request.POST.get("message", "").strip())
            and (round_id := request.POST.get("round"))
            and (request_round := models.Round.where(id=round_id).first())
        ):
            is_ajax = not request.META.get("HTTP_ACCEPT", "").startswith("text/html")
            research_officers = User.where(
                research_offices__org__in=Subquery(
                    models.Affiliation.where(profile__user=user, end_date__isnull=True).values(
                        "org_id"
                    )
                )
            )
            if research_officers.count() > 0:
                try:
                    recipient_list = [
                        (ro.full_name or _("Research Office"), ro.email)
                        for ro in research_officers
                    ]
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
                        recipient_list=recipient_list,
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
    try:
        if not request.user.is_authenticated:
            invitation = models.Invitation.where(token=token).first()
            user_exists = invitation and (
                User.objects.filter(email=invitation.email).exists()
                or EmailAddress.objects.filter(email=invitation.email).exists()
            )

            if token:
                request.session["invitation_token"] = token
                if (i := models.Invitation.where(token=token).first()) and i.status == "revoked":
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
        u = request.user
        if not token:
            if (
                i := models.Invitation.where(
                    Q(status__isnull=True)
                    | Q(status__in=["draft", "submitted", "sent", "bounced"])
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
                    i.email == u.email
                    or u.emailaddress_set.filter(email=i.email, verified=True).exists()
                ):
                    messages.warning(
                        request,
                        _(
                            "The invitation was not sent to any of this profile's email addresses. "
                            "Please use and log in with the account that is linked with the email "
                            "address that received the invitation."
                        ),
                    )
                    return redirect(next_url or "home")

            else:
                messages.warning(request, _("There is no invitation with the given token."))
                return redirect(next_url or "home")

            if i.status in ["draft", "submitted", "sent", "bounced"]:
                u = User.get(request.user.id)
                if i.first_name and not u.first_name:
                    u.first_name = i.first_name
                if i.middle_names and not u.middle_names:
                    u.middle_names = i.middle_names
                if i.last_name and not u.last_name:
                    u.last_name = i.last_name
                if not u.name:
                    u.name = u.full_name
                u.is_approved = True
                u.save()

                if i.email and u.email != i.email:
                    ea, created = EmailAddress.objects.get_or_create(
                        email=i.email, defaults=dict(user=u, verified=True)
                    )
                    if not created and ea.user != u:
                        messages.warning(
                            request, _("there is already user with this email address: ") + i.email
                        )

                i.accept(by=u, request=request)
                i.save()
                reset_cache(request)

            elif i.status == "revoked":
                messages.warning(
                    request,
                    _("The invitation has been revoked and is not any more valid."),
                )
            elif i.status == "accepted":
                messages.warning(
                    request,
                    _("The invitation has been already accepted."),
                )

            if i.status != "accepted":
                next_url = i.handler_url
            else:
                if i.type == "A" and (n := i.nomination):
                    if not n.user:
                        n.user = u
                        n.save(updated_fields=["user"])
                    if a := n.application:
                        if a.submitted_by == u:
                            next_url = reverse("application-update", kwargs={"pk": a.id})
                        else:
                            next_url = reverse("application", kwargs={"pk": a.id})
                    else:
                        next_url = reverse("application-create", kwargs={"round": n.round_id})
                elif i.type == "T" and (m := i.member) and (a_id := m.application_id):
                    next_url = reverse("application", kwargs={"pk": a_id})
                elif i.type == "R" and (r := i.referee):
                    if t := models.Testimonial.where(referee=r).last():
                        next_url = reverse("testimonial-detail", kwargs={"pk": t.id})
                    elif a_id := r.application_id:
                        next_url = reverse("application", kwargs={"pk": a_id})

        if Profile.where(user=request.user).exists() and request.user.profile.is_completed:
            if token and (
                i := models.Invitation.where(
                    token=token, type="P", panellist__isnull=False
                ).first()
            ):
                next_url = reverse("round-coi", kwargs=dict(round=i.panellist.round_id))

            return redirect(next_url or "home")
        else:
            messages.info(request, _("Please complete your profile or skip it."))
            return redirect(
                reverse("profile-update")
                if Profile.where(user=request.user).exists()
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
        redirect("profile")
        if models.Profile.where(user=u).exists()
        else redirect("profile-create")
    )


class ProfileView:
    model = models.Profile
    template_name = "profile_form.html"
    form_class = forms.ProfileForm

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
                Q(status__isnull=True)
                # | Q(status__in=["draft", "submitted", "sent", "bounced"])
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
            u = self.request.user
            if not Profile.where(user=u).exists() or not u.profile.is_completed:
                kwargs["progress"] = 10
                self.request.session["wizard"] = True

        if "user_form" not in kwargs:
            kwargs["user_form"] = self.get_user_form()

        return super().get_context_data(**kwargs)

    def get_success_url(self):
        if not self.request.user.profile.is_completed:
            return reverse(ProfileSectionFormSetView.section_views[0])
        return super().get_success_url()

    def post(self, request, *args, **kwargs):
        form = self.get_user_form()
        if not form.is_valid():
            return self.form_invalid(form)
        form.save()
        reset_cache(self.request)
        return super().post(request, *args, **kwargs)


@login_required
@csrf_exempt
def disable_profile_protection_patterns(request):
    if request.method == "POST":
        if profile := models.Profile.where(user=request.user).first():
            models.ProfileProtectionPattern.where(profile=profile).delete()
            profile.has_protection_patterns = False
            profile.save()
    return HttpResponse(status=204)


@login_required
@shoud_be_onboarded
def profile_protection_patterns(request):
    profile = request.profile
    if request.method == "POST":
        no_protection_needed = "no_protection_needed" in request.POST
        rp = request.POST
        pp_codes = rp.getlist("pp_code")
        pp_flags = {ppc: f"pp_enabled:{ppc}" in rp.keys() for ppc in pp_codes}
        if not no_protection_needed and not any(pp_flags.values()):
            no_protection_needed = True
        profile.has_protection_patterns = not no_protection_needed
        profile.save()

        if not no_protection_needed:
            expires_on_dates = rp.getlist("expires_on")
            for idx, ppc in enumerate(pp_codes):
                if pp_flags[ppc]:
                    ppp, _ = models.ProfileProtectionPattern.objects.get_or_create(
                        protection_pattern_id=ppc, profile=profile
                    )
                    expires_on = expires_on_dates[idx]
                    if expires_on:
                        ppp.expires_on = expires_on
                        ppp.save()

                else:
                    models.ProfileProtectionPattern.where(
                        protection_pattern_id=ppc, profile=profile
                    ).delete()
        else:
            models.ProfileProtectionPattern.where(profile=profile).delete()
        if "wizard" in request.session:
            del request.session["wizard"]
            request.session.modified = True
            i = models.Invitation.user_inviations(request.user).filter(~Q(status="bounced")).last()
            url = (i and i.handler_url) or "index"
        else:
            url = "profile"

        if not request.user.is_approved and not profile.account_approval_message_sent_at:
            site = Site.objects.get_current()
            profile.account_approval_message_sent_at = timezone.now()
            profile.save(update_fields=["account_approval_message_sent_at"])
            contact_email = models.site_contact_email(site.id)
            if site.domain == "portal.pmscienceprizes.org.nz":
                send_mail(
                    recipient_list=[request.user.full_email_address],
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

    protection_patterns = profile.protection_patterns
    return render(request, "profile_protection_patterns.html", locals())


class ProfileDetail(ProfileView, LoginRequiredMixin, _DetailView):
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
            if u.is_staff or u.is_superuser or p.user == u:
                return p
            raise PermissionDenied(_("You are not allowed to see this profile."))
        return self.request.user.profile


class ProfileUpdate(ProfileView, LoginRequiredMixin, UpdateView):
    def get_object(self):
        return self.request.user.profile


class ProfileCreate(ProfileView, CreateView):
    def form_valid(self, form):
        form.instance.user = self.request.user
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        data = super().get_context_data(**kwargs)

        if "user_form" not in kwargs:
            kwargs["user_form"] = self.get_user_form()

        return data

    def get_initial(self):
        initial = super().get_initial()
        u = self.request.user
        n = (
            models.Nomination.where(user=self.request.user, status="submitted")
            .order_by("-id")
            .first()
        )
        if n:
            initial["first_name"] = n.first_name or u.first_name
            initial["middle_names"] = n.middle_names or u.middle_names
            initial["last_name"] = n.last_name or u.last_name
            initial["title"] = n.title or u.title
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


def invite_team_members(request, application):
    """Send invitations to all team members to authorized_at the representative."""
    # members that don't have invitations
    count = 0
    members = list(
        models.Member.where(
            ~Q(invitation__email=F("email")) | Q(status="sent") | Q(status__isnull=True),
            application=application,
        )
    )
    for m in members:
        get_or_create_team_member_invitation(m)

    # send 'yet unsent' invitations:
    invitations = list(
        models.Invitation.where(application=application, type="T", sent_at__isnull=True)
    )
    for i in invitations:
        i.send(request)
        i.save()
        count += 1
    return count


def invite_referee(request, application=None, by=None, referees=None):
    """Send invitations to all referee."""
    # members that don't have invitations
    count = 0
    # referees = list(models.Referee.where(application=application, invitation__isnull=True))
    # referees = list(models.Referee.where(invitation__isnull=True))
    # referees = list(models.Referee.where(~Q(invitation__email=F("email"))))
    if not referees:
        referees = list(
            models.Referee.where(
                ~Q(status__in=["testified", "accepted", "opted_out"]),
                ~Q(invitation__email=F("email")),
                application=application,
            ).prefetch_related("application", "application__submitted_by")
        )

    for r in referees:
        get_or_create_referee_invitation(
            r, by=r.application.submitted_by or by or request and request.user
        )

    # send 'yet unsent' invitations:
    invitations = list(
        (
            models.Invitation.where(
                Q(sent_at__isnull=True),
                ~Q(status__in=["accepted", "expired", "bounced", "revoked"]),
                application=application,
                type="R",
            )
            if application
            else models.Invitation.where(
                ~Q(status__in=["accepted", "expired", "bounced", "revoked"]),
                referee__in=Subquery(referees.values("id")),
            )
        ).prefetch_related("referee", "referee__user")
    )
    for i in invitations:
        i.send(request, by=by or request and request.user)
        i.save()
        if i.referee:
            i.referee.send()
            i.referee.save()
        count += 1

    return count


def get_or_create_team_member_invitation(member):
    u = member.user or models.User.objects.filter(email=member.email).first()
    if not u and (ea := EmailAddress.objects.filter(email=member.email).first()):
        u = ea.user
    first_name = member.first_name or u and u.first_name or ""
    last_name = member.last_name or u and u.last_name or ""
    middle_names = member.middle_names or u and u.middle_names or ""
    site = (member.application and member.application.site) or Site.objects.get_current()

    if hasattr(member, "invitation"):
        i = member.invitation
        if member.email != i.email:
            i.email = member.email
            i.first_name = first_name
            i.middle_names = middle_names
            i.last_name = last_name
            i.sent_at = None
            i.site = site
            i.submit()
            i.save()
        return (i, False)
    else:
        return models.Invitation.get_or_create(
            type=models.INVITATION_TYPES.T,
            member=member,
            email=member.email,
            defaults=dict(
                application=member.application,
                first_name=first_name,
                middle_names=middle_names,
                last_name=last_name,
                site=site,
            ),
        )


def get_or_create_referee_invitation(referee, by=None):
    u = referee.user or models.User.objects.filter(email=referee.email).first()
    if not u and (ea := EmailAddress.objects.filter(email=referee.email).first()):
        u = ea.user
    if not referee.user and u:
        referee.user = u
        if not referee.first_name:
            referee.first_name = u and u.first_name or ""
        if not referee.last_name:
            referee.last_name = u and u.last_name or ""
        if not referee.middle_names:
            referee.middle_names = u and u.middle_names or ""
        referee.save(update_fields=["user", "first_name", "middle_names", "last_name"])
    first_name = referee.first_name or u and u.first_name or ""
    last_name = referee.last_name or u and u.last_name or ""
    middle_names = referee.middle_names or u and u.middle_names or ""
    site = (referee.application and referee.application.site) or Site.objects.get_current()

    if (
        settings.SITE_ID == 4
        and referee.application.round.survey_id
        and not (referee.survey_token_id or referee.survey_token)
    ):
        referee.add_to_survey()

    if hasattr(referee, "invitation"):
        i = referee.invitation
        if referee.email != i.email:
            i.revoke(by=by)
            i.save()
        else:
            referee.satus = None
            return (i, False)

    i, created = models.Invitation.get_or_create(
        type=models.INVITATION_TYPES.R,
        referee=referee,
        email=referee.email,
        defaults=dict(
            inviter=by,
            application=referee.application,
            first_name=first_name,
            middle_names=middle_names,
            last_name=last_name,
            site=site,
        ),
    )
    referee.invitation = i
    referee.save()
    return (i, created)


def invite_panellist(request, round):
    """Send invitations to all panellists."""
    count = 0
    panellist = list(
        models.Panellist.where(~Q(invitation__email=F("email")) | Q(status__isnull=True))
    )
    for p in panellist:
        p.get_or_create_invitation(by=request and request.user)

    invitations = list(
        models.Invitation.where(
            ~Q(status="accepted"),
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
    # exclude = ["organisation", "status", "submitted_at", "accepted_at", "expired_at"]
    fields = ["email", "first_name", "middle_names", "last_name", "org"]
    widgets = {"org": autocomplete.ModelSelect2("org-autocomplete")}
    labels = {"org": _("organisation")}

    def form_valid(self, form):
        form.instance.user = self.request.user
        if form.instance.org:
            form.instance.organisation = form.instance.org.name

        self.object = form.save()
        self.object.send(self.request)
        self.object.save()

        messages.success(self.request, _("An invitation was sent to ") + form.instance.email)
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


class AuthorizationForm(Form):
    # authorize_team_lead = BooleanField(label=_("I authorize the team leader."), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_group_wrapper_class = "row"
        self.helper.include_media = False
        # self.helper.label_class = "offset-md-1 col-md-1"
        # self.helper.field_class = "col-md-8"
        self.helper.add_input(Submit("submit", _("I agree to be part of this team")))
        self.helper.add_input(
            Submit("turn_down", _("I decline the invitation"), css_class="btn-outline-danger")
        )
        # Submit("load_from_orcid", "Import from ORCiD", css_class="btn-orcid",)

    # def clean_is_accepted(self):
    #     """Allow only 'True'"""
    #     if not self.cleaned_data["is_accepted"]:
    #         raise forms.ValidationError("Please read and consent to the Privacy Policy")
    #     return True


class ApplicationDetail(DetailView):
    model = Application
    template_name = "application_detail.html"

    def dispatch(self, request, *args, **kwargs):
        u = self.request.user
        if u.is_authenticated and not (u.is_superuser or u.is_staff):
            a = self.get_object()
            if not a.user_can_view(u):
                messages.error(request, _("You do not have permissions to view this application."))
                return redirect(self.request.META.get("HTTP_REFERER", "index"))
        return super().dispatch(request, *args, **kwargs)

    def get_member(self):
        """Returns the member entry related to the current user"""
        user = self.request.user
        return self.object.members.filter(
            Q(user=user) | Q(email=user.email) | Q(email__in=user.emailaddress_set.values("email"))
        ).last()

    def get(self, request, *args, **kwargs):
        resp = super().get(request, *args, **kwargs)

        if (a := self.object) and (r := a.round) and r.survey_id:
            u = self.request.user
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
        self.object = self.get_object()
        if member := self.get_member():
            if not member.user:
                member.user = self.request.user

            if "submit" in request.POST:
                member.authorize(request)
                member.save()
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
                    _("The application was cancelled. The applcant(s) were notified."),
                )
            elif action == "request_resubmission":
                self.object.request_resubmission(request)
                self.object.save()
                messages.info(
                    self.request,
                    _(
                        "The request to review and resubmit the application was sent to the applcant(s)."
                    ),
                )
            elif action == "approve":
                self.object.approve(request)
                self.object.save()
                messages.info(
                    self.request,
                    _(
                        "The application was approved. The applcant(s) and adminstrator(s) were notified."
                    ),
                )

        return redirect(request.path)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        a = self.object
        u = self.request.user
        if n := models.Nomination.where(application=a).last():
            context["nomination"] = n
            context["nominator"] = n.nominator
        if a.members.filter(
            Q(user=u) | Q(email=u.email) | Q(email__in=u.emailaddress_set.values("email")),
            # has_authorized__isnull=True,
            Q(status__isnull=True) | ~Q(status__in=["authorized", "opted_out"]),
        ).exists():
            messages.info(
                self.request,
                _("Please review the application and authorize your team representative."),
            )
            context["form"] = AuthorizationForm()
        is_owner = (
            a.submitted_by == u
            or a.members.filter(user=u, status="authorized").exists()
            or (a.site_id == 4 and a.org.where(research_offices__user=u).exists())
        )
        if p := a.round.panellists.filter(user=u).first():
            context["is_panellist"] = True
            coi = p.conflict_of_interests.filter(Q(application=a)).last()
            context["has_coi"] = not coi or coi.has_conflict is True or coi.has_conflict is None
            context["evaluation"] = models.Evaluation.where(panellist=p, application=a).last()

        context["is_owner"] = is_owner
        if (
            is_owner
            and not a.round.is_open
            and (current_round := a.round.scheme.current_round)
            and current_round != a.round
            and current_round.is_open
            and not Application.user_applications(user=u, round=current_round).exists()
        ):
            context["can_reenter"] = True
            context["current_round"] = current_round

        context["was_submitted"] = a.state in ["submitted", "approved", "cancelled"]
        if not is_owner:
            context["show_basic_details"] = not (
                u.is_staff
                or u.is_superuser
                or (settings.SITE_ID != 4 and a.referees.filter(user=u).exists())
                or models.ConflictOfInterest.where(
                    Q(has_conflict=False) | Q(has_conflict__isnull=False),
                    application=a,
                    panellist__user=u,
                ).exists()
                or a.org.where(research_offices__user=u).exists()
            )
            if (
                t := models.Testimonial.where(referee__user=u, referee__application=a)
                .order_by("-id")
                .first()
            ):
                context["testimonial"] = t
            if referee := a.referees.filter(
                Q(user=u) | Q(email__in=u.emailaddress_set.values("email"))
            ).last():
                context["referee"] = referee

        return context


class ApplicationView(LoginRequiredMixin):
    model = Application
    template_name = "application.html"
    form_class = forms.ApplicationForm

    # def form_invalid(self, form):
    #     breakpoint()
    #     return super().form_invalid(form)

    @property
    def previous_application(self):
        user = self.request.user
        if "previous" in self.request.GET:
            pa = models.Application.where(id=int(self.request.GET.get("previous"))).first()
            if pa and (pa.submitted_by == user or user in pa.members.all()):
                return pa
            raise PermissionDenied(
                _("You do not have permission to access the source application.")
            )

    @property
    def latest_application(self):
        return (
            self.previous_application
            or models.Application.where(submitted_by=self.request.user).order_by("-id").first()
        )

    def dispatch(self, request, *args, **kwargs):
        u = request.user
        if u.is_authenticated and not (u.is_staff or u.is_superuser):
            if (pk := self.kwargs.get("pk")) and (
                a := get_object_or_404(models.Application, pk=pk)
            ):
                r = a.round
                if not (
                    a.is_applicant(u)
                    or (a.site_id == 4 and a.org.where(research_offices__user=u).exists())
                ):
                    messages.error(
                        request, _("You do not have permissions to edit this application.")
                    )
                    return redirect("application", pk=pk)

                if a.members.filter(
                    ~Q(status="authorized"),
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

                if a.state and a.state not in ["new", "draft"]:
                    messages.error(
                        request,
                        _(
                            "The application has been already submitted. "
                            "You cannot modify a submitted application."
                        ),
                    )
                    return redirect("application", pk=pk)
                if not r.is_open:
                    messages.error(
                        request,
                        _(
                            "The application period has closed. "
                            "You cannot longer modify this application."
                        ),
                    )
                    return redirect("application", pk=pk)
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
        initial["round"] = self.round.id
        round = self.round

        if (
            round.letter_of_support_required
            and self.object
            and self.object.letter_of_support
            and self.object.letter_of_support.file
        ):
            initial["letter_of_support_file"] = self.object.letter_of_support.file

        if (
            round.applicant_cv_required
            and round.curriculum_vitae_templates.count() > 0
            and self.object
            and self.object.id
            and self.object.cv
            and self.object.cv.file
        ):
            initial["cv_file"] = self.object.cv.file

        initial["round"] = round.id
        if not (self.object and self.object.id):
            initial["user"] = user
            initial["email"] = user.email
            initial["language"] = django.utils.translation.get_language()
            current_affiliation = (
                models.Affiliation.where(profile=user.profile, end_date__isnull=True)
                .order_by("-start_date")
                .first()
            )
            latest_application = self.latest_application
            if round.research_experience_in_years_required:
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
                        profile__user=user,
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
                    pcs := ProfileCareerStage.where(
                        ~Q(career_stage__code="R9"),
                        profile__user=user,
                        year_achieved__isnull=False,
                    )
                    .order_by("year_achieved")
                    .first()
                ):
                    research_experience_in_years = timezone.now().year - pcs.year_achieved

                if research_experience_in_years:
                    initial["research_experience_in_years"] = research_experience_in_years

            if current_affiliation:
                initial["org"] = current_affiliation.org
                initial["position"] = (
                    current_affiliation.role or latest_application and latest_application.position
                )
            elif latest_application:
                initial["org"] = latest_application.org
                initial["position"] = latest_application.position

            if latest_application:
                initial["postal_address"] = latest_application.postal_address
                initial["city"] = latest_application.city
                initial["postcode"] = latest_application.postcode
                initial["daytime_phone"] = latest_application.daytime_phone
                initial["mobile_phone"] = latest_application.mobile_phone

                initial["is_bilingual"] = latest_application.is_bilingual
                initial["summary_en"] = latest_application.summary_en
                initial["summary_mi"] = latest_application.summary_mi
                initial["summary"] = latest_application.summary
                if latest_application.file:
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

        return initial

    @property
    def round(self):
        if "nomination" in self.kwargs:
            return self.nomination.round
        return (
            models.Round.get(self.kwargs["round"]) if "round" in self.kwargs else self.object.round
        )

    @property
    def nomination(self):
        if "nomination" in self.kwargs:
            return models.Nomination.get(self.kwargs["nomination"])

    def form_valid(self, form):
        instance = form.instance
        # if not instance.pk:
        #     resp = super().form_valid(form)

        context = self.get_context_data()
        referees = context["referees"]
        user = self.request.user
        reset_cache(self.request)
        url = self.request.path_info
        round = self.round
        has_required_documents = round.required_documents.count() > 0
        site_id = settings.SITE_ID

        try:
            with transaction.atomic():
                instance = form.instance
                if not instance.organisation and instance.org:
                    instance.organisation = instance.org.name
                if not instance.email:
                    instance.email = user.email

                if round.letter_of_support_required and (
                    letter_of_support_file := self.request.FILES.get("letter_of_support_file")
                ):
                    letter_of_support = models.LetterOfSupport.create(file=letter_of_support_file)
                    instance.letter_of_support = letter_of_support
                    # if letter_of_support_file.name.endswith(".pdf")

                if round.applicant_cv_required and (cv_file := self.request.FILES.get("cv_file")):
                    cv = models.CurriculumVitae.create(
                        file=cv_file, owner=user, profile=user.profile
                    )
                    instance.cv = cv
                    # if letter_of_support_file.name.endswith(".pdf")

                if (
                    "file" in form.changed_data
                    and instance.id
                    and instance.file
                    and instance.converted_file
                ):
                    instance.converted_file.delete()
                    instance.converted_file = None

                if (
                    "cv_file" in form.changed_data
                    and instance.id
                    and instance.cv
                    and instance.cv.file
                    and instance.cv.converted_file
                ):
                    instance.converted_file.delete()
                    instance.converted_file = None

                resp = super().form_valid(form)

                has_deleted = False
                a = self.object

                if a.is_team_application:
                    members = context["members"]
                    has_deleted = bool(members.deleted_forms)
                    if has_deleted:
                        # url = self.request.path_info + "?members=1"
                        # url = self.request.path_info.split("?")[0] + "#application"
                        url = self.continue_url("application")
                    if members.is_valid():
                        members.instance = a
                        members.save()
                        count = invite_team_members(self.request, a)
                        if count > 0:
                            messages.success(
                                self.request,
                                _("%d invitation(s) to join the team have been sent.") % count,
                            )
                    else:
                        for f in members.forms:
                            if not f.is_valid():
                                form.errors.update(f.errors)
                                url = self.continue_url("application")
                                raise ValidationError(_("Invalid member form"))

                    if has_deleted:
                        return redirect(url)

                # if identity_verification_form := context.get("identity_verification"):
                #     identity_verification_form.instance.application = a
                #     if identity_verification_form.is_valid():

                if has_required_documents and (documents := context.get("documents")):
                    if not documents.instance or not documents.instance.id:
                        documents.instance = a
                    if documents.is_valid():
                        documents.save()
                    else:
                        return self.form_invalid(form)

                try:
                    if not referees.instance or not referees.instance.id:
                        referees.instance = a
                    if referees.is_valid():
                        # referees.instance = a
                        has_deleted = bool(has_deleted or referees.deleted_forms)
                        # if has_deleted or "send_invitations" in self.request.POST:
                        #     url = self.continue_url("referees")

                        # for df in referees.deleted_forms:
                        #     if referee := df.instance:
                        #         for i in models.Invitation.where(models.Q(referee=referee)):
                        #             i.revoke(self.request)
                        #             i.save()

                    referees.save()
                    if (
                        a.file
                        or site_id == 4
                        or (
                            has_required_documents
                            and a.documents.filter(~Q(file=""), document_type__role="AF").exists()
                        )
                    ):
                        count = invite_referee(self.request, a)
                        if count > 0:
                            messages.success(
                                self.request,
                                _("%d referee invitation(s) sent.") % count,
                            )
                    elif a.referees.count():
                        messages.info(
                            self.request,
                            _(
                                "The invitation(s) to referee(s) will be sent after "
                                "you upload the application form."
                            ),
                        )

                        if has_deleted:
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
                                raise ValidationError(_("Invalid referee form"))
                except Exception as e:
                    capture_exception(e)
                    messages.error(self.request, str(e))
                    return self.form_invalid(form)

                if "photo_identity" in form.changed_data and instance.photo_identity:
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

                if ethics_statement_form := context.get("ethics_statement"):
                    ethics_statement_form.instance.application = a
                    if ethics_statement_form.is_valid():
                        ethics_statement_form.save()

                if round.has_fors:
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

                        return self.form_invalid(form)

                if round.has_seos:
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
                        return self.form_invalid(form)

                if "file" in form.changed_data and instance.file:
                    try:
                        if cf := instance.update_converted_file():
                            messages.success(
                                self.request,
                                _(
                                    "Your application form was converted into PDF file. "
                                    "Please review the converted application form version <a href='%s'>%s</a>."
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
                    "letter_of_support_file" in form.changed_data
                    and instance.letter_of_support
                    and instance.letter_of_support.file
                    and form.cleaned_data["letter_of_support_file"].content_type
                    != "application/pdf"
                ):
                    try:
                        if (
                            letter_of_support_cf := instance.letter_of_support.update_converted_file()
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
                                "Failed to convert your lettter of support form into PDF. "
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
            return self.form_invalid(form)

        if has_deleted:  # keep editing
            return redirect(url)
        else:
            url = None
            try:
                if "submit" in self.request.POST:
                    if self.round.applicant_cv_required:
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
                                if a and a.id
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

                    if self.round.ethics_statement_required and not (
                        a.ethics_statement
                        or (a.ethics_statement.not_relevant and a.ethics_statement.comment)
                        or a.ethics_statement.file
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

                    if not a.is_tac_accepted:
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

                    if a.round.budget_template and not (
                        a.budget
                        or a.documents.filter(~Q(file=""), document_type__role="B").exists()
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

                    if site_id != 4 and not (
                        a.file
                        or (
                            has_required_documents
                            and models.ApplicationDocument.where(
                                Q(document_type__role="AF")
                                | Q(required_document__document_type__role="AF")
                            ).exists()
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
                        a.round
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

                    if (
                        a.round.required_referees
                        and a.referees.filter(
                            ~Q(status__in=["bounced", "opted_out"])
                            if site_id == 4
                            else Q(status="testified")
                        ).count()
                        < a.round.required_referees
                    ):
                        messages.error(
                            self.request,
                            (
                                _("You need to nominate at least %d referee(s).")
                                if site_id == 4
                                else _(
                                    "You need to procure reviews of your application from at least %d referees."
                                )
                            )
                            % a.round.required_referees,
                        )
                        if not url:
                            url = self.continue_url("referees")

                    if has_required_documents:
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

                    if site_id == 4 and a.round.has_seos and a.application_seos.count() > 3:
                        form.add_error(
                            None,
                            _(
                                "Please enter up to THREE SEO codes from the drop-down "
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

                    if form.errors:
                        return self.form_invalid(form)

                    if url:
                        return redirect(url)

                    a.submit(request=self.request)
                    a.save()
                    messages.info(
                        self.request,
                        _(
                            "Your application has been successfully submitted. "
                            "The Research Office will be in touch if there is anything more needed. Good luck."
                        )
                        if site_id == 4
                        else _(
                            "Your application has been successfully submitted. "
                            "The Prize secretariat will be in touch if there is anything more needed. Good luck."
                        ),
                    )

                elif (
                    self.request.method == "POST"
                    or "save_draft" in self.request.POST
                    or "send_invitations" in self.request.POST
                ):
                    if not a.state or a.state != "new":
                        a.save_draft(request=self.request)
                    a.save()
                    if "send_invitations" in self.request.POST:
                        # url = self.request.path_info.split("?")[0] + "#referees"
                        url = self.continue_url("referees")
                        return redirect(url)
                    else:
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

            except Exception as e:
                capture_exception(e)
                messages.error(self.request, str(e))
                return redirect(self.continue_url())

        return resp

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        round = self.round
        context["round"] = round
        latest_application = self.latest_application
        has_required_documents = round.required_documents.count() > 0

        if round.ethics_statement_required:
            EthicsStatementForm = model_forms.modelform_factory(
                models.EthicsStatement,
                exclude=["application"],
            )
            ethics_statement_form = EthicsStatementForm(
                self.request.POST or None,
                self.request.FILES or None,
                instance=self.object.ethics_statement
                if self.object
                and self.object.id
                and models.EthicsStatement.where(application=self.object).exists()
                else None,
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
            if self.request.POST:
                context["members"] = (
                    forms.MemberFormSet(self.request.POST, instance=self.object)
                    if self.object
                    else forms.MemberFormSet(self.request.POST)
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
                    forms.MemberFormSet(instance=self.object, initial=initial_members)
                    if self.object
                    else forms.MemberFormSet(initial=initial_members)
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
            models.Application,
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
            initial_documents = [
                dict(
                    required_document=rd_id,
                )
                for rd_id, in (
                    round.required_documents.values_list("id")
                    .filter(~Q(id__in=self.object.documents.values("required_document_id")))
                    .order_by("ordering")
                    if (self.object and self.object.id)
                    else round.required_documents.order_by("ordering").values_list("id")
                )
            ]
            fsc = forms.inlineformset_factory(
                models.Application,
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
                        }
                    ),
                },
            )
            if self.request.POST:
                fs = fsc(
                    self.request.POST or None,
                    self.request.FILES or None,
                    instance=self.object,
                    initial=initial_documents,
                )
            else:
                fs = fsc(instance=self.object, initial=initial_documents)
            if initial_documents:
                fs.extra = len(initial_documents)
            context["documents"] = fs
            context["required_documents"] = {
                rd.id: rd for rd in round.required_documents.all().order_by("ordering")
            }

        if round.has_fors:
            fsc = forms.inlineformset_factory(
                models.Application,
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
            if self.request.POST:
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
                models.Application,
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
            fs = fsc(self.request.POST or None, instance=self.object, initial=initial_seos)
            fs.extra = len(initial_seos) or 1
            context["seos"] = fs
        return context

    def get_form_kwargs(self):
        """Return the keyword arguments for instantiating the form."""
        kwargs = super().get_form_kwargs()
        kwargs["initial"]["user"] = self.request.user

        if self.object and self.object.id:
            return kwargs

        if "nomination" in self.kwargs:
            kwargs["initial"]["nomination"] = self.kwargs["nomination"]
            kwargs["initial"]["round"] = self.round.id
        elif "round" in self.kwargs:
            kwargs["initial"]["round"] = self.kwargs["round"]

        if self.request.method == "GET" and "initial" in kwargs:
            user = self.request.user
            kwargs["initial"].update(
                {
                    "application_title": self.round.title,  # models.Round.get(self.kwargs["round"]).title,
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "middle_names": user.middle_names,
                    "title": user.title,
                }
            )
            if "nomination" in self.kwargs and self.nomination and self.nomination.org:
                kwargs["initial"]["org"] = self.nomination.org.id

        return kwargs


class ApplicationUpdate(ApplicationView, UpdateView):
    pass


class ApplicationCreate(ApplicationView, CreateView):
    # class ApplicationCreate(LoginRequiredMixin, CreateWithInlinesView):
    # model = Application
    # # inlines = [MemberInline]
    # template_name = "application.html"
    # form_class = forms.ApplicationForm

    def get(self, request, *args, **kwargs):
        r = (
            models.Round.get(kwargs["round"])
            if "round" in kwargs
            else models.Nomination.get(kwargs["nomination"]).round
        )
        u = request.user
        if r.panellists.all().filter(user=u).exists():
            messages.error(
                self.request,
                _("You are a panellist for this round. You cannot apply for this round: %s")
                % r.title,
            )
            return redirect("home")

        a = models.Application.where(submitted_by=u, round=r).order_by("-id").first()
        if a:
            messages.warning(
                self.request, _("You have already created an application. Please update it.")
            )
            return redirect(reverse("application-update", kwargs=dict(pk=a.id)))

        if nomination_id := request.GET.get("nomination"):
            if n := models.Nomination.where(id=nomination_id).exists():
                if u.email != n.email or not u.emailaddress_set.filter(email=n.email).exists():
                    messages.error(
                        self.request,
                        _(
                            "The nomination was not sent to your address. "
                            "Please contact the portal administrators."
                        ),
                    )
                    return redirect("home")

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
        # Extra layer of protection - to prevent dupliate submssion:
        kwargs = self.kwargs
        r = (
            models.Round.get(kwargs["round"])
            if "round" in kwargs
            else models.Nomination.get(kwargs["nomination"]).round
            if "nomination" in kwargs
            else models.Nomination.get(
                self.request.GET.get("nomination") or self.request.POST.get("nomination")
            ).round
            if "nomination" in self.request.GET or "nomination" in self.request.POST
            else getattr(form.instance, "round")
        )
        if r and (a := models.Application.where(round=r, submitted_by=self.request.user).last()):
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
                resp = super().form_valid(form)
                a.save()
                n = (
                    self.nomination
                    or self.round.user_nominations(self.request.user).order_by("-id").first()
                )
                if n and not n.application:
                    n.application = self.object
                    if n.status != models.NOMINATION_STATUS.accepted:
                        n.accept()
                    n.save(update_fields=["application_id", "status"])
        except Exception as ex:
            capture_exception(ex)
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
#         if request.user.is_authenticated and not Profile.where(user=self.request.user).exists():
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


class RelatedOnlyModelChoiceFilter(django_filters.ModelChoiceFilter):
    # ("round", admin.RelatedOnlyFieldListFilter),
    __queryset = None

    # @property
    # def field(self):
    #     request = self.get_request()
    #     queryset = self.get_queryset(request).filter(**{"id__in": self.parent.qs.values_list(self.field_name)})
    #     self.extra["choices"] = [(o, o) for o in queryset]
    #     return super().field

    def get_queryset(self, request):
        if not self.__queryset:
            self.__queryset = (
                super()
                .get_queryset(request)
                .filter(**{"id__in": self.parent.queryset.values_list(self.field_name)})
            )
        return self.__queryset


def application_filter_rounds(request, *args, **kwargs):
    if request is None:
        return models.Round.objects.none()

    # company = request.user.company
    return models.Round.objects.all()


class YearChoiceFilter(django_filters.ChoiceFilter):
    # field_class = ChoiceField
    field_class = django_filters.fields.ChoiceField

    # def __init__(self, *args, **kwargs):
    #     # self.null_value = kwargs.get("null_value", settings.NULL_CHOICE_VALUE)
    #     with connection.cursor() as cr:
    #         cr.execute("SELECT DISTINCT strftime('%Y', opens_on) AS year FROM round ORDER BY 1;")
    #         kwargs["choices"] = [(y, y) for y in cr.fetchall()]
    #     super().__init__(*args, **kwargs)

    # @property
    # def field(self):
    #     with connection.cursor() as cr:
    #         cr.execute("SELECT DISTINCT strftime('%Y', opens_on) AS year FROM round ORDER BY 1;")
    #         self.extra["choices"] = [(y, y) for (y,) in cr.fetchall()]
    #     return super().field

    def filter(self, qs, value):
        if value != self.null_value and value:
            return qs.filter(created_at__year=value)
        return qs


class ApplicationFilterSet(django_filters.FilterSet):
    # @property
    # def qs(self):
    #     parent = super().qs
    #     author = getattr(self.request, 'user', None)
    #     return parent.filter(is_published=True) | parent.filter(author=author)

    # @property
    # def qs(self):
    #     qs = super().qs
    #     if self.form.data.get('archived_filter') != "true":
    #         qs = qs.filter(round__scheme__current_round=F("round"))
    #     return qs

    application_filter = django_filters.CharFilter(
        method="set_filter", label=gettext_lazy("Application Filter")
    )
    archived_filter = django_filters.BooleanFilter(
        method="filter_archived",
        label=gettext_lazy("Archived Applications"),
    )
    active_filter = django_filters.BooleanFilter(
        method="filter_active", label=gettext_lazy("Active Applications")
    )
    # year_filter = django_filters.ChoiceFilter(  # YearChoiceFilter(
    year_filter = YearChoiceFilter(
        label=gettext_lazy("Year"),
        widget=django_filters.widgets.LinkWidget,
        choices=[(v, v) for v in range(timezone.now().year, 2019, -1)]
        # method="set_filter",
        # queryset=application_filter_years,
    )

    round_filter = RelatedOnlyModelChoiceFilter(  # django_filters.ModelChoiceFilter(
        #     "round",
        label=gettext_lazy("Round"),
        widget=django_filters.widgets.LinkWidget,
        # widget=LinkWidget,
        field_name="round",
        queryset=application_filter_rounds,
    )

    class Meta:
        model = models.Application
        fields = ["application_filter", "archived_filter", "active_filter", "round"]

    def filter_archived(self, queryset, name, value):
        if not value:
            return queryset.filter(round__scheme__current_round=F("round"))
        return queryset

    def filter_active(self, queryset, name, value):
        if value:
            return queryset.filter(round__scheme__current_round=F("round"))
        return queryset

    def set_filter(self, queryset, name, value):
        if value:
            return queryset.filter(
                Q(application_title__icontains=value)
                | Q(number__icontains=value)
                | Q(first_name__icontains=value)
                | Q(last_name__icontains=value)
                | Q(email__icontains=value)
                | Q(submitted_by__first_name__icontains=value)
                | Q(submitted_by__last_name__icontains=value)
                | Q(submitted_by__email__icontains=value)
                | Q(
                    Exists(
                        models.Member.where(
                            first_name__icontains=value, application=OuterRef("pk")
                        )
                    )
                )
                | Q(
                    Exists(
                        models.Member.where(last_name__icontains=value, application=OuterRef("pk"))
                    )
                )
            ).distinct()
        else:
            return queryset


class InvitationList(LoginRequiredMixin, SingleTableView):
    table_class = tables.InvitationTable
    model = models.Invitation
    template_name = "table.html"
    extra_context = {"category": "applications"}

    def get_queryset(self, *args, **kwargs):
        queryset = super().get_queryset(*args, **kwargs)
        u = self.request.user
        if not (u.is_superuser or u.is_staff):
            queryset = queryset.filter(Q(inviter=u) | Q(email__in=u.email_addresses))
        return queryset


class ApplicationListMixin:
    def get_queryset(self, *args, **kwargs):
        u = self.request.user
        # if not (u.is_superuser or u.is_staff):
        #     return models.Application.user_applications(
        #         self.request.user, round=self.request.GET.get("round")
        #     )
        # queryset = super().get_queryset(*args, **kwargs)
        # if "round" in self.request.GET:
        #     queryset = queryset.filter(round=self.request.GET["round"])
        # return queryset
        return models.Application.user_applications(u, round=self.request.GET.get("round"))


class ApplicationList(
    LoginRequiredMixin,
    StateInPathMixin,
    ApplicationListMixin,
    SingleTableView
    # LoginRequiredMixin, StateInPathMixin, ApplicationListMixin, SingleTableMixin, FilterView
):
    model = models.Application
    table_class = tables.ApplicationTable
    extra_context = {"category": "applications"}
    template_name = "table.html"
    # filterset_class = ApplicationFilterSet
    paginator_class = django_tables2.paginators.LazyPaginator

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # u = self.request.user
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

        context["filter_disabled"] = True
        if (state := self.request.path.split("/")[-1]) and state in ["draft", "submitted"]:
            context["state"] = state

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
        if u.is_authenticated and not (u.is_staff or u.is_superuser):
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
    ]

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not Profile.where(user=self.request.user).exists():
            return redirect("onboard")
        return super().dispatch(request, *args, **kwargs)

    def get_defaults(self):
        """Default values for a form."""
        return dict(profile=self.request.user.profile)

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
                "profile": HiddenInput(),
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
        profile = self.request.user.profile
        context["profile"] = profile
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
        if self.request.session.get("wizard"):
            view_idx = self.section_views.index(url_name)
            if view_idx > 0:
                previous_step = self.section_views[view_idx - 1]
                context["previous_step"] = previous_step
            if view_idx < len(self.section_views):
                next_step = self.section_views[view_idx - 1]
                context["next_step"] = next_step
            context["progress"] = ((view_idx + 1) * 100) / (len(self.section_views) + 1)
        context["helper"] = forms.ProfileSectionFormSetHelper(
            profile=profile, previous_step=previous_step, next_step=next_step
        )
        return context

    def get_success_url(self):
        if not self.request.user.profile.is_completed or self.request.session.get("wizard"):
            view_idx = self.section_views.index(self.request.resolver_match.url_name)
            if "previous" in self.request.POST:
                return reverse(self.section_views[view_idx - 1])
            if "next" in self.request.POST and view_idx < len(self.section_views) - 1:
                return reverse(self.section_views[view_idx + 1])
            return reverse("profile-protection-patterns")
        return super().get_success_url()

    def formset_valid(self, formset):
        url_name = self.request.resolver_match.url_name
        profile = self.request.user.profile
        if "complete" in self.request.POST:
            profile.is_employments_completed = True
            profile.is_professional_bodies_completed = True
            profile.is_career_stages_completed = True
            profile.is_external_ids_completed = True
            profile.is_cvs_completed = True
            profile.is_academic_records_completed = True
            profile.is_recognitions_completed = True
            if not self.success_url:
                self.success_url = reverse("home")
        else:
            if url_name == "profile-employments":
                profile.is_employments_completed = True
            elif url_name == "profile-professional-records":
                profile.is_professional_bodies_completed = True
            elif url_name == "profile-career-stages":
                profile.is_career_stages_completed = True
            elif url_name == "profile-external-ids":
                profile.is_external_ids_completed = True
            elif url_name == "profile-cvs":
                profile.is_cvs_completed = True
            elif url_name == "profile-academic-records":
                profile.is_academic_records_completed = True
            elif url_name == "profile-recognitions":
                profile.is_recognitions_completed = True
        profile.save()
        try:
            resp = super().formset_valid(formset)
        except ProtectedError as ex:
            if url_name == "profile-cvs" and hasattr(formset, "deleted_objects"):
                messages.error(
                    self.request,
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
                return redirect(self.request.path_info)

        if hasattr(formset, "deleted_objects"):
            if len(formset.deleted_objects) == 1:
                messages.info(
                    self.request,
                    _("Record deleted: %s") % formset.deleted_objects[0],
                )
            elif len(formset.deleted_objects) > 1:
                messages.info(
                    self.request,
                    _("%d records deleted") % len(formset.deleted_objects),
                )
        elif not profile.is_completed:
            if not profile.is_employments_completed:
                msg = _("You have not completed the affiliation section.")
            elif not profile.is_professional_bodies_completed:
                msg = _("You have not completed the professional body section.")
            elif not profile.is_career_stages_completed:
                msg = _("You have not completed the career stage section.")
            elif not profile.is_external_ids_completed:
                msg = _("You have not completed the external ID section.")
            elif not profile.is_cvs_completed:
                msg = _("You have not completed the CV section.")
            elif not profile.is_academic_records_completed:
                msg = _("You have not completed the academic record section.")
            elif not profile.is_recognitions_completed:
                msg = _("You have not completed the recognition section.")
            messages.info(self.request, "%s %s" % (msg, _("Please complete or skip it.")))

        return resp


class ProfileCareerStageFormSetView(ProfileSectionFormSetView):
    model = ProfileCareerStage
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
        return self.model.where(profile=self.request.user.profile).order_by("year_achieved")


class ProfilePersonIdentifierFormSetView(ProfileSectionFormSetView):
    model = models.ProfilePersonIdentifier
    # formset_class = forms.ProfilePersonIdentifierFormSet
    orcid_sections = ["externalid"]
    form_class = forms.ProfilePersonIdentifierForm

    def get_factory_kwargs(self):
        kwargs = super().get_factory_kwargs()
        kwargs.update(
            {
                "widgets": {
                    "profile": HiddenInput(),
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
        #     "profile": HiddenInput(),
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
        return self.model.where(profile=self.request.user.profile).order_by("code")

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
                    "profile": HiddenInput(),
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
        if not self.request.user.profile.is_employments_completed:
            data = (
                models.Invitation.where(email=self.request.user.email).order_by("-id").first()
                or models.Nomination.where(user=self.request.user).order_by("-id").first()
            )
            if data and data.org:
                models.Affiliation.get_or_create(
                    profile=self.request.user.profile,
                    org=data.org,
                    type=models.AFFILIATION_TYPES.EMP,
                )

        return self.model.where(
            profile=self.request.user.profile, type__in=self.affiliation_type.values()
        ).order_by(
            "start_date",
            "end_date",
        )

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
                    "profile": HiddenInput(),
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


from dal import autocomplete
from taggit.models import Tag


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


class KeywordAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):
    def get_queryset(self):
        # Don't forget to filter out results depending on the visitor !
        if not self.request.user.is_authenticated:
            return models.Keyword.objects.none()
        if not self.q or not self.request.user.is_authenticated:
            return models.Keyword.objects.all()

        return models.Keyword.objects.all().filter(name__istartswith=self.q)

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


class OrgAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):
    def has_add_permission(self, request):
        # Authenticated users can add new records
        return not ("nominator" in self.forwarded and settings.SITE_ID == 4)
        # return True  # request.user.is_authenticated

    def get_queryset(self):
        if (nominator := self.forwarded.get("nominator")) and settings.SITE_ID == 4:
            return models.Organisation.where(Q(research_offices__user_id=nominator))
        elif self.q:
            return models.Organisation.where(name__icontains=self.q).order_by("-id", "name")
        return models.Organisation.objects.order_by("-id", "name")


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
        return self.get_queryset().get_or_create(is_nzqf=False, **{self.create_field: text})[0]


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
    def has_add_permission(self, request):
        # Authenticated users can add new records
        return False  # request.user.is_authenticated

    def get_queryset(self):
        q = models.FieldOfResearch.objects.filter(version="2.0.0")
        if self.q:
            if self.q.isdecimal():
                q = q.filter(code__contains=self.q)
            else:
                q = q.filter(description__icontains=self.q)
            return q.order_by("description")
        return q


class SeoAutocomplete(LoginRequiredMixin, autocomplete.Select2QuerySetView):
    def has_add_permission(self, request):
        # Authenticated users can add new records
        return False  # request.user.is_authenticated

    def get_queryset(self):
        q = models.SocioEconomicObjective.objects.all()
        if self.q:
            if self.q.isdecimal():
                q = q.filter(code__contains=self.q)
            else:
                q = q.filter(description__icontains=self.q)
            return q.order_by("description")
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
                    "profile": HiddenInput(),
                    "owner": HiddenInput(),
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
        resp = super().formset_valid(formset)

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
                            message_text = f"""{message_text}.<br/>
                                    {_('''Now you can complete the submission of your referee report/testimonial.
                                    <br/>Please click on the <strong>Submit</strong> button.''')}"""
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
                    "profile": HiddenInput(),
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
        return self.model.where(profile=self.request.user.profile).order_by("-start_year")

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
#         # fields = ["status", "email", "first_name", "middle_names", "last_name", "role"]
#         exclude = ["award"]
#         widgets = {
#             "profile": HiddenInput(),
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
                    "profile": HiddenInput(),
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
        return self.model.where(profile=self.request.user.profile).order_by("-recognized_in")

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
        return self.request.user.is_superuser or self.request.user.is_staff


class ProfileSummaryView(AdminstaffRequiredMixin, DetailView):
    """Profile summary view"""

    model = models.User
    slug_field = "username"
    slug_url_kwarg = "username"
    template_name = "profile_summary.html"
    user = None

    def get_context_data(self, **kwargs):
        """Get the profile summary of user"""

        context = super().get_context_data(**kwargs)
        user = self.object
        if not (profile := models.Profile.where(user=user).first()):
            messages.warning(
                self.request,
                _(
                    "No Profile summary found or User haven't completed his/her Profile. "
                    "Please come back again!"
                ),
            )

        context["user"] = user
        context["profile"] = profile
        context["image_url"] = user.image_url()

        if profile:
            try:
                context["qualification"] = models.Affiliation.where(
                    profile=profile, type__in=["EMP"]
                ).order_by(
                    "start_date",
                    "end_date",
                )
                context["professional_records"] = models.Affiliation.where(
                    profile=profile, type__in=["MEM", "SER"]
                ).order_by(
                    "start_date",
                    "end_date",
                )
                context["external_id_records"] = models.ProfilePersonIdentifier.where(
                    profile=profile
                ).order_by("code")
                context["academic_records"] = models.AcademicRecord.where(
                    profile=profile
                ).order_by("-start_year")
                context["recognitions"] = models.Recognition.where(profile=profile).order_by(
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
            recipient_list=[u.full_email_address],
            subject=f"Confirmation of {u.email} Signup",
            html_message="<p>You have been approved by schema administrators, "
            f"now start submitting an application to the Portal: {url}</p>",
        )
        messages.success(request, f"You have just approved self signed user {u.email}")
    else:
        messages.info(request, f"Self signed user {u.email} is already approved")

    return redirect("profile-summary", username=u.username)


class NominationView(CreateUpdateView):
    model = models.Nomination
    form_class = forms.NominationForm
    template_name = "nomination.html"

    def dispatch(self, request, *args, **kwargs):
        self.user = u = self.request.user
        if u.is_authenticated and not (u.is_superuser or u.is_staff):
            n = self.get_object()
            if n and n.nominator and n.nominator != u:
                messages.error(
                    request, _("You do not have permissions to access this nomination.")
                )
                return redirect(self.request.META.get("HTTP_REFERER", "index"))
            if n and n.status == "accepted":
                contact_email = models.site_contact_email()
                messages.warning(
                    request,
                    _(
                        "You cannot alter a nomination that has been submitted and accepted.  "
                        f"If you feel a need to do this, please email {contact_email} "
                        "with a reason and we may be able to enable."
                    ),
                )
        return super().dispatch(request, *args, **kwargs)

    @cached_property
    def round(self):
        return (
            models.Round.get(self.kwargs["round"]) if "round" in self.kwargs else self.object.round
        )

    def get_initial(self):
        initial = super().get_initial()
        initial["round"] = self.round.id
        return initial

    def form_valid(self, form):
        n = form.instance

        if not n.id:
            if not n.nominator:
                n.nominator = self.request.user
            if not n.round_id:
                n.round = self.round
            if not n.site:
                n.site = Site.objects.get_current()

        resp = super().form_valid(form)
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

        if "submit" in self.request.POST or self.request.POST.get("action") == "submit":
            if settings.SITE_ID != 4 and not n.file:
                messages.error(
                    self.request,
                    _(
                        "Missing the nomination form. Please attach a nomination form and re-submit"
                    ),
                )
                return resp

            if n.status == "accepted":
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
                    _("An invitation to submit an application has been sent to %s (your nominee).")
                    % invitation.email
                    if created
                    else _(
                        "An invitation to submit an application has been resent to %s (your nominee)."
                    )
                    % invitation.email,
                )
                reset_cache(self.request)
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
            and n.status != "draft"
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
                self.request.user.profile.affiliations.filter(type="EMP", end_date__isnull=True)
                .order_by("-id")
                .first()
            )
            if a:
                kwargs["initial"]["org"] = a.org
            elif ro := models.ResearchOffice.where(user=self.user).order_by("-id").first():
                kwargs["initial"]["org"] = ro.org

        kwargs["initial"]["round"] = self.round
        kwargs["initial"]["round_id"] = self.round.id
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
        return self.request.GET.get("next") or (
            referer if not referer.endswith(self.request.path) else reverse("nominations")
        )


class TestimonialView(CreateUpdateView):
    model = models.Testimonial
    form_class = forms.TestimonialForm
    template_name = "testimonial.html"

    def dispatch(self, request, *args, **kwargs):
        u = self.request.user
        if u.is_authenticated and not (u.is_superuser or u.is_staff):
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
                or a.referees.filter(
                    Q(user=u) | Q(email__in=u.emailaddress_set.values("email"))
                ).last()
            )

    def form_valid(self, form):
        t = form.instance
        u = self.request.user
        reset_cache(self.request)

        if not t.id:
            a = self.application
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

        resp = super().form_valid(form)

        if r := t.referee:
            for i in models.Invitation.where(~Q(status="accepted"), type="R", referee=r):
                i.accept(self.request, by=u)
                i.save(update_fields=["status"])

        if t.state != "submitted":
            if self.request.method == "POST" and "file" in form.changed_data and t.file:
                try:
                    if cf := t.update_converted_file():
                        messages.success(
                            self.request,
                            _(
                                "Your testimonial form was converted into PDF file. "
                                "Please review the converted testimonial form version <a href='%s'>%s</a>."
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

                if not t.file:
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
                    and not a.referees.filter(~Q(status="testified")).exists()
                ):
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
                        recipient_list=recipients,
                        fail_silently=False,
                        request=self.request,
                        reply_to=settings.DEFAULT_FROM_EMAIL,
                    )

                messages.info(
                    self.request,
                    _(
                        "Your referee report has been submitted. The Prize secretariat will be in touch "
                        "if there is anything more needed. Thank you for your participation."
                    ),
                )

            elif "save_draft" in self.request.POST:
                if t.state != "draft":
                    t.save_draft(request=self.request)
                    t.save()
            elif "turn_down" in self.request.POST:
                t.referee.opt_out()
                t.referee.save()
                send_mail(
                    __("A Referee opted out of Testimonial"),
                    __("Your Referee %s has opted out of Testimonial") % t.referee,
                    settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[
                        t.referee.application.submitted_by.email
                        if t.referee.application.submitted_by
                        else t.referee.application.email
                    ],
                    fail_silently=False,
                    request=self.request,
                    reply_to=settings.DEFAULT_FROM_EMAIL,
                )
                messages.info(
                    self.request,
                    _(
                        "You opted out of providing an application "
                        "supporting referee report/testimonial."
                    ),
                )
                reset_cache(self.request)
                return redirect("testimonials")
        else:
            messages.warning(
                self.request,
                _("Testimonial is already submitted."),
            )
        return redirect("testimonial-detail", pk=t.id)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["application"] = self.application
        if not self.referee:
            messages.info(
                self.request,
                _("Please submit your review."),
            )
        return context


class NominationList(LoginRequiredMixin, StateInPathMixin, SingleTableView):
    model = models.Nomination
    table_class = tables.NominationTable
    template_name = "nominations.html"

    def get_queryset(self, *args, **kwargs):
        queryset = super().get_queryset(*args, **kwargs)
        u = self.request.user
        status = self.request.path.split("/")[-1]
        if not (u.is_superuser or u.is_staff):
            # if not status or (status == "submitted" or "submitted" in status):
            queryset = queryset.filter(
                Q(nominator=u)
                | Q(nominator__research_offices__user=u)
                | Q(
                    Q(Q(user=u) | Q(email=u.email)),
                    status="submitted",
                )
            ).distinct()
        queryset = queryset.filter(round__scheme__current_round=F("round"))
        if status == "draft":
            queryset = queryset.filter(status__in=[status, "new"])
        elif status == "submitted":
            queryset = queryset.filter(status=status)
        return queryset


class NominationDetail(DetailView):
    model = models.Nomination
    template_name = "nomination_detail.html"

    def dispatch(self, request, *args, **kwargs):
        u = self.request.user
        if u.is_authenticated and not (u.is_superuser or u.is_staff):
            n = self.get_object()
            if not (
                n.nominator == u
                or n.user == u
                or u.emailaddress_set.filter(email=n.email).exists()
            ):
                messages.error(request, _("You do not have permissions to view this nomination."))
                return redirect(self.request.META.get("HTTP_REFERER", "index"))
        return super().dispatch(request, *args, **kwargs)

    @property
    def can_start_applying(self):
        return self.object.user == self.request.user and not self.object.application

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.can_start_applying:
            nominator = self.object.nominator
            button_label = (
                _("Start Application") if settings.SITE_ID == 4 else _("Start Prize Application")
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

    # def post(self, request, *args, **kwargs):
    #     self.object = self.get_object()
    #     member = self.object.members.filter(
    #         has_authorized__isnull=True, user=self.request.user
    #     ).first()
    #     if "authorize_team_lead" in request.POST:
    #         member.has_authorized = True
    #         member.authorized_at = datetime.now()
    #         member.save()
    #     elif "turn_down" in request.POST:
    #         member.has_authorized = False
    #         member.save()
    #         send_mail(
    #             _("A team member opted out of application"),
    #             _("Your team member %s has opted out of application") % member,
    #             settings.DEFAULT_FROM_EMAIL,
    #             recipient_list=[self.object.submitted_by.email],
    #             fail_silently=False,
    #         )
    #     return self.get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["category"] = "nominations"
        if self.can_start_applying:
            context["start_applying"] = reverse(
                "nomination-application-create", kwargs=dict(nomination=self.object.id)
            )
        #     if self.object.members.filter(
        #         user=self.request.user, has_authorized__isnull=True
        #     ).exists():
        #         messages.info(
        #             self.request,
        #             _("Please review the application and authorize your team representative."),
        #         )
        #         context["form"] = AuthorizationForm()
        return context


class TestimonialList(LoginRequiredMixin, StateInPathMixin, SingleTableView):
    model = models.Testimonial
    table_class = tables.TestimonialTable
    template_name = "testimonials.html"

    def get_queryset(self, *args, **kwargs):
        state = self.state
        return self.model.user_testimonials(user=self.request.user, state=state).order_by(
            "referee__application__number"
        )


class TestimonialDetail(DetailView):
    model = models.Testimonial
    template_name = "testimonial_detail.html"

    def dispatch(self, request, *args, **kwargs):
        u = self.request.user
        if u.is_authenticated and not (u.is_superuser or u.is_staff):
            t = self.get_object()
            if t.referee.user != u:
                messages.error(request, _("You do not have permissions to view this testimonial."))
                return redirect(self.request.META.get("HTTP_REFERER", "index"))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        referee = self.get_object().referee
        a = referee.application
        r = a and referee.application.round

        if a:
            context["extra_object"] = a

        survey_url = (
            r and r.survey_id and reverse("survey-referee", kwargs={"referee_id": referee.id})
        )
        if survey_url:
            context["survey_url"] = survey_url
        if self.get_object().state == "new":
            context["update_view_name"] = f"{self.model.__name__.lower()}-create"
            context["update_button_name"] = _("Add Testimonial")
        else:
            context["update_button_name"] = _("Edit Testimonial")
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
                messages.info(
                    self.request,
                    _("Please review the application details and submit testimonial."),
                )
        return context


class ExportView(LoginRequiredMixin, UserPassesTestMixin, View):
    model = None
    template = "pdf_export_template.html"

    def get_metadata(self, pk):
        return {"/Title": f"{self.model.get(pk)}"}

    def get_objects(self, pk):
        return [self.model.get(id=pk)]

    def get_attachments(self, pk):
        return []

    def get_filename(self, pk):
        return "export"

    def get(self, request, pk):
        try:
            objects = self.get_objects(pk)
            template = get_template(self.template)
            attachments = self.get_attachments(pk)
            merger = PdfFileMerger()
            merger.addMetadata(self.get_metadata(pk))

            html = HTML(string=template.render({"objects": objects}))
            pdf_object = html.write_pdf(presentational_hints=True)
            # converting pdf bytes to stream which is required for pdf merger.
            pdf_stream = io.BytesIO(pdf_object)
            merger.append(pdf_stream)
            for a in attachments:
                if isinstance(a, (tuple, list)):
                    merger.append(a[1], bookmark=a[0], import_bookmarks=True)
                else:
                    merger.append(a, import_bookmarks=True)
            pdf_content = io.BytesIO()
            merger.write(pdf_content)
            pdf_response = HttpResponse(pdf_content.getvalue(), content_type="application/pdf")
            pdf_response["Content-Disposition"] = f"inline; filename={self.get_filename(pk)}.pdf"
            return pdf_response
        except Exception as ex:
            capture_exception(ex)
            messages.warning(
                self.request,
                _(f"Error while converting to pdf. Please contact Administrator: {ex}"),
            )
            return redirect(self.request.META.get("HTTP_REFERER"))


class ApplicationExportView(ExportView):
    """Application PDF export view"""

    model = models.Application
    permission_denied_message = _("Only the round panellist and staff can export the application")

    def test_func(self):
        u = self.request.user
        # staff, superuser, or a panellist of the round
        return (
            u.is_staff
            or u.is_superuser
            or (
                "pk" in self.kwargs
                and (a := get_object_or_404(models.Application, pk=self.kwargs["pk"]))
                and (
                    a.submitted_by == u
                    or a.members.all().filter(user=u).exists()
                    or (settings.SITE_ID != 4 and a.referees.all().filter(user=u).exists())
                    or a.round.panellists.all().filter(user=u).exists()
                    or a.org.where(research_offices__user=u).exists()
                )
            )
        )

    def get_objects(self, pk):
        app = self.model.get(id=pk)
        objects = [app]
        testimonials = app.get_testimonials()
        objects.extend(testimonials)
        return objects

    def get_attachments(self, pk):
        attachments = []
        app = self.model.get(id=pk)
        if app.file:
            attachments.append(settings.PRIVATE_STORAGE_ROOT + "/" + str(app.pdf_file))
        if app.cv and app.cv.file:
            attachments.append(settings.PRIVATE_STORAGE_ROOT + "/" + str(app.cv.pdf_file))

        testimonials = app.get_testimonials()
        for t in testimonials:
            if t.file:
                attachments.append(settings.PRIVATE_STORAGE_ROOT + "/" + str(t.pdf_file))
            if t.cv and t.cv.file:
                attachments.append(settings.PRIVATE_STORAGE_ROOT + "/" + str(t.cv.pdf_file))

        return attachments

    def get_filename(self, pk):
        return self.model.get(id=pk).number

    def get(self, request, pk):
        a = get_object_or_404(models.Application, pk=pk)

        # try:

        pdf_content = io.BytesIO()
        a.to_pdf(request).write(pdf_content)
        # pdf_response = HttpResponse(pdf_content.getvalue(), content_type="application/pdf")
        pdf_content.seek(0)
        pdf_response = FileResponse(pdf_content, content_type="application/pdf")
        # pdf_response["Content-Disposition"] = f"attachment; filename={a.number}.pdf"
        pdf_response["Content-Disposition"] = f"inline; filename={a.number}.pdf"
        return pdf_response

        # except Exception as ex:
        #     messages.warning(
        #         self.request,
        #         _(f"Error while converting to pdf. Please contact Administrator: {ex}"),
        #     )
        #     return redirect(self.request.META.get("HTTP_REFERER"))


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
        return u.is_staff or u.is_superuser or self.round.panellists.all().where(user=u).exists()

    @property
    def filename(self):
        return (self.round.title or self.round.scheme.title).lower().replace(" ", "-")

    def get(self, request, pk):
        round = self.round

        merger = PdfFileMerger()
        merger.addMetadata({"/Title": f"{round.title or self.round.scheme.title}"})
        merger.addMetadata({"/Subject": f"{round.title or self.round.scheme.title}"})

        numbers = []
        for a in self.round.applications.all().order_by("number"):
            numbers.append(a.number)
            content = io.BytesIO()
            a.to_pdf(request).write(content)
            content.seek(0)
            merger.append(
                content,
                bookmark=f"{a.number}: {a.application_title or round.title}",
                import_bookmarks=True,
            )
        merger.addMetadata({"/Keywords": ", ".join(numbers)})

        content = io.BytesIO()
        merger.write(content)
        content.seek(0)

        response = FileResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = f"attachment; filename={self.filename}.pdf"
        return response

        # except Exception as ex:
        #     messages.warning(
        #         self.request,
        #         _(f"Error while converting to pdf. Please contact Administrator: {ex}"),
        #     )
        #     return redirect(self.request.META.get("HTTP_REFERER"))


class TestimonialExportView(ExportView, TestimonialDetail):
    """Testimonial PDF export view"""

    model = models.Testimonial

    def get_metadata(self, pk):
        testimonial = self.model.get(pk)
        metadata = super().get_metadata(pk)
        metadata.update(
            {
                "/Author": testimonial.referee.full_name_with_email,
                "/Subject": testimonial.application.title or testimonial.application.round.title,
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
        return (
            u.is_staff
            or u.is_superuser
            or (
                "pk" in self.kwargs
                and (t := get_object_or_404(models.Testimonial, pk=self.kwargs["pk"]))
                and t.referee.user == u
            )
        )

    def get_attachments(self, pk):
        testimonial = self.model.get(id=pk)
        attachments = []
        if testimonial.file:
            attachments.append(
                (
                    f"{testimonial} {_('Form')}",
                    settings.PRIVATE_STORAGE_ROOT + "/" + str(testimonial.pdf_file),
                )
            )
        if testimonial.cv:
            attachments.append(
                (
                    f"{testimonial.cv} {_('Curriculum Vitae')}",
                    settings.PRIVATE_STORAGE_ROOT + "/" + str(testimonial.cv.pdf_file),
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
        "status_changed_at",
    )

    @property
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
                "status": forms.InvitationStatusInput(),
            }
        )
        kwargs["widgets"] = widgets
        kwargs["can_delete"] = True
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
        if (u := self.request.user) and (u.is_staff or u.is_superuser):
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
        if not (user.is_staff or user.is_superuser):
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
        if (u := self.request.user) and (u.is_staff or u.is_superuser):
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
        if (u := self.request.user) and (u.is_staff or u.is_superuser):
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
        return context

    def get(self, request, *args, **kwargs):
        user = self.request.user
        if r := self.round:
            if not (user.is_staff or user.is_superuser or r.has_online_scoring):
                if not r.all_coi_statements_given_by(request.user):
                    return redirect("round-coi", round=r.id)
                else:
                    return redirect("score-sheet", round=r.id)
            # elif not r.all_coi_statements_given_by(request.user):
            #     return redirect("round-coi", round=r.id)
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
        if not (user.is_staff or user.is_superuser):
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
        return context


class ConflictOfInterestView(CreateUpdateView):
    model = models.ConflictOfInterest
    form_class = forms.ConflictOfInterestForm
    template_name = "conflict_of_interest.html"

    def dispatch(self, request, *args, **kwargs):
        u = self.request.user
        if u.is_authenticated and not (u.is_superuser or u.is_staff):
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
                        "and cannot change the submitted statement of conflict of interst."
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
        if (
            application := models.Application.get(self.kwargs.get("application"))
            if "application" in kwargs
            else self.object.application
        ):
            data["application"] = application
            data["round"] = application.round
            data["coi"] = application.conflict_of_interests.filter(
                panellist__user=self.request.user
            ).last()

        return data


@login_required
def edit_evaluation(request, pk):
    """Redirect either to create or update an evaluation."""
    if e := models.Evaluation.where(application=pk, panellist__user=request.user).first():
        return redirect(reverse("evaluation-update", kwargs=dict(pk=e.id)))
    return redirect(reverse("application-evaluation-create", kwargs=dict(application=pk)))


class CreateEvaluation(LoginRequiredMixin, EvaluationMixin, CreateWithInlinesView):
    def dispatch(self, request, *args, **kwargs):
        u = self.request.user
        if u.is_authenticated and not (u.is_superuser or u.is_staff):
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


class UpdateEvaluation(LoginRequiredMixin, EvaluationMixin, UpdateWithInlinesView):
    def dispatch(self, request, *args, **kwargs):
        u = self.request.user
        if u.is_authenticated and not (u.is_superuser or u.is_staff):
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


class EvaluationDetail(DetailView):
    model = models.Evaluation
    template_name = "evaluation.html"

    def dispatch(self, request, *args, **kwargs):
        if not (u := request.user) and u.is_authenticated and not (u.is_superuser or u.is_staff):
            if (e := self.get_object()) and e.panellist and e.panellist.user != u:
                messages.error(request, _("You do not have permission to access this review."))
                return self.handle_no_permission()
        return super().dispatch(request, *args, **kwargs)

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
    #         member.status = models.MEMBER_STATUS.authorized
    #         # member.authorized_at = datetime.now()
    #         member.save()
    #     elif "turn_down" in request.POST:
    #         member.has_authorized = False
    #         member.status = models.MEMBER_STATUS.opted_out
    #         member.save()
    #         if self.object.submitted_by.email:
    #             send_mail(
    #                 _("A team member opted out of application"),
    #                 _("Your team member %s has opted out of application") % member,
    #                 settings.DEFAULT_FROM_EMAIL,
    #                 recipient_list=[self.object.submitted_by.email],
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
        data = super().get_context_data(*args, **kwargs)
        data["yes_label"] = _("Yes")
        data["no_label"] = _("No")

        round_id = self.kwargs.get("round")
        if round_id and (
            p := models.Panellist.where(user=self.request.user, round_id=round_id).first()
        ):
            if p.has_all_coi_statements_submitted_for(round_id):
                data["is_all_coi_statements_sumitted"] = True

            for row in (
                models.ConflictOfInterest.where(
                    panellist=p,
                    application__round_id=round_id,
                )
                .values("has_conflict")
                .annotate(count=Count("*"))
            ):
                data[f"has_conflict_{row['has_conflict']}"] = row["count"] != 0

        if round_id:
            data["round"] = models.Round.get(round_id)

        return data

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

    filename = str(r).replace(" ", "-").lower() + "-template." + file_type
    response = HttpResponse(book.export(file_type), content_type=content_type)
    response["Content-Disposition"] = f"attachment; filename={filename}"
    return response


class RoundConflictOfInterstSatementList(LoginRequiredMixin, ExportMixin, SingleTableView):
    export_formats = ["xls", "xlsx", "csv", "json", "latex", "ods", "tsv", "yaml"]
    model = models.ConflictOfInterest
    table_class = tables.RoundConflictOfInterestSatementTable
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
    # table_class = tables.RoundConflictOfInterestSatementTable
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
    response["Content-Disposition"] = f"attachment; filename={filename}"
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


def application_exported_view(request, number, lang=None):
    # remote_addr = request.META.get("REMOTE_ADDR")
    # if not remote_addr.startswith("127.0.0."):
    #     return remote_addr
    number = vignere.decode(number)
    application = get_object_or_404(models.Application, number=number)
    round = application.round
    site = Site.objects.get_current()
    domain = site.domain

    logo = None
    if domain == "international.royalsociety.org.nz":
        logo = request.build_absolute_uri(
            f"{settings.STATIC_URL}images/{domain}/alt_logo_small.png"
        )
    objects = application.get_testimonials()

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
    filterset_class = ApplicationFilterSet
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
    response["Content-Disposition"] = 'attachment; filename="{}.pdf"'.format("headers.pdf")
    return response


# vim:set ft=python.django:
