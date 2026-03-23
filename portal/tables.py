import django_tables2 as tables
from django.conf import settings
from django.shortcuts import reverse
from django.utils import formats, timezone
from django.utils.html import format_html, mark_safe
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from dateutil.relativedelta import relativedelta

from . import models


class Table(tables.Table):

    @property
    def model_name(self):
        return self._meta.model and self._meta.model._meta.model_name

    @property
    def verbose_model_name(self):
        return self._meta.model and self._meta.model._meta.verbose_name

    class Meta:
        attrs = {"class": "table table-striped table-bordered"}
        # attrs = {"class": "table table-striped"}
        template_name = "django_tables2/bootstrap4.html"


class SafeTemplateColumn(tables.TemplateColumn):
    def render(self, record, table, value, bound_column, **kwargs):
        return mark_safe(super().render(record, table, value, bound_column, **kwargs))


class ReportedFundingTable(Table):
    class Meta:
        model = models.ReportedFunding
        fields = ("title", "doi")


class PublicationTable(Table):
    title = tables.Column(linkify=("publication-update", {"pk": tables.A("pk")}))
    reports = SafeTemplateColumn(
        verbose_name=gettext_lazy("Report(s)"),
        template_name="partials/publication_reports.html",
        attrs={
            "td": {
                "class": "text-center",
            },
        },
    )

    class Meta(Table.Meta):
        model = models.Publication
        fields = ("title", "doi")


class SubscriptionTable(Table):
    class Meta(Table.Meta):
        model = models.Subscription
        fields = (
            "name",
            "email",
        )


class StateColumn(tables.Column):
    attrs = {"td": {"class": "align-middle text-center"}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        kwargs["empty_values"] = [None, ""]

    def render(self, record, table, value, bound_column, **kwargs):
        state = getattr(record, "state", None) or value
        name = (
            table and table.verbose_model_name or record and record._meta.model._meta.verbose_name
        )
        name = gettext_lazy(name and name.lower() or "record")
        if not state:
            return mark_safe(
                '<i class="far fa-question-circle text-dark text-center" aria-hidden="true"></i>'
            )
        elif state in ["new", "draft"]:
            if state == "draft":
                if not isinstance(record, (models.Invitation)):
                    css_classes = "far fa-times-circle text-danger text-center"
                    title = _("Work in progress")
                else:
                    css_classes = "far fa-plus-square text-success text-center"
                    title = _(f"The {name} has not been processed yet or it is in draft version")
            else:
                if not isinstance(record, (models.Invitation)):
                    css_classes = "far fa-times-circle text-danger text-center"
                else:
                    css_classes = "far fa-plus-square text-success text-center"
                title = _(f"The {name} was just created")
        elif state == "in_review":
            css_classes = "fas fa-question text-success text-center"
            title = _(f"The {name} was submitted and sent out to the referees for the reviewing")
        elif state == "withdrawn":
            css_classes = "fa fa-ban text-warning text-center"
            title = _(f"The {name} was withdrawn")
        elif state == "sent":
            css_classes = "far fa-envelope text-success text-center"
            title = _("The invitation was sent")
        elif state == "accepted":
            if isinstance(record, models.Application):
                css_classes = "fas fa-star text-success text-center"
            elif isinstance(record, models.Invitation):
                css_classes = "far fa-envelope-open text-success text-center"
            else:
                css_classes = "fas fa-check-double text-success text-center"
            title = _(f"The {name} was accepted")
        elif state == "testified":
            css_classes = "fa fa-check-circle text-success text-center"
            title = _(f"The {name} was submitted")
        elif state == "opted_out":
            css_classes = "fa fa-ban text-danger text-center"
            title = _(f"The {name} has turned down the nomination")
        elif state == "bounced":
            css_classes = "fa fa-exclamation-triangle text-danger text-center"
            title = _(f"The {name} failed or autoreplied. Please check the recipient")
        elif state == "submitted":
            css_classes = "fa fa-check text-success text-center"
            title = _(f"The {name} was completed and submitted")
        elif state == "cancelled":
            css_classes = "fa fa-ban text-danger text-center"
            title = _(f"The {name} was cancelled")
        elif state == "declined" or state == "excluded":
            css_classes = "fa fa-ban text-danger text-center"
            title = _("Cancelled") if state == "declined" else _("Excluded")
        elif state == "approved":
            css_classes = "fa fa-thumbs-up text-success text-center"
            title = _(f"The {name} was approved")
        elif state == "funded":
            css_classes = "fa fa-heart text-success text-center"
            title = _(f"The {name} was funded")
        elif state == "assessed":
            css_classes = "fa fa-heart text-success text-center"
            title = _(f"The {name} was assessed")
        elif state == "assessed":
            css_classes = "fa fa-heart text-success text-center"
            title = _(f"The {name} was assessed")
        elif state == "assigned":
            css_classes = "fas fa-plus text-success text-center"
            if getattr(record, "assessor", False):
                title = _(f"The {name} was assigned to {record.assessor.full_name_with_email}")
            else:
                title = _(f"The {name} was assigned")
        else:
            if isinstance(record, (models.Testimonial, models.Application)):
                return mark_safe(
                    '<i class="fas fa-plus text-success text-center" aria-hidden="true"></i>'
                )
            css_classes = "fas fa-plus text-success text-center"
            title = _(f"The {name} was created")

        if state_changed_at := getattr(record, "state_changed_at", None):
            # title += f""" {_("(the state updated at <time datetime='%s'>%s</time>)") % (
            #     state_changed_at.isoformat(),
            #     state_changed_at.strftime('%d-%m-%Y %H:%m'))}"""
            title += f""" {_("(the state updated at %s)") % state_changed_at.strftime('%d-%m-%Y %H:%m')}"""

        return mark_safe(
            f'<i class="{css_classes}" aria-hidden="true" data-toggle="tooltip" data-html="true" title="{title}"></i>'
        )


class NominationTable(Table):
    round = tables.Column(
        linkify=lambda table, record: (
            record.get_absolute_url()
            if record.state not in ["submitted", "accepted"]
            else (
                reverse("nomination-detail", args=[record.pk])
                if record.user == table.request.user
                or record.nominator == table.request.user
                or record.email == table.request.user.email
                else None
            )
        )
    )
    state = StateColumn()
    application = tables.Column(
        # accessor="referee__application__number",
        linkify=lambda record: (
            reverse("application", kwargs=dict(pk=record.application_id))
            if record.application
            else None
        ),
    )
    user = tables.Column(verbose_name=_("Nominee"), accessor="full_name_with_email")

    # first_name = tables.Column(verbose_name=_("Nominee First Name"))
    # last_name = tables.Column(verbose_name=_("Nominee Last Name"))
    # email = tables.Column(verbose_name=_("Nominee Email Address"))

    # def render_user(self, record, value):
    #    if value:
    #        return value.full_name_with_email
    #    if value := record.full_name_with_email:
    #        return value
    #    return record.email

    def render_application(self, record, value):
        if value:
            return value.number

    def render_nominator(self, record, value):
        if value:
            return value.full_name_with_email

    def before_render(self, request):
        if (
            (u := request.user)
            and not u.is_superuser
            and not u.is_staff
            and not u.research_offices.exists()
        ):
            self.columns.hide("nominator")

    class Meta(Table.Meta):
        model = models.Nomination
        attrs = {"class": "table table-striped table-bordered"}
        fields = (
            "state",
            "round",
            "user",
            "nominator",
            # "first_name",
            # "last_name",
            # "email",
            "application",
        )


class TestimonialTable(Table):
    state = StateColumn(verbose_name=_("Submitted"))
    number = tables.Column(
        accessor="referee__application__number",
        linkify=lambda record: reverse("testimonial", kwargs=dict(pk=record.id)),
    )
    application_title = tables.Column(accessor="referee__application__application_title")
    referee = tables.Column(
        accessor="referee__full_name_with_email",
        order_by=("referee__first_name", "referee__last_name", "referee__email"),
    )

    class Meta(Table.Meta):
        model = models.Testimonial
        attrs = {"class": "table table-striped table-bordered"}
        fields = ()


def application_link(table, record, value):
    u = table.request.user
    # if u.is_superuser:
    #     return reverse("admin:portal_application_change", kwargs={"object_id": record.id})
    if (
        u.is_superuser
        and record.state in ["draft", "new", "submitted"]
        or record.site_id not in [2, 4, 5]
        and not record.was_submitted
        and record.is_applicant(u)
    ):
        return reverse("application-update", kwargs={"pk": record.id})
    return record.get_absolute_url()


def application_round_link(table, record, value):
    u = table.request.user
    if u.is_staff or u.is_superuser:
        return reverse("admin:portal_round_change", kwargs={"object_id": record.round_id})
    return application_link(table, record, value)


def application_contract_link(table, record, value):
    if value:
        return reverse("contract-detail", kwargs={"number": value.number})
    return f'{reverse("contract-create")}?application_id={record.pk}'


class ContractColumn(tables.LinkColumn):
    pass

    # def text_value(self, record, value):
    #     if record.state == "funded" or record.contract:
    #         return super().text_value(record, value)

    # def value(self, record, value):
    #     if record.state == "funded" or record.contract:
    #         return super().value(record, value)

    def render(self, record, value):
        if record.state == "funded" or record.contract:
            return super().render(record, value)


def default_start_date(record=None):
    if (record and record.site_id or settings.SITE_ID) in [2, 5]:
        return timezone.now().date().replace(day=1, month=3)
    return timezone.now().date().replace(day=1) + relativedelta(months=1)


class ApplicationTable(Table):
    # selection = tables.CheckBoxColumn(accessor="pk")
    state = StateColumn(verbose_name=_("Submitted"))
    number = tables.Column(linkify=application_link)
    round = tables.Column(linkify=application_round_link)
    pi = tables.Column(
        gettext_lazy("Application PI"),
        tables.A("pi__full_name_with_email"),
        order_by=("first_name", "last_name"),
    )
    # email = tables.Column(
    #     linkify=lambda table, record, value: (
    #         reverse("admin:users_user_change", kwargs={"object_id": record.submitted_by_id})
    #         if (table.request.user.is_staff or table.request.user.is_superuser)
    #         and record.submitted_by_id
    #         else None
    #     )
    # )
    export = tables.LinkColumn(
        "application-export",
        args=[tables.A("pk")],
        text=gettext_lazy("Export"),
        orderable=False,
        attrs={
            "a": {
                "class": "btn btn-primary btn-sm",
                "target": "_blank",
                "data-toggle": "tooltip",
                "title": gettext_lazy("Export the application into a consolidated PDF file"),
            },
            "td": {"class": "text-center"},
        },
    )
    admin = tables.LinkColumn(
        "admin:portal_application_change",
        args=[tables.A("pk")],
        text=gettext_lazy("Open"),
        verbose_name="In Admin",
        orderable=False,
        attrs={
            "a": {
                "class": "btn btn-primary btn-sm",
                "target": "_blank",
                "data-toggle": "tooltip",
                "title": "Open the application in the admin",
            },
            "td": {"class": "text-center"},
        },
    )
    current_contract = SafeTemplateColumn(
        verbose_name=gettext_lazy("Contract"),
        template_name="partials/current_contract.html",
        attrs={
            "td": {
                "class": "text-center",
            },
        },
        extra_context={
            "start_date": default_start_date(),
            "relativedelta": relativedelta,
            "today": timezone.now().date(),
        },
    )

    # def render_current_contract(self, value, *args, **kwargs):
    #     return mark_safe(value)

    _current_contract = tables.columns.linkcolumn.BaseLinkColumn(
        visible=False,
        verbose_name=gettext_lazy("Contract"),
        text=lambda record: (
            gettext_lazy("Create")
            if record.state != "funded"
            else gettext_lazy("Open") if record.contract else gettext_lazy("Create")
        ),
        linkify=lambda table, record, value: (
            reverse("application-contract", args=[record.pk])
            if record.contract
            else (
                f'{reverse("contract-create")}?application_id={record.pk}'
                if record.state == "funded"
                else None
            )
        ),
        attrs={
            "a": {
                "class": "btn btn-primary btn-sm",
                "target": "_blank",
            },
            "td": {
                "class": "text-center",
                "data-toggle": "tooltip",
                "title": gettext_lazy("Create or update a contract"),
            },
        },
    )

    def before_render(self, request, *args, **kwargs):
        view_name = (rm := request.resolver_match) and rm.view_name
        state = rm and rm.kwargs.get("state")
        # if state != "submitted" and view_name != "applications-submitted":
        #     self.columns.hide("selection")
        if state != "funded":
            self.columns.hide("current_contract")
        if (u := request.user) and not u.is_admin:
            self.columns.hide("export")
            self.columns.hide("admin")
            self.columns.hide("current_contract")
        if not models.Round.where(
            scheme__current_round=models.F("pk"), can_specify_panel=True
        ).exists():
            self.columns.hide("panel")

    # def render_latest_contract(self, record, value):
    #     if record.state == "funded" or record.state == "archived" and record.contract:
    #         return value

    def render_number(self, record, value):
        if (
            record.state in ["draft", "new"]
            and (deadline_days := record.deadline_days)
            and deadline_days < 6
        ):
            r = record.round
            closes_at = r.closes_at and (
                timezone.localtime(r.closes_at) if timezone.is_aware(r.closes_at) else r.closes_at
            )
            return format_html(
                """<span
                    data-toggle="tooltip"
                    title="{}"
                >
                    <i class="fas fa-exclamation-circle {}"
                    ></i> {}
                </span>""",
                _("The round is closing in %s day(s) on %s by %s")
                % (
                    deadline_days,
                    formats.date_format(closes_at, "d-m-Y"),
                    formats.date_format(closes_at, "P"),
                ),
                "text-danger" if record.deadline_days < 4 else "text-warning",
                value,
            )
        return value

    class Meta(Table.Meta):
        model = models.Application
        attrs = {"class": "table table-striped table-bordered"}
        fields = (
            "state",
            "number",
            "round",
            "pi",
            # "email",
            # "first_name",
            # "last_name",
            "panel",
            "export",
            "admin",
            # "contract",
        )


def report_link(table, record, value):
    u = table.request.user
    if u.is_superuser:
        return reverse("admin:portal_report_change", kwargs={"object_id": record.id})
    if record.site_id not in [2, 4, 5] and not record.was_submitted and record.is_applicant(u):
        return reverse("report-update", kwargs={"pk": record.id})
    return record.get_absolute_url()


def report_contract_link(table, record, value):
    if value:
        return reverse("contract-detail", kwargs={"number": value.number})
    return f'{reverse("contract-create")}?report_id={record.pk}'


class ReportTable(Table):
    state = StateColumn(verbose_name=_("Status"))
    # number = tables.Column(linkify=report_link)
    number = tables.LinkColumn(
        "report",
        args=[tables.A("pk")],
        text=lambda record: f"{record.contract.number}:{record.type}-{record.period}",
        verbose_name=gettext_lazy("Report"),
        order_by=["contract__number", "period", "type"],
    )
    contract = tables.columns.linkcolumn.BaseLinkColumn(
        linkify=lambda record: reverse(
            "contract-detail", kwargs=dict(number=record.contract.number)
        ),
        text=lambda record: record.contract.number,
    )
    export = tables.LinkColumn(
        "report-export",
        args=[tables.A("pk")],
        text=gettext_lazy("Export"),
        orderable=False,
        attrs={
            "a": {
                "class": "btn btn-primary btn-sm",
                "target": "_blank",
                "data-toggle": "tooltip",
                "title": gettext_lazy("Export the report into a consolidated PDF file"),
            },
            "td": {"class": "text-center"},
        },
    )
    pi = tables.Column(
        gettext_lazy("Contract PI"),
        tables.A("pi__full_name_with_email"),
        order_by="contract__members__email",
    )
    due_date = tables.Column(order_by="schedule_entry__due_date")

    # def before_render(self, request):
    #     if (u := request.user) and not u.is_superuser and not u.is_staff:
    #         self.columns.hide("export")
    #         self.columns.hide("contract")

    # def render_latest_contract(self, record, value):
    #     if record.state == "funded" or record.state == "archived" and record.contract:
    #         return value

    # def render_number(self, record, value):
    #     if (
    #         record.state in ["draft", "new"]
    #         and (deadline_days := record.deadline_days)
    #         and record.deadline_days < 6
    #     ):
    #         r = record.round
    #         closes_at = timezone.localtime(r.closes_at)
    #         return format_html(
    #             """<span
    #                 data-toggle="tooltip"
    #                 title="%s"
    #             >
    #                 <i class="fas fa-exclamation-circle %s"
    #                 ></i> %s
    #             </span>"""
    #             % (
    #                 _("The round is closing in %s day(s) on %s by %s")
    #                 % (
    #                     deadline_days,
    #                     formats.date_format(closes_at, "d-m-Y"),
    #                     formats.date_format(closes_at, "P"),
    #                 ),
    #                 "text-danger" if record.deadline_days < 4 else "text-warning",
    #                 value,
    #             )
    #         )
    #     return value

    class Meta(Table.Meta):
        model = models.Report
        attrs = {"class": "table table-striped table-bordered"}
        fields = (
            "state",
            "number",
            "contract",
            "pi",
            # "period",
            "type",
            "due_date",
        )


def round_link(record, table, *args, **kwargs):
    user = table.request.user
    if not (user.is_staff or user.is_superuser) and (
        not record.has_online_scoring
        and not record.all_coi_statements_given_by(table.request.user)
    ):
        return reverse("round-coi", kwargs={"round": record.id})

    if record.has_online_scoring or user.is_staff or user.is_superuser:
        url = reverse("round-application-list", kwargs={"round_id": record.id})
    else:
        url = reverse("score-sheet", kwargs={"round": record.id})

    if state := table.context.get("state"):
        url += f"?state={state}"
    return url


class RoundTable(Table):
    title = tables.Column(linkify=round_link, verbose_name=_("Round"))
    scheme = tables.Column(verbose_name=_("Scheme"))
    opens_on = tables.Column(verbose_name=_("Opens On"))
    closes_at = tables.Column(verbose_name=_("Closes On"))
    evaluation_count = tables.Column(
        verbose_name=_("Review Count"),
        attrs={
            "td": {"style": "text-align: right;"},
            "tf": {"style": "text-align: right; font-weight: bold;"},
        },
        footer=lambda table: sum(row.evaluation_count for row in table.data),
    )

    class Meta(Table.Meta):
        model = models.Round
        attrs = {"class": "table table-striped table-bordered"}
        fields = (
            "title",
            "scheme",
            "opens_on",
            "closes_at",
            "evaluation_count",
        )


class ScoreSheetTable(Table):
    round = tables.Column(
        linkify=lambda record: reverse("score-sheet", kwargs=dict(round=record.round_id))
    )

    class Meta(Table.Meta):
        model = models.ScoreSheet
        attrs = {"class": "table table-striped table-bordered"}
        fields = (
            "round",
            "file",
        )


def application_review_link(table, record, value):
    user = table.request.user
    if user.is_staff or user.is_superuser:
        url = reverse(
            "round-application-reviews-list",
            kwargs={"pk": record.id},
        )
        if state := table.context.get("state"):
            url += f"?state={state}"
        return url

    coi = record.conflict_of_interests.filter(panellist__user=user).last()
    #  coi = record.conflict_of_interests.last()
    if not coi or coi.has_conflict is None:
        return reverse("round-coi", kwargs={"round": record.round_id})
        # return reverse(
        #     "round-application-review",
        #     kwargs={"round_id": record.round.id, "application_id": record.id},
        # )
    elif not coi.has_conflict:
        e = record.evaluations.filter(panellist__user=user).order_by("-id").first()
        if e and e.state in ["new", "draft"]:
            return reverse("evaluation-update", kwargs=dict(pk=e.id))
        elif e:
            return reverse("evaluation", kwargs=dict(pk=e.id))
        elif not e:
            return reverse("application-evaluation-create", kwargs=dict(application=record.id))
    elif coi.has_conflict or record.state != "submitted":
        return


class RoundApplicationTable(Table):
    number = tables.Column(linkify=application_review_link, verbose_name=_("Number"))
    first_name = tables.Column(verbose_name=_("First Name"))
    last_name = tables.Column(verbose_name=_("Last Name"))
    email = tables.Column(verbose_name=_("Email"))
    evaluation_count = tables.Column(
        verbose_name=_("Review Count"),
        attrs={
            "td": {"style": "text-align: right;"},
            "tf": {"style": "text-align: right; font-weight: bold;"},
        },
        footer=lambda table: sum(row.evaluation_count for row in table.data),
    )

    def render_number(self, record, value):
        user = self.request.user
        coi = record.conflict_of_interests.filter(panellist__user=user).last()
        #  coi = record.conflict_of_interests.last()

        if not coi or coi.has_conflict is None:
            return format_html(
                "<span data-toggle='tooltip' title='{}'>{}</span>",
                _("Conflict of Interest statement to complete."),
                value,
            )
        if not coi.has_conflict:
            if record.evaluations.filter(state="submitted", panellist__user=user).exists():
                return format_html(
                    "<span data-toggle='tooltip' title='{}'>{}</span>",
                    _("You have already submitted an evaluation of this application."),
                    value,
                )

            return format_html(
                "<span data-toggle='tooltip' title='{}'>{}</span>",
                _(
                    "You have submitted the statement of the conflict of interest. "
                    "Please evaluate the application and submit scores."
                ),
                value,
            )
        # if coi.has_conflict:
        #     return format_html(
        #         "<span data-toggle='tooltip' title='%s'>%s</span>"
        #         % (
        #             _(
        #                 "You have stated that you have a conflict of interest in respect of this application. "
        #                 "You cannot evaluate this application."
        #             ),
        #             value,
        #         )
        #     )

        if record.state != "submitted":
            return format_html(
                "<span data-toggle='tooltip' title='{}'>{}</span>",
                _("The application has not been submitted yet"),
                value,
            )
        if (r := record.round) and (deadline_days := r.deadline_days) and deadline_days < 6:
            closes_at = timezone.localtime(r.closes_at)
            return format_html(
                """<span
                    data-toggle="tooltip"
                    title="{}"
                >
                    <i class="fas fa-exclamation-circle {}"
                    ></i> {}
                </span>""",
                _("The round is closing in %(days)s day(s) on %(date)s by %(time)s")
                % {
                    "days": deadline_days,
                    "date": formats.date_format(closes_at, "d-m-Y"),
                    "time": formats.date_format(closes_at, "P"),
                },
                "text-danger" if deadline_days < 4 else "text-warning",
                value,
            )
        return value

    class Meta(Table.Meta):
        model = models.Application
        attrs = {"class": "table table-striped table-bordered"}
        fields = (
            "number",
            "first_name",
            "last_name",
            "email",
            "evaluation_count",
        )


class EvaluationTable(Table):
    # round = tables.Column(verbose_name=_("Round"))
    total_score = tables.Column(
        verbose_name=_("Total Score"), attrs={"td": {"style": "text-align: right;"}}
    )
    panellist = tables.Column(
        accessor="panellist__full_name_with_email",
        order_by=("panellist__first_name", "panellist__last_name", "panellist__email"),
    )

    # def render_panellist(self, record, value):
    #     if value:
    #         return value.full_name_with_email

    class Meta(Table.Meta):
        model = models.Evaluation
        attrs = {"class": "table table-striped table-bordered"}
        fields = (
            # "round",
            "panellist",
            "total_score",
        )


class RoundConflictOfInterestStatementTable(Table):
    number = tables.Column(linkify=lambda record: record.application.get_absolute_url())
    has_conflict = tables.Column()
    first_name = tables.Column()
    middle_names = tables.Column()
    last_name = tables.Column()
    email = tables.Column(
        linkify=lambda record: reverse(
            "admin:portal_conflictofinterest_change", kwargs={"object_id": record.id}
        )
    )

    def render_has_conflict(self, value):
        if value is None:
            return _("N/A")
        elif value:
            return _("Yes")
        return _("No")

    class Meta(Table.Meta):
        attrs = {"class": "table table-striped table-bordered"}


class RoundSummaryTable(Table):
    number = tables.Column(linkify=lambda record: record.get_absolute_url())
    lead = tables.Column()
    state = tables.Column(verbose_name=_("State"))
    is_accepted = tables.Column(verbose_name=_("T&C"))
    referees = tables.Column(empty_values=(), verbose_name=_("Referees"), orderable=False)
    members = tables.Column(
        empty_values=(), verbose_name=_("Members (authorized/total)"), orderable=False
    )
    is_identity_verified = tables.Column(verbose_name=_("Identity Verified"))

    def render_state(self, value):
        return _(value)

    def render_referees(self, record):
        return f"{record.submitted_reference_count}/{record.referee_count}"

    def render_members(self, record):
        return f"{record.member_authorized_count}/{record.member_count}"

    def render_is_identity_verified(self, value):
        return _("Yes") if value else _("No")

    def render_is_accepted(self, value):
        return _("Yes") if value else _("No")

    class Meta:
        template_name = "django_tables2/bootstrap4.html"
        attrs = {"class": "table table-striped table-bordered"}
        model = models.Application
        fields = ["number"]


class InvitationTable(Table):
    url = tables.Column(linkify=lambda value: value)
    token = tables.Column(linkify=lambda value, record: record.url)
    # number = tables.Column(linkify=application_link)
    # round = tables.Column(linkify=application_round_link)
    # email = tables.Column(
    #     linkify=lambda table, record, value: reverse(
    #         "admin:users_user_change", kwargs={"object_id": record.submitted_by_id}
    #     )
    #     if (table.request.user.is_staff or table.request.user.is_superuser)
    #     and record.submitted_by_id
    #     else None
    # )

    class Meta:
        model = models.Invitation
        attrs = {"class": "table table-striped table-bordered"}
        fields = [
            "token",
            "url",
            "inviter",
            "type",
            "email",
            "first_name",
            "middle_names",
            "last_name",
            "organisation",
            "org",
            "application",
            "nomination",
            "member",
            "referee",
            "panellist",
            "round",
            "state",
            "submitted_at",
            "sent_at",
            "accepted_at",
            "expired_at",
            "bounced_at",
        ]


class SummaryReportTable(Table):
    class Meta(Table.Meta):
        model = models.Application
        attrs = {"class": "table table-striped table-bordered"}
        fields = ["number", "round", "submitted_by", "state"]


class ContractTable(Table):
    number = tables.Column(
        verbose_name=gettext_lazy("Contract"),
        linkify=lambda value, record: reverse(
            "contract-detail", kwargs=dict(number=record.number)
        ),
    )
    application = tables.Column(
        gettext_lazy("Proposal"),
        tables.A("application__number"),
        linkify=lambda value, record: reverse(
            "application-detail", kwargs=dict(number=record.application.number)
        ),
        order_by="application__number",
    )
    state = StateColumn(gettext_lazy("Status"))
    # contract_pi = tables.Column(linkify=application_link)
    pi = tables.Column(
        gettext_lazy("Contract PI"),
        tables.A("pi_member__full_name_with_email"),
        order_by="members__email",
    )
    notes = StateColumn()

    class Meta(Table.Meta):
        model = models.Contract
        fields = ("state", "number", "application", "pi", "notes")


class ChangeRequestTable(Table):

    state = StateColumn(gettext_lazy("Status"))
    updated_at = tables.Column(
        accessor="updated_at",
        order_by="updated_at",
        verbose_name=gettext_lazy("Change Date"),
        linkify=lambda value, record: reverse("change-request", kwargs=dict(pk=record.pk)),
        # attrs={"a": {"target": "_blank"}}
    )
    number = tables.Column(
        # accessor="pk",
        # verbose_name=gettext_lazy("ID"),
        linkify=lambda value, record: reverse("change-request", kwargs=dict(pk=record.pk)),
        # attrs={"a": {"target": "_blank"}}
        # order_by="pk",
    )
    contract = tables.Column(
        _("Contract"),
        tables.A("contract__number"),
        # verbose_name=gettext_lazy("Contract"),
        linkify=lambda value, record: reverse(
            "contract-detail", kwargs=dict(number=record.contract.number)
        ),
        # attrs={"a": {"target": "_blank"}},
        order_by="contract__number",
    )
    pi = tables.Column(
        gettext_lazy("Contract PI"),
        tables.A("contract__pi__full_name_with_email"),
        orderable=False,
    )
    title = tables.Column(
        _("Title"),
        tables.A("contract__project_title"),
        # verbose_name=gettext_lazy("Contract"),
        linkify=lambda value, record: reverse(
            "contract-detail", kwargs=dict(number=record.contract.number)
        ),
        order_by="contract__project_title",
    )

    def render_updated_at(self, record, value):
        if value:
            # return (value or record.state_changed_at).strftime("%Y-%m-d")
            return value.strftime("%Y-%m-%d")
        return _("N/A")

    def render_description(self, record, value):
        if not value:
            return "N/A"
        return mark_safe(value)

    class Meta:
        model = models.ChangeRequest
        fields = ("state", "updated_at", "number", "contract", "pi")


# class ReportTable(tables.Table):
#     # application = tables.Column(
#     #     linkify=lambda value, record: reverse(
#     #         "application-detail", kwargs=dict(number=record.application.number)
#     #     )
#     # )
#     contract = tables.Column(
#         linkify=lambda value, record: reverse(
#             "contract-detail", kwargs=dict(number=record.contract.number)
#         )
#     )
#     # number = tables.Column(
#     #         # linkify=lambda value, record: reverse("report-detail", kwargs=dict(number=record.number))
#     # )
#     state = StateColumn()

#     # def render_number(self, value, record, *args, **kwargs):
#     #     return 'abc'

#     def render_id(self, value, record, *args, **kwargs):
#         # breakpoint()
#         # c = record.contract
#         return format_html(
#             '<a href="{}">{}</a>',
#             reverse("report", kwargs={"pk": record.pk}),
#             f"{record.contract}:{record.period}:{record.type}",
#         )

#     class Meta:
#         model = models.Contract
#         fields = (
#             "id",
#             "state",
#             # "number",
#             # "application",
#             "contract",
#             # "contract_pi",
#         )


# vim:set ft=python.django:
