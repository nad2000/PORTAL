import django_tables2 as tables
from django.conf import settings
from django.shortcuts import reverse
from django.utils import formats, timezone
from django.utils.html import format_html, mark_safe
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from . import models


class ReportedFundingTable(tables.Table):
    class Meta:
        model = models.ReportedFunding
        template_name = "django_tables2/bootstrap4.html"
        attrs = {"class": "table table-striped"}
        fields = ("title", "doi")


class PublicationTable(tables.Table):
    class Meta:
        model = models.Publication
        template_name = "django_tables2/bootstrap4.html"
        attrs = {"class": "table table-striped"}
        fields = ("title", "doi")


class SubscriptionTable(tables.Table):
    class Meta:
        model = models.Subscription
        template_name = "django_tables2/bootstrap4.html"
        attrs = {"class": "table table-striped"}
        fields = (
            "name",
            "email",
        )


class StateColumn(tables.Column):
    attrs = {"td": {"class": "align-middle text-center"}}

    def render(self, value, record):
        state = getattr(record, "state", None) or value
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
                    title = _(
                        "The invitation has not been processed yet or it is in draft version"
                    )
            else:
                if not isinstance(record, (models.Invitation)):
                    css_classes = "far fa-times-circle text-danger text-center"
                    title = _("The %(verbose_name)s was just created") % {
                        "verbose_name": _(record._meta.verbose_name)
                    }
                    # if isinstance(record, models.Testimonial):
                    #     title = _("The testimonial was just created")
                    # else:
                    #     title = _("The application was just created")
                else:
                    title = _("The invitation was created")
                    css_classes = "far fa-plus-square text-success text-center"
        elif state == "in_review":
            css_classes = "fas fa-question text-success text-center"
            title = _(
                "The application was submitted and sent out to the referees for the reviewing"
            )
        elif state == "sent":
            css_classes = "far fa-envelope text-success text-center"
            title = _("The invitation was sent")
        elif state == "accepted":
            if isinstance(record, models.Application):
                css_classes = "fas fa-star text-success text-center"
                title = _("The application was accepted")
            else:
                css_classes = "far fa-envelope-open text-success text-center"
                title = _("The invitation was accepted")
        elif state == "testified":
            css_classes = "fa fa-check-circle text-success text-center"
            title = _("The testimonial was submitted")
        elif state == "opted_out":
            css_classes = "fa fa-ban text-danger text-center"
            title = _("The invitee has turned down the nomination")
        elif state == "bounced":
            css_classes = "fa fa-exclamation-triangle text-danger text-center"
            title = _("The invitation failed or autoreplied. Please check the recipient")
        elif state == "submitted":
            css_classes = "fa fa-check text-success text-center"
            if isinstance(record, models.Testimonial):
                title = _("The testimonial was completed and submitted")
            elif isinstance(record, models.Application):
                title = _("The application was completed and submitted")
            else:
                title = _("The invitation was submitted")
        elif state == "cancelled":
            css_classes = "fa fa-ban text-danger text-center"
            title = _("The application was cancelled")
        elif state == "approved":
            css_classes = "fa fa-thumbs-up text-success text-center"
            title = _("The application was approved")
        elif state == "funded":
            css_classes = "fa fa-heart text-success text-center"
            title = _("The application was funded")
        elif state == "assessed":
            css_classes = "fa fa-heart text-success text-center"
            title = _("The report was assessed")
        else:
            if isinstance(record, (models.Testimonial, models.Application)):
                return mark_safe(
                    '<i class="fas fa-plus text-success text-center" aria-hidden="true"></i>'
                )
            css_classes = "fas fa-plus text-success text-center"
            title = _("The invitation was created")

        if state_changed_at := getattr(record, "state_changed_at", None):
            # title += f""" {_("(the state updated at <time datetime='%s'>%s</time>)") % (
            #     state_changed_at.isoformat(),
            #     state_changed_at.strftime('%d-%m-%Y %H:%m'))}"""
            title += f""" {_("(the state updated at %s)") % state_changed_at.strftime('%d-%m-%Y %H:%m')}"""

        return mark_safe(
            f'<i class="{css_classes}" aria-hidden="true" data-toggle="tooltip" data-html="true" title="{title}"></i>'
        )


class NominationTable(tables.Table):
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
    first_name = tables.Column(verbose_name=_("Nominee First Name"))
    last_name = tables.Column(verbose_name=_("Nominee Last Name"))
    email = tables.Column(verbose_name=_("Nominee Email Address"))

    def render_application(self, record, value):
        if value:
            return value.number

    def render_nominator(self, record, value):
        if value:
            return value.full_name_with_email

    def before_render(self, request):
        if (u := request.user) and not u.is_superuser and not u.is_staff:
            self.columns.hide("nominator")

    class Meta:
        model = models.Nomination
        template_name = "django_tables2/bootstrap4.html"
        attrs = {"class": "table table-striped table-bordered"}
        fields = (
            "state",
            "round",
            "nominator",
            "first_name",
            "last_name",
            "email",
            "application",
        )


class TestimonialTable(tables.Table):
    state = StateColumn(verbose_name=_("Submitted"))
    number = tables.Column(
        accessor="referee__application__number",
        linkify=lambda record: reverse("testimonial-detail", kwargs=dict(pk=record.id)),
    )
    application_title = tables.Column(accessor="referee__application__application_title")
    referee = tables.Column(
        accessor="referee__full_name_with_email",
        order_by=("referee__first_name", "referee__last_name", "referee__email"),
    )

    class Meta:
        model = models.Testimonial
        template_name = "django_tables2/bootstrap4.html"
        attrs = {"class": "table table-striped table-bordered"}
        fields = ()


def application_link(table, record, value):
    u = table.request.user
    if u.is_superuser:
        return reverse("admin:portal_application_change", kwargs={"object_id": record.id})
    if record.site_id not in [4, 5] and not record.was_submitted and record.is_applicant(u):
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


class ApplicationTable(tables.Table):
    state = StateColumn(verbose_name=_("Submitted"))
    number = tables.Column(linkify=application_link)
    round = tables.Column(linkify=application_round_link)
    email = tables.Column(
        linkify=lambda table, record, value: (
            reverse("admin:users_user_change", kwargs={"object_id": record.submitted_by_id})
            if (table.request.user.is_staff or table.request.user.is_superuser)
            and record.submitted_by_id
            else None
        )
    )
    export = tables.LinkColumn(
        "application-export",
        args=[tables.A("pk")],
        text=gettext_lazy("Export"),
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

    current_contract = tables.columns.linkcolumn.BaseLinkColumn(
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
                "data-toggle": "tooltip",
                "title": gettext_lazy("Create or update a contract"),
            },
            "td": {"class": "text-center"},
        },
    )

    def before_render(self, request, *args, **kwargs):
        view_name = (rm := request.resolver_match) and rm.view_name
        state = rm and rm.kwargs.get("state")
        if state != "funded":
            self.columns.hide("current_contract")
        if (u := request.user) and not u.is_superuser and not u.is_staff:
            self.columns.hide("export")
            self.columns.hide("current_contract")

    # def render_latest_contract(self, record, value):
    #     if record.state == "funded" or record.state == "archived" and record.contract:
    #         return value

    def render_number(self, record, value):
        if (
            record.state in ["draft", "new"]
            and (deadline_days := record.deadline_days)
            and record.deadline_days < 6
        ):
            r = record.round
            closes_at = timezone.localtime(r.closes_at)
            return format_html(
                """<span
                    data-toggle="tooltip"
                    title="%s"
                >
                    <i class="fas fa-exclamation-circle %s"
                    ></i> %s
                </span>"""
                % (
                    _("The round is closing in %s day(s) on %s by %s")
                    % (
                        deadline_days,
                        formats.date_format(closes_at, "d-m-Y"),
                        formats.date_format(closes_at, "P"),
                    ),
                    "text-danger" if record.deadline_days < 4 else "text-warning",
                    value,
                )
            )
        return value

    class Meta:
        model = models.Application
        template_name = "django_tables2/bootstrap4-responsive.html"
        attrs = {"class": "table table-striped table-bordered"}
        fields = (
            "state",
            "number",
            "round",
            "email",
            "first_name",
            "last_name",
            "export",
            # "contract",
        )


def report_link(table, record, value):
    u = table.request.user
    if u.is_superuser:
        return reverse("admin:portal_report_change", kwargs={"object_id": record.id})
    if record.site_id not in [4, 5] and not record.was_submitted and record.is_applicant(u):
        return reverse("report-update", kwargs={"pk": record.id})
    return record.get_absolute_url()


def report_contract_link(table, record, value):
    if value:
        return reverse("contract-detail", kwargs={"number": value.number})
    return f'{reverse("contract-create")}?report_id={record.pk}'


class ReportTable(tables.Table):
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

    class Meta:
        model = models.Report
        template_name = "django_tables2/bootstrap4-responsive.html"
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


class RoundTable(tables.Table):
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

    class Meta:
        model = models.Round
        template_name = "django_tables2/bootstrap4.html"
        attrs = {"class": "table table-striped table-bordered"}
        fields = (
            "title",
            "scheme",
            "opens_on",
            "closes_at",
            "evaluation_count",
        )


class ScoreSheetTable(tables.Table):
    round = tables.Column(
        linkify=lambda record: reverse("score-sheet", kwargs=dict(round=record.round_id))
    )

    class Meta:
        model = models.ScoreSheet
        template_name = "django_tables2/bootstrap4.html"
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


class RoundApplicationTable(tables.Table):
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
                "<span data-toggle='tooltip' title='%s'>%s</span>"
                % (_("Conflict of Interest statement to complete."), value)
            )
        if not coi.has_conflict:
            if record.evaluations.filter(state="submitted", panellist__user=user).exists():
                return format_html(
                    "<span data-toggle='tooltip' title='%s'>%s</span>"
                    % (
                        _("You have already submitted an evaluation of this application."),
                        value,
                    )
                )

            return format_html(
                "<span data-toggle='tooltip' title='%s'>%s</span>"
                % (
                    _(
                        "You have submitted the statement of the conflict of interest. "
                        "Please evaluate the application and submit scores."
                    ),
                    value,
                )
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
                "<span data-toggle='tooltip' title='%s'>%s</span>"
                % (
                    _("The application has not been submitted yet"),
                    value,
                )
            )
        if (r := record.round) and (deadline_days := r.deadline_days) and deadline_days < 6:
            closes_at = timezone.localtime(r.closes_at)
            return format_html(
                """<span
                    data-toggle="tooltip"
                    title="%s"
                >
                    <i class="fas fa-exclamation-circle %s"
                    ></i> %s
                </span>"""
                % (
                    _("The round is closing in %(days)s day(s) on %(date)s by %(time)s")
                    % {
                        "days": deadline_days,
                        "date": formats.date_format(closes_at, "d-m-Y"),
                        "time": formats.date_format(closes_at, "P"),
                    },
                    "text-danger" if deadline_days < 4 else "text-warning",
                    value,
                )
            )
        return value

    class Meta:
        model = models.Application
        template_name = "django_tables2/bootstrap4.html"
        attrs = {"class": "table table-striped table-bordered"}
        fields = (
            "number",
            "first_name",
            "last_name",
            "email",
            "evaluation_count",
        )


class EvaluationTable(tables.Table):
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

    class Meta:
        model = models.Evaluation
        template_name = "django_tables2/bootstrap4.html"
        attrs = {"class": "table table-striped table-bordered"}
        fields = (
            # "round",
            "panellist",
            "total_score",
        )


class RoundConflictOfInterestSatementTable(tables.Table):
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

    class Meta:
        template_name = "django_tables2/bootstrap4.html"
        attrs = {"class": "table table-striped table-bordered"}


class RoundSummaryTable(tables.Table):
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


class InvitationTable(tables.Table):
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
        template_name = "django_tables2/bootstrap4.html"
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


class SummaryReportTable(tables.Table):
    class Meta:
        model = models.Application
        template_name = "django_tables2/bootstrap4.html"
        attrs = {"class": "table table-striped table-bordered"}
        fields = ["number", "round", "submitted_by", "state"]


class ContractTable(tables.Table):
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
        tables.A("pi__full_name_with_email"),
        order_by="members__email",
    )
    notes = StateColumn()

    # email = tables.Column(
    #     linkify=lambda table, record, value: reverse(
    #         "admin:users_user_change", kwargs={"object_id": record.submitted_by_id}
    #     )
    #     if (table.request.user.is_staff or table.request.user.is_superuser)
    #     and record.submitted_by_id
    #     else None
    # )
    # export = tables.LinkColumn(
    #     "application-export",
    #     args=[tables.A("pk")],
    #     text=gettext_lazy("Export"),
    #     attrs={
    #         "a": {
    #             "class": "btn btn-primary btn-sm",
    #             "target": "_blank",
    #             "data-toggle": "tooltip",
    #             "title": gettext_lazy("Export the application into a consolidated PDF file"),
    #         },
    #         "td": {"style": "padding: 6px 0 0 16px;"},
    #     },
    # )

    # def before_render(self, request):
    #     if (u := request.user) and not u.is_superuser and not u.is_staff:
    #         self.columns.hide("export")

    # def render_number(self, record, value):
    #     if (
    #         record.state in ["draft", "new"]
    #         and (deadline_days := record.deadline_days)
    #         and record.deadline_days < 5
    #     ):
    #         r = record.round
    #         return format_html(
    #             """<span
    #                 data-toggle="tooltip"
    #                 title="%s"
    #             >
    #                 <i class="fas fa-exclamation-circle text-danger"
    #                 ></i> %s
    #             </span>"""
    #             % (
    #                 _("The round is closing in %s day(s) on %s by %s")
    #                 % (
    #                     deadline_days,
    #                   # formats.date_format(r.closes_at, "d-m-Y"),
    #                   # formats.date_format(r.closes_at, "P"),
    #                     r.closes_at.strftime("%d-%m-%Y"),
    #                     r.closes_at.strftime("%I:%M %P"),
    #                 ),
    #                 value,
    #             )
    #         )
    #     return value

    class Meta:
        model = models.Contract
        fields = ("state", "number", "application", "pi", "notes")


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
