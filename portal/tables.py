import django_tables2 as tables
from django.shortcuts import reverse
from django.utils.html import format_html, mark_safe
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from . import models


class SubscriptionTable(tables.Table):
    class Meta:
        model = models.Subscription
        template_name = "django_tables2/bootstrap4.html"
        attrs = {"class": "table table-striped"}
        fields = (
            "name",
            "email",
        )


class StatusColumn(tables.Column):
    attrs = {"td": {"class": "align-middle text-center"}}

    def render(self, value, record):
        status = getattr(record, "state", None) or getattr(record, "status", None) or value
        if not status:
            return mark_safe(
                '<i class="far fa-question-circle text-dark text-center" aria-hidden="true"></i>'
            )
        elif status in ["new", "draft"]:
            if status == "draft":
                if isinstance(record, (models.Testimonial, models.Application)):
                    css_classes = "far fa-times-circle text-danger text-center"
                    title = _("Work in progress")
                else:
                    css_classes = "far fa-plus-square text-success text-center"
                    title = _(
                        "The invitation has not been processed yet or it is in draft version"
                    )
            else:
                if isinstance(record, (models.Testimonial, models.Application)):
                    css_classes = "far fa-times-circle text-danger text-center"
                    if isinstance(record, models.Testimonial):
                        title = _("The testimonial was just created")
                    else:
                        title = _("The application was just created")
                else:
                    title = _("The invitation was created")
                    css_classes = "far fa-plus-square text-success text-center"
        elif status == "sent":
            css_classes = "far fa-envelope text-success text-center"
            title = _("The invitation was sent")
        elif status == "accepted":
            if isinstance(record, models.Application):
                css_classes = "fas fa-star text-success text-center"
                title = _("The application was accepted")
            else:
                css_classes = "far fa-envelope-open text-success text-center"
                title = _("The invitation was accepted")
        elif status == "testified":
            css_classes = "fa fa-check-circle text-success text-center"
            title = _("The testimonial was submitted")
        elif status == "opted_out":
            css_classes = "fa fa-ban text-danger text-center"
            title = _("The invitee has turned down the nomination")
        elif status == "bounced":
            css_classes = "fa fa-exclamation-triangle text-danger text-center"
            title = _("The invitation failed or autoreplied. Please check the recipient")
        elif status == "submitted":
            css_classes = "fa fa-check text-success text-center"
            if isinstance(record, models.Testimonial):
                title = _("The testimonial was completed and submitted")
            elif isinstance(record, models.Application):
                title = _("The application was completed and submitted")
            else:
                title = _("The invitation was submitted")
        elif status == "cancelled":
            css_classes = "fa fa-ban text-danger text-center"
            title = _("The application was cancelled")
        elif status == "approved":
            css_classes = "fa fa-thumbs-up text-success text-center"
            title = _("The application was approved")
        else:
            if isinstance(record, (models.Testimonial, models.Application)):
                return mark_safe(
                    '<i class="fas fa-plus text-success text-center" aria-hidden="true"></i>'
                )
            css_classes = "fas fa-plus text-success text-center"
            title = _("The invitation was created")

        return mark_safe(
            f'<i class="{css_classes}" aria-hidden="true" data-toggle="tooltip" title="{title}"></i>'
        )


class NominationTable(tables.Table):
    round = tables.Column(
        linkify=lambda table, record: record.get_absolute_url()
        if record.status not in ["submitted", "accepted"]
        else reverse("nomination-detail", args=[record.pk])
        if record.user == table.request.user or record.nominator == table.request.user or record.email == table.request.user.email
        else None
    )
    status = StatusColumn()
    application = tables.Column(
        # accessor="referee.application.number",
        linkify=lambda record: reverse("application", kwargs=dict(pk=record.application_id))
        if record.application
        else None,
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
            "status",
            "round",
            "nominator",
            "first_name",
            "last_name",
            "email",
            "application",
        )


class TestimonialTable(tables.Table):
    state = StatusColumn(verbose_name=_("Submitted"))
    number = tables.Column(
        accessor="referee.application.number",
        linkify=lambda record: reverse("testimonial-detail", kwargs=dict(pk=record.id)),
    )
    application_title = tables.Column(accessor="referee.application.application_title")
    referee = tables.Column(
        accessor="referee.full_name_with_email",
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
    if record.site_id != 4 and not record.was_submitted and record.is_applicant(u):
        return reverse("application-update", kwargs={"pk": record.id})
    return record.get_absolute_url()


def application_round_link(table, record, value):
    u = table.request.user
    if u.is_staff or u.is_superuser:
        return reverse("admin:portal_round_change", kwargs={"object_id": record.round_id})
    return application_link(table, record, value)


class ApplicationTable(tables.Table):
    state = StatusColumn(verbose_name=_("Submitted"))
    number = tables.Column(linkify=application_link)
    round = tables.Column(linkify=application_round_link)
    email = tables.Column(
        linkify=lambda table, record, value: reverse(
            "admin:users_user_change", kwargs={"object_id": record.submitted_by_id}
        )
        if (table.request.user.is_staff or table.request.user.is_superuser)
        and record.submitted_by_id
        else None
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
            "td": {"style": "padding: 6px 0 0 16px;"},
        },
    )

    def before_render(self, request):
        if (u := request.user) and not u.is_superuser and not u.is_staff:
            self.columns.hide("export")

    def render_number(self, record, value):
        if (
            record.state in ["draft", "new"]
            and (deadline_days := record.deadline_days)
            and record.deadline_days < 5
        ):
            r = record.round
            return format_html(
                """<span
                    data-toggle="tooltip"
                    title="%s"
                >
                    <i class="fas fa-exclamation-circle text-danger"
                    ></i> %s
                </span>"""
                % (
                    _("The round is closing in %s day(s) on %s by %s")
                    % (
                        deadline_days,
                        r.closes_on.strftime("%d-%m-%Y"),
                        r.closes_on.strftime("%I:%M %P"),
                    ),
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
    closes_on = tables.Column(verbose_name=_("Closes On"))
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
            "closes_on",
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
        if (r := record.round) and (deadline_days := r.deadline_days) and deadline_days < 5:
            return format_html(
                """<span
                    data-toggle="tooltip"
                    title="%s"
                >
                    <i class="fas fa-exclamation-circle text-danger"
                    ></i> %s
                </span>"""
                % (
                    _("The round is closing in %(days)s day(s) on %(date)s by %(time)s")
                    % {
                        "days": deadline_days,
                        "date": r.closes_on.strftime("%d-%m-%Y"),
                        "time": r.closes_on.strftime("%I:%M %P"),
                    },
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
        accessor="panellist.full_name_with_email",
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
    state = tables.Column(verbose_name=_("Status"))
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
            "status",
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
        fields = ["number", "round", "submitted_by", "status"]


# vim:set ft=python.django:
