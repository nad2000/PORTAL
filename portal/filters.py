import django
import django_filters
from django.conf import settings
from django.contrib.admin import RelatedFieldListFilter
from django.db.models import Exists, F, Min, OuterRef, Q, Sum, Value
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.functional import lazy
from django.utils.translation import gettext_lazy

from . import models

__first_year = {}


def first_year(site_id=None):
    global __first_year
    if not site_id:
        site_id = settings.SITE_ID
    if not __first_year.get(site_id):
        if data := models.Round.objects.aggregate(Min("opens_on__year"), Min("closes_at__year")):
            __first_year[site_id] = min(v for v in data.values() if v)
    return __first_year[site_id]


def get_request():
    """Walk the stack up to find a request in a context variable."""
    import inspect

    frame = None
    try:
        for f in inspect.stack()[1:]:
            frame = f[0]
            code = frame.f_code
            if code.co_varnames and "context" in code.co_varnames:
                return frame.f_locals["context"]["request"]
    finally:
        del frame


class AutocompleteListFilter(RelatedFieldListFilter):
    """Admin list_filter using autocomplete select 2 widget."""

    template = "admin/filter_autocomplete.html"

    def has_output(self):
        """Show the autocomplete filter at all times."""
        return True

    @staticmethod
    def get_admin_namespace():
        request = get_request()
        return request.resolver_match.namespace

    def get_url(self):
        if django.VERSION > (3, 2):
            return self.get_generic_url()

        remote_model = self.field.related_model
        args = (
            self.get_admin_namespace(),
            remote_model._meta.app_label,
            remote_model._meta.model_name,
        )
        return reverse("%s:%s_%s_autocomplete" % args)

    def get_generic_url(self):
        try:
            return reverse("admin:autocomplete")
        except NoReverseMatch:
            pass

        namespace = self.get_admin_namespace()
        return reverse("%s:autocomplete" % namespace)

    def field_choices(self, field, request, model_admin):
        # Do not populate the field choices with a huge queryset
        return []

    def choices(self, changelist):
        """
        Get choices for the widget.

        Yields a single choice populated with template context variables.

        """
        url = self.get_url()

        placeholder = "PKVAL"
        query_string = changelist.get_query_string(
            {self.lookup_kwarg: placeholder}, [self.lookup_kwarg_isnull]
        )

        lookup_display = None
        if self.lookup_val:
            if django.VERSION >= (5, 0):
                instance = self.field.related_model.objects.get(pk=self.lookup_val[-1])
            else:
                instance = self.field.related_model.objects.get(pk=self.lookup_val)
            lookup_display = str(instance)

        model = self.field.model

        yield {
            "url": url,
            "selected": self.lookup_val,
            "selected_display": lookup_display,
            "query_string": query_string,
            "query_string_placeholder": placeholder,
            "query_string_all": changelist.get_query_string(
                {}, [self.lookup_kwarg, self.lookup_kwarg_isnull]
            ),
            # Data attrs required for Django 3.2+
            "app_label": model._meta.app_label,
            "model_name": model._meta.model_name,
            "field_name": self.field.name,
        }


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
                .filter(**{"pk__in": self.parent.queryset.values_list(self.field_name)})
            )
        return self.__queryset


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


def application_filter_rounds(request=None, *args, **kwargs):
    if request is None:
        return models.Round.objects.none()

    # company = request.user.company
    return models.Round.objects.all()


def filter_all_rounds(request=None, *args, **kwargs):
    if request is None:
        return models.Round.objects.none()

    # company = request.user.company
    return models.Round.all_objects.all()


class FilterSet(django_filters.FilterSet):

    def unaccent(self, **kwargs):
        if settings.ENV == "prod":
            return Q(**{k.replace("name", "name__unaccent"): v for (k, v) in kwargs.items()})
        return Q(**kwargs)

    def __init__(self, data=None, queryset=None, *, request=None, prefix=None):
        super().__init__(data=data, queryset=queryset, request=request, prefix=prefix)
        model = self.queryset.model

        year_now = timezone.now().year
        if (
            start_year := first_year(request and getattr(request, "site_id", None))
        ) and start_year != year_now:
            self.filters["year_filter"] = self.year_filter = YearChoiceFilter(
                label=gettext_lazy("By Year"),
                widget=django_filters.widgets.LinkWidget,
                choices=[(v, v) for v in range(year_now, start_year, -1)],
                # method="set_filter",
                # queryset=application_filter_years,
            )
            self.year_filter.model = model
            self.year_filter.parent = self
            self.year_filter.side_bar = True

        if model is models.Testimonial:
            round_field_name = "referee__application__round"
        elif model is models.Report:
            round_field_name = "contract__application__round"
        elif model is models.Contract:
            round_field_name = "application__round"
        elif model is models.ChangeRequest:
            round_field_name = "contract__application__round"
        else:
            round_field_name = "round"
        rounds = models.Round.all_objects.filter(
            pk__in=self.queryset.values_list(round_field_name)
        )
        if rounds.count() > 1:
            self.filters["round_filter"] = self.round_filter = (
                RelatedOnlyModelChoiceFilter(  # django_filters.ModelChoiceFilter(
                    #     "round",
                    label=gettext_lazy("By Round"),
                    widget=django_filters.widgets.LinkWidget,
                    # widget=LinkWidget,
                    field_name=round_field_name,
                    queryset=(
                        filter_all_rounds
                        if model in [models.Contract, models.Report]
                        else application_filter_rounds
                    ),
                )
            )
            self.round_filter.model = model
            self.round_filter.parent = self
            self.round_filter.side_bar = True

        if model and "fund" in model._meta.fields_map:
            self.filters["fund_filter"] = self.fund_filter = (
                RelatedOnlyModelChoiceFilter(  # django_filters.ModelChoiceFilter(
                    #     "round",
                    label=gettext_lazy("Fund"),
                    widget=django_filters.widgets.LinkWidget,
                    # widget=LinkWidget,
                    field_name="fund",
                    queryset=models.Fund.objects.all(),
                )
            )
            self.fund_filter.model = model
            self.fund_filter.parent = self
            self.fund_filter.side_bar = True

        if model and hasattr(model, "state"):
            self.filters["state_filter"] = self.state_filter = django_filters.ChoiceFilter(
                label=gettext_lazy("By State"),
                field_name="state",
                widget=django_filters.widgets.LinkWidget,
                choices=[
                    (k, gettext_lazy(v))
                    for k, v in model.state.field.choices
                    if k in queryset.distinct().values_list("state", flat=True)
                ],
            )
            self.state_filter.model = model
            self.state_filter.parent = self
            self.state_filter.side_bar = True

        if model:
            if hasattr(model, "org"):
                org_field = "org"
            elif model is models.Report or model is models.ChangeRequest:
                org_field = "contract__org"
            elif model is models.Testimonial:
                org_field = "referee__application__org"
            else:
                org_field = "org"

            self.filters["org_filter"] = self.org_filter = RelatedOnlyModelChoiceFilter(
                label=gettext_lazy("By Source"),
                field_name=org_field,
                widget=django_filters.widgets.LinkWidget,
                queryset=models.Organisation.objects.all(),
            )
            self.org_filter.side_bar = True
            self.org_filter.model = model
            self.org_filter.parent = self


class ApplicationFilterSet(FilterSet):
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
    # # year_filter = django_filters.ChoiceFilter(  # YearChoiceFilter(
    # year_filter = YearChoiceFilter(
    #     label=gettext_lazy("Year"),
    #     widget=django_filters.widgets.LinkWidget,
    #     choices=[(v, v) for v in range(timezone.now().year, 2019, -1)],
    #     # method="set_filter",
    #     # queryset=application_filter_years,
    # )

    # round_filter = RelatedOnlyModelChoiceFilter(  # django_filters.ModelChoiceFilter(
    #     #     "round",
    #     label=gettext_lazy("Round"),
    #     widget=django_filters.widgets.LinkWidget,
    #     # widget=LinkWidget,
    #     field_name="round",
    #     queryset=application_filter_rounds,
    # )

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
            value = value.strip()
            return queryset.filter(
                Q(application_title__icontains=value)
                | Q(number__icontains=value)
                | self.unaccent(first_name__icontains=value)
                | self.unaccent(last_name__icontains=value)
                | Q(email__icontains=value)
                | self.unaccent(submitted_by__first_name__icontains=value)
                | self.unaccent(submitted_by__last_name__icontains=value)
                | Q(submitted_by__email__icontains=value)
                | Q(
                    Exists(
                        models.Member.where(
                            application=OuterRef("pk"),
                            self.unaccent(first_name__icontains=value),
                        )
                    )
                )
                | Q(
                    Exists(
                        models.Member.where(
                            application=OuterRef("pk"),
                            self.unaccent(last_name__icontains=value),
                        )
                    )
                )
            ).distinct()
        else:
            return queryset

    class Meta:
        model = models.Application
        fields = ["application_filter", "archived_filter", "active_filter"]


class TestimonialFilterSet(FilterSet):
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

    testimonial_filter = django_filters.CharFilter(
        method="set_filter",
        label=lazy(
            lambda: (
                "Referee Report Filter"
                if settings.SITE_ID in [2, 4, 5]
                else gettext_lazy("Testimonial Filter")
            )
        )(),
    )
    archived_filter = django_filters.BooleanFilter(
        method="filter_archived",
        label=gettext_lazy("Archived Testimonials"),
    )
    active_filter = django_filters.BooleanFilter(
        method="filter_active", label=gettext_lazy("Active Testimonials")
    )
    # # year_filter = django_filters.ChoiceFilter(  # YearChoiceFilter(
    # year_filter = YearChoiceFilter(
    #     label=gettext_lazy("Year"),
    #     widget=django_filters.widgets.LinkWidget,
    #     choices=[(v, v) for v in range(timezone.now().year, 2019, -1)],
    #     # method="set_filter",
    #     # queryset=application_filter_years,
    # )

    # round_filter = RelatedOnlyModelChoiceFilter(  # django_filters.ModelChoiceFilter(
    #     #     "round",
    #     label=gettext_lazy("Round"),
    #     widget=django_filters.widgets.LinkWidget,
    #     # widget=LinkWidget,
    #     field_name="referee__application__round",
    #     queryset=application_filter_rounds,
    # )

    def filter_archived(self, queryset, name, value):
        if not value:
            return queryset.filter(
                referee__application__round__scheme__current_round=F("referee__application__round")
            )
        return queryset

    def filter_active(self, queryset, name, value):
        if value:
            return queryset.filter(
                referee__application__round__scheme__current_round=F("referee__application__round")
            )
        return queryset

    def set_filter(self, queryset, name, value):
        if value:
            value = value.strip()
            return queryset.filter(
                Q(referee__application__application_title__icontains=value)
                | self.unaccent(referee__first_name__icontains=value)
                | self.unaccent(referee__last_name__icontains=value)
                | Q(referee__email__icontains=value)
                | self.unaccent(referee__user__first_name__icontains=value)
                | self.unaccent(referee__user__last_name__icontains=value)
                | Q(referee__user__email__icontains=value)
                | Q(referee__application__number__icontains=value)
                | self.unaccent(referee__application__first_name__icontains=value)
                | self.unaccent(referee__application__last_name__icontains=value)
                | Q(referee__application__email__icontains=value)
                | self.unaccent(referee__application__submitted_by__first_name__icontains=value)
                | self.unaccent(referee__application__submitted_by__last_name__icontains=value)
                | Q(referee__application__submitted_by__email__icontains=value)
            ).distinct()
        else:
            return queryset

    class Meta:
        model = models.Testimonial
        fields = ["testimonial_filter", "archived_filter", "active_filter"]


class NominationFilterSet(FilterSet):
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

    nomination_filter = django_filters.CharFilter(
        method="set_filter", label=gettext_lazy("Nomination Filter")
    )
    archived_filter = django_filters.BooleanFilter(
        method="filter_archived",
        label=gettext_lazy("Archived Testimonials"),
    )
    active_filter = django_filters.BooleanFilter(
        method="filter_active", label=gettext_lazy("Active Testimonials")
    )
    # year_filter = django_filters.ChoiceFilter(  # YearChoiceFilter(
    # year_filter = YearChoiceFilter(
    #     label=gettext_lazy("Year"),
    #     widget=django_filters.widgets.LinkWidget,
    #     choices=[(v, v) for v in range(timezone.now().year, 2019, -1)],
    #     # method="set_filter",
    #     # queryset=application_filter_years,
    # )

    # round_filter = RelatedOnlyModelChoiceFilter(  # django_filters.ModelChoiceFilter(
    #     #     "round",
    #     label=gettext_lazy("Round"),
    #     widget=django_filters.widgets.LinkWidget,
    #     # widget=LinkWidget,
    #     field_name="round",
    #     queryset=application_filter_rounds,
    # )

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
            value = value.strip()
            return queryset.filter(
                Q(application__application_title__icontains=value)
                | self.unaccent(first_name__icontains=value)
                | self.unaccent(last_name__icontains=value)
                | Q(email__icontains=value)
                | self.unaccent(nominator__first_name__icontains=value)
                | self.unaccent(nominator__last_name__icontains=value)
                | Q(nominator__email__icontains=value)
                | self.unaccent(user__first_name__icontains=value)
                | self.unaccent(user__last_name__icontains=value)
                | Q(user__email__icontains=value)
                | Q(application__number__icontains=value)
                | self.unaccent(application__first_name__icontains=value)
                | self.unaccent(application__last_name__icontains=value)
                | Q(application__email__icontains=value)
                | self.unaccent(application__submitted_by__first_name__icontains=value)
                | self.unaccent(application__submitted_by__last_name__icontains=value)
                | Q(application__submitted_by__email__icontains=value)
            ).distinct()
        else:
            return queryset

    class Meta:
        model = models.Nomination
        fields = ["nomination_filter", "archived_filter", "active_filter"]


class ReportFilterSet(FilterSet):
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

    report_filter = django_filters.CharFilter(
        method="set_filter", label=gettext_lazy("Report Filter")
    )
    archived_filter = django_filters.BooleanFilter(
        method="filter_archived",
        label=gettext_lazy("Archived Reports"),
    )
    active_filter = django_filters.BooleanFilter(
        method="filter_active", label=gettext_lazy("Active Reports")
    )
    # # year_filter = django_filters.ChoiceFilter(  # YearChoiceFilter(
    # year_filter = YearChoiceFilter(
    #     label=gettext_lazy("Year"),
    #     widget=django_filters.widgets.LinkWidget,
    #     choices=[(v, v) for v in range(timezone.now().year, 2019, -1)],
    #     # method="set_filter",
    #     # queryset=application_filter_years,
    # )

    # round_filter = RelatedOnlyModelChoiceFilter(  # django_filters.ModelChoiceFilter(
    #     #     "round",
    #     label=gettext_lazy("Round"),
    #     widget=django_filters.widgets.LinkWidget,
    #     # widget=LinkWidget,
    #     field_name="referee__application__round",
    #     queryset=application_filter_rounds,
    # )

    def filter_archived(self, queryset, name, value):
        if not value:
            return queryset.filter(
                contract__application__round__scheme__current_round=F(
                    "contract__application__round"
                )
            )
        return queryset

    def filter_active(self, queryset, name, value):
        if value:
            return queryset.filter(
                contract__application__round__scheme__current_round=F(
                    "contract__application__round"
                )
            )
        return queryset

    def set_filter(self, queryset, name, value):
        if value:
            value = value.strip()
            return queryset.filter(
                Q(contract__application__application_title__icontains=value)
                | Q(contract__number__icontains=value)
                | Q(contract__project_title__icontains=value)
                # | Q(contract__last_name__icontains=value)
                # | Q(contract__email__icontains=value)
                # | Q(contract__user__first_name__icontains=value)
                # | Q(contract__user__last_name__icontains=value)
                # | Q(contract__user__email__icontains=value)
                # | Q(contract__application__number__icontains=value)
                # | Q(contract__application__first_name__icontains=value)
                # | Q(contract__application__last_name__icontains=value)
                # | Q(contract__application__email__icontains=value)
                # | Q(contract__application__submitted_by__first_name__icontains=value)
                # | Q(contract__application__submitted_by__last_name__icontains=value)
                # | Q(contract__application__submitted_by__email__icontains=value)
            ).distinct()
        else:
            return queryset

    class Meta:
        model = models.Report
        fields = ["report_filter", "archived_filter", "active_filter"]


class ContractFilterSet(FilterSet):

    contract_filter = django_filters.CharFilter(
        method="set_filter", label=gettext_lazy("Contract Filter")
    )
    archived_filter = django_filters.BooleanFilter(
        method="filter_archived",
        label=gettext_lazy("Archived Contracts"),
    )
    active_filter = django_filters.BooleanFilter(
        method="filter_active", label=gettext_lazy("Active Contracts")
    )

    def filter_archived(self, queryset, name, value):
        if not value:
            return queryset.filter(
                application__round__scheme__current_round=F("application__round")
            )
        return queryset

    def filter_active(self, queryset, name, value):
        if value:
            return queryset.filter(
                application__round__scheme__current_round=F("application__round")
            )
        return queryset

    def set_filter(self, queryset, name, value):
        if value:
            value = value.strip()
            return queryset.filter(
                Q(application__application_title__icontains=value)
                | Q(number__icontains=value)
                | Q(application__number__icontains=value)
                | Q(project_title__icontains=value)
                | Q(
                    Q(
                        self.unaccent(members__last_name__icontains=value)
                        | self.unaccent(members__first_name__icontains=value),
                        members__role="PI",
                    )
                    | self.unaccent(submitted_by__last_name__icontains=value)
                    | self.unaccent(submitted_by__first_name__icontains=value)
                )
            ).distinct()
        else:
            return queryset

    class Meta:
        model = models.Contract
        fields = ["contract_filter", "archived_filter", "active_filter"]


class ChangeRequestFilterSet(FilterSet):

    object_filter = django_filters.CharFilter(
        method="set_filter", label=gettext_lazy("Request Filter")
    )
    archived_filter = django_filters.BooleanFilter(
        method="filter_archived",
        label=gettext_lazy("Archived Contracts"),
    )
    active_filter = django_filters.BooleanFilter(
        method="filter_active", label=gettext_lazy("Active Contracts")
    )

    def filter_archived(self, queryset, name, value):
        if not value:
            return queryset.filter(
                contract__application__round__scheme__current_round=F(
                    "contract__application__round"
                )
            )
        return queryset

    def filter_active(self, queryset, name, value):
        if value:
            return queryset.filter(
                contract__application__round__scheme__current_round=F(
                    "contract__application__round"
                )
            )
        return queryset

    def set_filter(self, queryset, name, value):
        if value:
            value = value.strip()
            return queryset.filter(
                Q(contract__application__application_title__icontains=value)
                | Q(contract__number__icontains=value)
                | Q(contract__application__number__icontains=value)
                | Q(contract__project_title__icontains=value)
                | Q(
                    Q(
                        self.unaccent(contract__members__last_name__icontains=value)
                        | self.unaccent(contract__members__first_name__icontains=value),
                        contract__members__role="PI",
                    )
                    | self.unaccent(contract__submitted_by__last_name__icontains=value)
                    | self.unaccent(contract__submitted_by__first_name__icontains=value)
                )
            ).distinct()
        else:
            return queryset

    class Meta:
        model = models.Contract
        fields = ["object_filter", "archived_filter", "active_filter"]


# vim:set ft=python.django:
