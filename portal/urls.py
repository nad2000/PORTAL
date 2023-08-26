from django.conf import settings
from django.http import HttpResponse
from django.urls import include, path
from django.views.decorators.cache import cache_page
from django.views.generic import TemplateView
from rest_framework.schemas import get_schema_view

from . import apis, models, views

# app_name = "portal"  ## in case if there is anohter app, add this prefix
urlpatterns = [
    # path('<int:pk>', ProductDetailView.as_view(), name="product-detail"),
    # path("", TemplateView.as_view(template_name="pages/comingsoon.html"), name="comingsoon"),
    path(
        "webmanifest",
        cache_page(None)(
            TemplateView.as_view(
                template_name="pages/webmanifest.html", content_type="application/json"
            )
        ),
        name="webmanifest",
    ),
    path("about", views.about, name="about"),
    path("logout", views.logout, name="logout"),
    path("status", views.status, name="status"),
    path(
        "robots.txt",
        cache_page(None)(
            lambda *args, **kwargs: HttpResponse(
                "User-agent: *\nDisallow: /", content_type="text/plain"
            )
        ),
    ),
    path("subscriptions/", views.SubscriptionList.as_view(), name="subscriptions"),
    path("users/<int:pk>/profile", views.user_profile, name="user-profile"),
    path(
        "applications/",
        include(
            [
                path(
                    "summary",
                    views.SummaryReportList.as_view(),
                    name="summary-report",
                ),
                path(
                    "<int:application>/evaluation/~create",
                    views.CreateEvaluation.as_view(),
                    name="application-evaluation-create",
                ),
                path(
                    "<int:pk>/evaluation/~edit",
                    views.edit_evaluation,
                    name="application-evaluation",
                ),
                path(
                    "<int:round>/~create",
                    views.ApplicationCreate.as_view(),
                    name="application-create",
                ),
                path(
                    "<int:pk>/~update",
                    views.ApplicationUpdate.as_view(),
                    name="application-update",
                ),
                path("<int:pk>", views.ApplicationDetail.as_view(), name="application"),
                path(
                    "<int:application>/review/~create",
                    views.TestimonialView.as_view(),
                    name="application-review-create",
                ),
                path("draft", views.ApplicationList.as_view(), name="applications-draft"),
                path("submitted", views.ApplicationList.as_view(), name="applications-submitted"),
                path("approved", views.ApplicationList.as_view(), name="applications-approved"),
                path("", views.ApplicationList.as_view(), name="applications"),
                path(
                    "<int:pk>/~export",
                    views.ApplicationExportView.as_view(),
                    name="application-export",
                ),
                path(
                    "<number>/exported-view",
                    views.application_exported_view,
                    name="application-exported-view",
                ),
                path("<number>/summary", views.application_summary, name="application-summary"),
            ]
        ),
    ),
    path(
        "evaluation/",
        include(
            [
                path("<int:pk>", views.EvaluationDetail.as_view(), name="evaluation"),
                path(
                    "<int:pk>/~update", views.UpdateEvaluation.as_view(), name="evaluation-update"
                ),
            ]
        ),
    ),
    path("myprofile/", views.user_profile, name="my-profile"),
    path("account/", views.AccountView.as_view(), name="account"),
    path(
        "identity-verification/",
        include(
            [
                path(
                    "<int:pk>/file",
                    views.IdentityVerificationFileView.as_view(),
                    name="identity-verification-file",
                ),
                path(
                    "<int:pk>",
                    views.IdentityVerificationView.as_view(),
                    name="identity-verification",
                ),
            ]
        ),
    ),
    path("profiles/<int:pk>", views.ProfileDetail.as_view(), name="profile-instance"),
    path(
        "survey/",
        include(
            [
                path("webhook/", views.survey_webhook, name="survey-webhook"),
                path("complete/", views.complete_survey, name="survey-complete"),
                path("<int:survey_id>/<token>", views.do_survey, name="survey-do"),
                path("<int:referee_id>", views.do_survey, name="survey-referee"),
            ]
        ),
    ),
    path(
        "profile/",
        include(
            [
                path("~create", views.ProfileCreate.as_view(), name="profile-create"),
                # path("profiles/<int:pk>/~update", views.ProfileUpdate.as_view(), name="profile-update"),
                path("~update", views.ProfileUpdate.as_view(), name="profile-update"),
                path(
                    "career-stages/",
                    views.ProfileCareerStageFormSetView.as_view(),
                    name="profile-career-stages",
                ),
                path(
                    "external-ids/",
                    views.ProfilePersonIdentifierFormSetView.as_view(),
                    name="profile-external-ids",
                ),
                path(
                    "employments/",
                    views.ProfileEmploymentsFormSetView.as_view(),
                    name="profile-employments",
                ),
                path(
                    "educations/",
                    views.ProfileEducationsFormSetView.as_view(),
                    name="profile-educations",
                ),
                path(
                    "academic-records/",
                    views.ProfileAcademicRecordFormSetView.as_view(),
                    name="profile-academic-records",
                ),
                path(
                    "recognitions/",
                    views.ProfileRecognitionFormSetView.as_view(),
                    name="profile-recognitions",
                ),
                path(
                    "protection-patterns/",
                    views.profile_protection_patterns,
                    name="profile-protection-patterns",
                ),
                path(
                    "disable-protection-patterns/",
                    views.disable_profile_protection_patterns,
                    name="disable-profile-protection-patterns",
                ),
                path(
                    "cvs/",
                    views.ProfileCurriculumVitaeFormSetView.as_view(),
                    name="profile-cvs",
                ),
                path("files/", views.user_files, name="profile-files"),
                path("~check", views.check_profile, name="check-profile"),
                path(
                    "professional/",
                    views.ProfileProfessionalFormSetView.as_view(),
                    name="profile-professional-records",
                ),
                path(
                    "summary/<username>",
                    views.ProfileSummaryView.as_view(),
                    name="profile-summary",
                ),
                path("", views.ProfileDetail.as_view(), name="profile"),
            ]
        ),
    ),
    path("start", views.index, name="start"),
    path("", views.index, name="index"),
    # path("index", views.index, name="index"),
    path("home", views.index, name="home"),
    path("index.html", views.index, name="index.html"),
    path("photo_identity", views.photo_identity, name="photo-identity"),
    # path("test_task/<message>", views.test_task),
    path("onboard/<token>", views.check_profile, name="onboard-with-token"),
    path("onboard", views.check_profile, name="onboard"),
    path("approve/<user_id>", view=views.approve_user, name="approve-user"),
    # path("profile/career-stages", views.profile_career_stages, name="profile-career-stages"),
    # path('', ProductListView.as_view(), name="product-list"),
    # path("subscription/create", views.SubscriptionCreate.as_view(), name="subscription-create"),
    path("subscription/<int:pk>", views.SubscriptionDetail.as_view(), name="subscription-detail"),
    path("ui_kit", TemplateView.as_view(template_name="pages/ui_kit.html"), name="ui_kit"),
    path(
        "autocomplete/",
        include(
            [
                path(
                    "keyword/",
                    views.KeywordAutocomplete.as_view(model=models.Keyword, create_field="name"),
                    name="keyword-autocomplete",
                ),
                path(
                    "iwi_group/",
                    views.IwiGroupAutocomplete.as_view(model=models.IwiGroup),
                    name="iwi-group-autocomplete",
                ),
                path(
                    "ethnicity/",
                    views.EthnicityAutocomplete.as_view(model=models.Ethnicity),
                    name="ethnicity-autocomplete",
                ),
                path(
                    "org/",
                    views.OrgAutocomplete.as_view(model=models.Organisation, create_field="name"),
                    name="org-autocomplete",
                ),
                # path(
                #     "ro-org/",
                #     views.OrgAutocomplete.as_view(model=models.Organisation),
                #     name="ro-org-autocomplete",
                # ),
                path(
                    "fos/",
                    views.FosAutocomplete.as_view(model=models.FieldOfStudy),
                    name="fos-autocomplete",
                ),
                path(
                    "for/",
                    views.ForAutocomplete.as_view(model=models.FieldOfResearch),
                    name="for-autocomplete",
                ),
                path(
                    "seo/",
                    views.SeoAutocomplete.as_view(model=models.SocioEconomicObjective),
                    name="seo-autocomplete",
                ),
                path(
                    "award/",
                    views.AwardAutocomplete.as_view(model=models.Award, create_field="name"),
                    name="award-autocomplete",
                ),
                path(
                    "qualification/",
                    views.QualificationAutocomplete.as_view(
                        model=models.Qualification, create_field="description"
                    ),
                    name="qualification-autocomplete",
                ),
                path(
                    "person-identifier/",
                    views.PersonIdentifierAutocomplete.as_view(
                        model=models.PersonIdentifierType, create_field="description"
                    ),
                    name="person-identifier-autocomplete",
                ),
                path(
                    "title/",
                    views.TitleAutocomplete.as_view(model=models.Title, create_field="name"),
                    name="title-autocomplete",
                ),
            ]
        ),
    ),
    path(
        "invitations/",
        include(
            [
                path("~create", views.InvitationCreate.as_view(), name="invitation-create"),
                path("", views.InvitationList.as_view(), name="invitation-list"),
            ]
        ),
    ),
    path("panellist/<int:round>/~invite", views.PanellistView.as_view(), name="panellist-invite"),
    path(
        "round/<int:round>/",
        include(
            [
                path("", views.round_detail, name="round-detail"),
                path("coi", views.RoundConflictOfInterestFormSetView.as_view(), name="round-coi"),
                path(
                    "coi/~list",
                    views.RoundConflictOfInterstSatementList.as_view(),
                    name="round-coi-list",
                ),
                path("scoresheet/~export", views.export_score_sheet, name="export-score-sheet"),
                path("scoresheet", views.score_sheet, name="score-sheet"),
                # path("scores/~list", views.RoundScoreList.as_view(), name="scores-list"),
                path("scores/~list", views.round_scores, name="scores-list"),
                path("scores/~export", views.round_scores_export, name="scores-export"),
                path("summary", views.RoundSummary.as_view(), name="round-summary"),
            ]
        ),
    ),
    path(
        "round/<int:pk>/applications/~export",
        views.RoundExportView.as_view(),
        name="round-application-export",
    ),
    path(
        "nominations/",
        include(
            [
                path(
                    "<int:nomination>/application/~create",
                    views.ApplicationCreate.as_view(),
                    name="nomination-application-create",
                ),
                path(
                    "<int:round>/~create", views.NominationView.as_view(), name="nomination-create"
                ),
                path("<int:pk>/~update", views.NominationView.as_view(), name="nomination-update"),
                path("<int:pk>", views.NominationDetail.as_view(), name="nomination-detail"),
                path("draft", views.NominationList.as_view(), name="nominations-draft"),
                path("submitted", views.NominationList.as_view(), name="nominations-submitted"),
                path("", views.NominationList.as_view(), name="nominations"),
            ]
        ),
    ),
    path(
        "testimonials/",
        include(
            [
                path(
                    "<int:pk>/~create", views.TestimonialView.as_view(), name="testimonial-create"
                ),
                path(
                    "<int:pk>/~update", views.TestimonialView.as_view(), name="testimonial-update"
                ),
                path("<int:pk>", views.TestimonialDetail.as_view(), name="testimonial-detail"),
                path("draft", views.TestimonialList.as_view(), name="testimonials-draft"),
                path("submitted", views.TestimonialList.as_view(), name="testimonials-submitted"),
                path("", views.TestimonialList.as_view(), name="testimonials"),
                path(
                    "<int:pk>/~export",
                    views.TestimonialExportView.as_view(),
                    name="testimonial-export",
                ),
            ]
        ),
    ),
    path(
        "coi/",
        include(
            [
                path(
                    "<int:pk>/~update",
                    views.ConflictOfInterestView.as_view(),
                    name="coi-update",
                ),
                path(
                    "<int:application_id>/~create",
                    views.ConflictOfInterestView.as_view(),
                    name="coi-create",
                ),
            ]
        ),
    ),
    path(
        "reviews/",
        include(
            [
                path("score-sheets", views.ScoreSheetList.as_view(), name="score-sheet-list"),
                path("<int:pk>/~create", views.TestimonialView.as_view(), name="review-create"),
                path("<int:pk>/~update", views.TestimonialView.as_view(), name="review-update"),
                path("<int:pk>", views.TestimonialDetail.as_view(), name="review-detail"),
                path("draft", views.RoundList.as_view(), name="reviews-working"),
                path("submitted", views.RoundList.as_view(), name="reviews-submitted"),
                path("", views.RoundList.as_view(), name="reviews"),
                path(
                    "round/<int:round_id>/~applications",
                    views.RoundApplicationList.as_view(),
                    name="round-application-list",
                ),
                path(
                    "round/<int:round_id>/~applications/<state>",
                    views.RoundApplicationList.as_view(),
                    name="round-application-list-with-state",
                ),
                path(
                    "round/<int:round_id>/applications/<int:application_id>",
                    views.ConflictOfInterestView.as_view(),
                    name="round-application-review",
                ),
                path(
                    "application/<int:pk>",
                    views.EvaluationListView.as_view(),
                    name="round-application-reviews-list",
                ),
                path(
                    "application/<int:pk>/<state>",
                    views.EvaluationListView.as_view(),
                    name="round-application-reviews-list-with-state",
                ),
            ]
        ),
    ),
    # path("", views.subscribe, name="comingsoon"),
    path("root/", views.index, name="root"),
    path("subscribe/", views.subscribe, name="subscription"),
    path("confirm/<token>", views.confirm_subscription, name="subscription-confirmation"),
    path("unsubscribe/<token>", views.unsubscribe, name="unsubscribe"),
    # path(
    #     "subscription/update/<int:pk>",
    #     views.SubscriptionUpdate.as_view(),
    #     name="subscription-update",
    # ),
    # path(
    #     "subscription/delete/<int:pk>",
    #     views.SubscriptionDelete.as_view(),
    #     name="subscription-delete",
    # ),
    # path("subscriptions", views.SubscriptionList.as_view(), name="subscription-list"),
    path(
        "api/",
        include(
            [
                path(
                    "schema",
                    get_schema_view(
                        title="Royal Society Te Apārangi Portals",
                        description="API for all things …",
                        version="1.0.0",
                    ),
                    name="openapi-schema",
                ),
                path("", include(apis.router.urls)),
            ]
        ),
    ),
    path("pyinfo/", views.pyinfo),
    path("pyinfo/<message>", views.pyinfo),
    path("headers/<application_id>/<page_count>/<output_type>", views.headers),
    path("headers/<application_id>/<page_count>", views.headers),
    path("headers/<application_id>/", views.headers),
    path("413/", views.handler413),
    path("favicon.ico", views.favicon),
    path("webhooks/survey/", views.survey_webhook),
]

if settings.SENTRY_DSN:
    from django.contrib.auth.decorators import login_required

    def trigger_error(request, message=None):
        raise Exception(message or request.GET.get("message") or "FAILURE")

    @login_required
    def trigger_error_with_login(request, message=None):
        trigger_error(request, message)

    urlpatterns.extend(
        [
            path("sentry-debug/", trigger_error),
            path("sentry-debug-login/", trigger_error_with_login),
            path("sentry-debug/<message>", trigger_error),
            path("sentry-debug-login/<message>", trigger_error_with_login),
        ]
    )

# vim:set ft=python.django:
