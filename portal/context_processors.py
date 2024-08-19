from datetime import timedelta

from django.conf import settings
from django.contrib.sites.shortcuts import get_current_site
from django.core.cache import cache
from django.db import connection
from django.db.models import Max, Q, Subquery
from django.utils import timezone
from multisite.models import Alias

from . import models


def portal_context(request):
    view_name = (rm := request.resolver_match) and rm.view_name
    request.site = site = get_current_site(request)
    site_id = settings.SITE_ID
    domain = site.domain
    context = {
        "settings": settings,
        "view_name": view_name,
        "domain": domain,
        "site_name": site.name,
        "SITE_ID": site_id,
        "disable_breadcrumbs": not view_name
        or view_name in ["index", "home"],  # , "account_login", "account_signup"],
    }

    if (u := request.user) and u.is_authenticated:
        filters = request.GET.get("application_filter","")
        cache_key = f"{u.username}:{site_id}:{filters}"
        cache_control = request.META.get("HTTP_CACHE_CONTROL")
        if not (has_refreshed := (cache_control == "max-age=0" or cache_control == "no-cache")):
            cached_context = cache.get(cache_key)
        if has_refreshed or not cached_context or view_name == "start":
            is_ro = models.ResearchOffice.where(user=u).exists()
            is_staff = u.staff_of_sites.filter(id=site_id).exists()
            score_sheet_count = models.ScoreSheet.user_score_sheet_count(u)
            counts = {s: c for s, c in models.Application.user_application_counts(u)}
            # application_draft_count = models.Application.user_application_count(
            #     u, ["draft", "new"]
            # )
            application_draft_count = counts.get("draft", 0) + counts.get("new", 0)
            # application_submitted_count = models.Application.user_application_count(
            #     u,
            #     ["submitted", "cancelled"]
            #     if site_id == 4 and (is_staff or u.is_superuser)
            #     else ["submitted", "approved", "cancelled"],
            # )
            application_submitted_count = counts.get("submitted", 0) + counts.get("canceled", 0)
            application_in_review_count = counts.get("in_review", 0)
            if (
                site_id not in [4, 5] or (not is_staff and not u.is_superuser)
            ) and "approved" in counts:
                application_submitted_count += counts["approved"]
            application_accepted_count = counts.get("accepted", 0)
            # application_accepted_count = models.Application.user_application_count(u, ["accepted"])
            # application_funded_count = models.Application.user_application_count(u, ["funded"])
            application_funded_count = counts.get("funded", 0)
            # outstanding_testimonial_requests = list(models.Referee.outstanding_requests(u))
            application_count = (
                application_draft_count
                + application_submitted_count
                + application_accepted_count
                + application_funded_count
                + application_in_review_count
            )
            cached_context = {
                "is_staff": is_staff,
                "three_days_ago": timezone.now() - timedelta(days=3),
                "application_draft_count": application_draft_count,
                "application_submitted_count": application_submitted_count,
                "application_accepted_count": application_accepted_count,
                "application_funded_count": application_funded_count,
                "nomination_count": models.Nomination.user_nomination_count(u),
                "nomination_draft_count": models.Nomination.user_nomination_count(u, "draft"),
                "nomination_submitted_count": models.Nomination.user_nomination_count(
                    u, "submitted"
                ),
                "nomination_accepted_count": models.Nomination.user_nomination_count(
                    u, "accepted"
                ),
                "testimonial_count": models.Testimonial.user_testimonial_count(u),
                "testimonial_draft_count": models.Testimonial.user_testimonial_count(u, "draft"),
                "testimonial_submitted_count": models.Testimonial.user_testimonial_count(
                    u, "submitted"
                ),
                "review_count": models.Evaluation.user_evaluation_count(u) + score_sheet_count,
                "review_draft_count": models.Evaluation.user_evaluation_count(u, "draft"),
                "review_submitted_count": models.Evaluation.user_evaluation_count(u, "submitted"),
                "score_sheet_count": score_sheet_count,
                "is_ro": is_ro,
            }
            if site_id == 5:
                cached_context["application_in_review_count"] = application_in_review_count
            if site_id in [4, 5] and (is_staff or u.is_superuser):
                application_approved_count = models.Application.user_application_count(
                    u, "approved"
                )
                cached_context["application_approved_count"] = application_approved_count
                application_count += application_approved_count
            cached_context["application_count"] = application_count
            if is_ro or u.is_superuser or u.is_staff or u.is_site_staff:
                cached_context["contract_count"] = models.Contract.objects.count()

            # if outstanding_testimonial_requests:
            #     cached_context["outstanding_testimonial_requests"] = outstanding_testimonial_requests
            if not (u.is_superuser or u.is_staff):
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT
                            EXISTS(SELECT 1 FROM referee WHERE user_id=%s) AS has_testimonials,
                            EXISTS(SELECT 1 FROM panellist WHERE user_id=%s) AS has_reviews,
                            EXISTS(SELECT 1 FROM nomination WHERE nominator_id=%s) AS has_nominations;
                            """,
                        [u.id, u.id, u.id],
                    )
                    row = cursor.fetchone()
                cached_context["has_testimonials"] = row[0]
                cached_context["has_reviews"] = row[1]
                cached_context["has_nominations"] = row[2]
            is_canonical = domain == request.get_host()
            schema = "https" if request.is_secure() else "http"
            port = request.get_port()
            port = "" if port in [80, 433] else f":{port}"
            if request.user.is_superuser:
                cached_context["all_sites"] = [
                    dict(
                        site_id=a.site_id,
                        domain=(
                            a.site.domain.encode().decode("idna")
                            if a.site.domain.startswith("xn--")
                            else a.site.domain
                        ),
                        name=a.site.name,
                        url=f"{schema}://{a.domain}{'' if ':' in a.domain else port}",
                        is_current=a.site_id == site_id,
                    )
                    for a in Alias.objects.filter(
                        (
                            Q(is_canonical=True)
                            if is_canonical
                            else (~Q(is_canonical=True) | Q(is_canonical__isnull=True))
                        ),
                        Q(
                            id__in=Subquery(
                                Alias.objects.filter(
                                    (
                                        Q(is_canonical=True)
                                        if is_canonical
                                        else (~Q(is_canonical=True) | Q(is_canonical__isnull=True))
                                    ),
                                )
                                .values("site_id")
                                .annotate(max_id=Max("id"))
                                .values("max_id")
                            )
                        ),
                    )
                ]
                if site_id in [4, 5] and (u.is_superuser or u.is_site_staff):
                    cached_context["LIMESURVEY_ADMIN_URL"] = (
                        f"{settings.DEBUG and settings.LIMESURVEY_SERVER_URL or '/limesurvey/'}admin/"
                    )
            cache.set(cache_key, cached_context)
        context.update(cached_context)
    return context


# vim:set ft=python.django:
