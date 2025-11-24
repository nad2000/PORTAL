from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.flatpages.views import flatpage
from django.http.response import Http404
from django.urls import include, path
from django.views import defaults as default_views
from django.views.generic import TemplateView
from rest_framework.authtoken.views import obtain_auth_token

from users.views import LoginView, SignupView


def handle_pages(request, *args, url, **kwargs):
    try:
        response = flatpage(request, url=url)
    except Http404:
        return flatpage(request, url=f"{request.LANGUAGE_CODE or 'en'}/{url}")
    # TODO: redirect to a page creation (for admins) if the page is absent...
    return response


urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    # path("", TemplateView.as_view(template_name="pages/home.html"), name="home"),
    # path("grappelli/", include("grappelli.urls")),
    # Django Admin, use {% url 'admin:index' %}
    path(settings.ADMIN_URL, admin.site.urls),
    # User management
    path("users/", include("users.urls", namespace="users")),
    path("accounts/login/", view=LoginView.as_view(), name="account_login"),
    path("accounts/signup/", view=SignupView.as_view(), name="account_signup"),
    path("accounts/", include("allauth.urls")),
    # Your stuff: custom urls includes go here
    path("", include("portal.urls")),
    path("summernote/", include("django_summernote.urls")),
    path("tinymce/", include("tinymce.urls")),
    path("pages/<path:url>", handle_pages, name="flatpage"),
    path("pages/", TemplateView.as_view(template_name="flatpages/list.html"), name="page-list"),
    # re_path("^pages/(?P<url>!((en|mi)/).*)/", handle_pages),
    # path("pages/", include("django.contrib.flatpages.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
# API URLS
urlpatterns += [
    # API base url
    path("api/", include("config.api_router")),
    # DRF auth token
    path("auth-token/", obtain_auth_token),
    path("select2/", include("django_select2.urls")),
    path("explorer/", include("explorer.urls")),
]

if settings.PRIVATE_STORAGE_CLASS != "common.models.ArchivalStorage":
    import private_storage.urls  # avoid pylint warning

    urlpatterns.append(
        path("private-media/", include(private_storage.urls)),
    )  # avoid pylint warning

if settings.DEBUG:
    # This allows the error pages to be debugged during development, just visit
    # these url in browser to see how these error pages look like.
    urlpatterns += [
        path(
            "400/",
            default_views.bad_request,
            kwargs={"exception": Exception("Bad Request!")},
        ),
        path(
            "403/",
            default_views.permission_denied,
            kwargs={"exception": Exception("Permission Denied")},
        ),
        path(
            "404/",
            default_views.page_not_found,
            kwargs={"exception": Exception("Page not Found")},
        ),
        path("500/", default_views.server_error),
    ]
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [path("__debug__/", include(debug_toolbar.urls))] + urlpatterns

handler500 = "portal.views.handler500"
