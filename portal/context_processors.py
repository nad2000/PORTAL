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
        cache_key = f"{u.username}:{site_id}"
        cache_control = request.META.get("HTTP_CACHE_CONTROL")
        if not (has_refreshed := (cache_control == "max-age=0" or cache_control == "no-cache")):
            stats = cache.get(cache_key)
        if has_refreshed or not stats or request.resolver_match.view_name == "start":
            is_ro = models.ResearchOffice.where(user=u).exists()
            is_staff = u.staff_of_sites.filter(id=site_id).exists()
            score_sheet_count = models.ScoreSheet.user_score_sheet_count(u)
            application_draft_count = models.Application.user_application_count(
                u, ["draft", "new"]
            )
            application_submitted_count = models.Application.user_application_count(
                u,
                ["submitted", "cancelled"]
                if site_id == 4 and (is_staff or u.is_superuser)
                else ["submitted", "approved", "cancelled"],
            )
            application_accepted_count = models.Application.user_application_count(u, ["accepted"])
            # outstanding_testimonial_requests = list(models.Referee.outstanding_requests(u))
            application_count = application_draft_count + application_submitted_count + application_accepted_count
            stats = {
                "is_staff": is_staff,
                "three_days_ago": timezone.now() - timedelta(days=3),
                "application_draft_count": application_draft_count,
                "application_submitted_count": application_submitted_count,
                "application_accepted_count": application_accepted_count,
                "nomination_count": models.Nomination.user_nomination_count(u),
                "nomination_draft_count": models.Nomination.user_nomination_count(u, "draft"),
                "nomination_submitted_count": models.Nomination.user_nomination_count(
                    u, "submitted"
                ),
                "nomination_accepted_count": models.Nomination.user_nomination_count(u, "accepted"),
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
            if site_id == 4 and (is_staff or u.is_superuser):
                application_approved_count = models.Application.user_application_count(
                    u, "approved"
                )
                stats["application_approved_count"] = application_approved_count
                application_count += application_approved_count
            stats["application_count"] = application_count
            # if outstanding_testimonial_requests:
            #     stats["outstanding_testimonial_requests"] = outstanding_testimonial_requests
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
                stats["has_testimonials"] = row[0]
                stats["has_reviews"] = row[1]
                stats["has_nominations"] = row[2]
            is_canonical = domain == request.get_host()
            schema = "https" if request.is_secure() else "http"
            port = request.get_port()
            port = "" if port in [80, 433] else f":{port}"
            if request.user.is_superuser:
                stats["all_sites"] = [
                    dict(
                        site_id=a.site_id,
                        domain=a.site.domain,
                        url=f"{schema}://{a.domain}{'' if ':' in a.domain else port}",
                        is_current=a.site_id == site_id,
                    )
                    for a in Alias.objects.filter(
                        Q(is_canonical=True)
                        if is_canonical
                        else (~Q(is_canonical=True) | Q(is_canonical__isnull=True)),
                        Q(
                            id__in=Subquery(
                                Alias.objects.filter(
                                    Q(is_canonical=True)
                                    if is_canonical
                                    else (~Q(is_canonical=True) | Q(is_canonical__isnull=True)),
                                )
                                .values("site_id")
                                .annotate(max_id=Max("id"))
                                .values("max_id")
                            )
                        ),
                    )
                ]
            cache.set(cache_key, stats)
        context.update(stats)
    return context


# vim:set ft=python.django:
