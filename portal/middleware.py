import zoneinfo

from django.conf import settings
from django.contrib.flatpages.middleware import FlatpageFallbackMiddleware
from django.contrib.flatpages.views import flatpage
from django.http import Http404
from django.utils import timezone
from django.core.cache import cache


class PortalMiddleware(FlatpageFallbackMiddleware):
    def __call__(self, request):
        tz = (
            # request.session.get("django_timezone") or
            request.COOKIES.get("djanogo_timezone") or settings.TIME_ZONE
        )
        if tz:
            timezone.activate(zoneinfo.ZoneInfo(tz))
        else:
            timezone.deactivate()

        u = request.user
        site_id = request.site_id = int(settings.SITE_ID or 0)
        if u.is_authenticated:
            cache_key = f"{0 if u.is_admin else u.username}:{site_id}"
            cache_control = request.META.get("HTTP_CACHE_CONTROL")
            if cache_control == "max-age=0" or cache_control == "no-cache":
                cache.delete(cache_key)
            request.cache_key = cache_key
        else:
            request.cache_key = None

        response = self.get_response(request)
        # response = super().process_response(request, response)
        if response.status_code == 404:
            # try to add the current language prefix:
            try:
                return flatpage(request, f"/{request.LANGUAGE_CODE or 'en'}{request.path_info}")
            except Http404:
                return response
            except Exception:
                if settings.DEBUG:
                    raise
        return response


# vim:set ft=python.django:
