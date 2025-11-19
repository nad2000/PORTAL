#!/usr/bin/env python
"""
.procmailrc
:0Wc:
| source $HOME/venv/bin/activate; python prod/email_receiver.py
"""
import datetime
import email
import importlib
import io
import os
import re
import sys
from email.header import decode_header, make_header
from pathlib import Path

import django
from django.core.files.base import File
from django.db import transaction
from django.shortcuts import reverse

# from django.contrib.sites.models import Site
from django.db.models import Value, F

EMAIL_EX = re.compile(r"([a-z0-9]+[.-_+])*[a-z0-9]+@[a-z0-9-.]+(\.[a-z]{2,})+", re.I | re.S)
message_id = None
site = None


def extract_addresses(address):
    if address:
        address = address.strip().lower()
        if "<" in address:
            address = address.split("<")[1].strip()
        match = EMAIL_EX.search(address)
        if match:
            address = match[0].lower()
    return address


if __name__ == "__main__":
    env_name = os.getenv("ENV", "local")
    try:
        importlib.import_module(f"config.settings.{env_name}")
    except ModuleNotFoundError:
        parent_dir = os.path.basename(__file__)
        env_name = parent_dir if parent_dir in ["local", "test", "dev"] else "prod"
    current_path = Path(__file__).parent.resolve()
    sys.path.append(str(current_path / "portal"))

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", f"config.settings.{env_name}")

    django.setup()

    from portal import models
    from portal.utils import send_mail
    from django.conf import settings
    from multisite.models import Alias

    # full_msg = open(sys.argv[1], "rb").read() if len(sys.argv) > 1 else sys.stdin.read()
    # msg = email.message_from_string(full_msg)
    if len(sys.argv) > 1:
        filename = sys.argv[1]
        if os.path.isfile(filename):
            root, ext = os.path.splitext(filename)
            if ext.lower() == ".msg":
                from msg_parser import MsOxMessage
                from msg_parser.email_builder import EmailFormatter
                import tempfile

                msg_obj = MsOxMessage(filename)
                filename = os.path.join(tempfile.gettempdir(), f"{os.path.basename(root)}.eml")
                msg_fmt = EmailFormatter(msg_obj)
                with open(filename, "w") as f:
                    f.write(msg_fmt.build_email())
                msg = msg_fmt.message
            else:
                with open(filename, "r") as f:
                    msg = email.message_from_file(f)
        else:
            message_id = filename
            msg = email.message_from_file(sys.stdin)
    else:
        msg = email.message_from_file(sys.stdin)
    if len(sys.argv) > 2 and not message_id:
        message_id = sys.argv[2]

    to = msg["to"]
    subject = msg["subject"]
    sender = msg["from"]
    thread_index = msg["thread-index"]
    thread_topic = msg["thread-topic"]
    from_addresses = []

    if subject:
        subject = str(make_header(decode_header(subject))).strip()

    # Skip CCed emails:
    if (
        subject
        and subject.strip().startswith("[")
        and (
            models.Site.objects.alias(subject=Value(subject[1:]))
            .filter(name__isnull=False, subject__istartswith=F("name"))
            .exists()
            or subject[1:].startswith(settings.EMAIL_SUBJECT_PREFIX)
        )
    ):
        exit()

    is_autoreply = (
        (x_autoreply := msg["X-Autoreply"])
        and x_autoreply.lower() == "yes"
        or (auto_submitted := msg["Auto-Submitted"])
        and auto_submitted.lower() == "auto-replied"
    )

    sender = extract_addresses(sender)
    to = extract_addresses(to)

    body = msg["body"]
    if not msg.is_multipart():
        body = msg.get_payload(decode=True)

    message_id = message_id or msg["references"] or msg["in-reply-to"]
    has_disposition_notification = any(
        p.get_content_type() == "message/disposition-notification" for p in msg.walk()
    )
    has_ms_tnef = any(p.get_content_type() == "application/ms-tnef" for p in msg.walk())
    has_delivery_status = any(
        p.get_content_type() == "message/delivery-status" for p in msg.walk()
    )

    for part in msg.walk():
        content_type = part.get_content_type()

        if has_delivery_status:
            for line in part.as_string().splitlines():
                if line and re.search(r"(final-recipient|original-recipient)", line, re.I):
                    final_recipient = extract_addresses(line)
                    if final_recipient:
                        from_addresses.append(final_recipient)

        if has_disposition_notification or (
            ("Read: " in subject or "Empfangsbestätigung angezeig" in subject) and has_ms_tnef
        ):
            for p in part.walk():
                message_id = p["original-message-id"] or part["in-reply-to"]
                if not body:
                    body = p.get_payload(decode=True)
                if message_id:
                    break
            final_recipient = extract_addresses(part.as_string())
            if final_recipient:
                from_addresses.append(final_recipient)

        if not message_id:
            message_id = (
                part["in-reply-to"]
                or part["original-message-id"]
                or part["x-ms-exchange-parent-message-id"]
                or part["message-id"]
            )
        if not message_id:
            continue

        if "@" in message_id:
            message_id = message_id.split("@")[0][1:]

        if not message_id:
            continue

        ml = (
            models.MailLog.all_objects.filter(
                models.Q(recipient__in=from_addresses)
                | models.Q(
                    recipient__in=models.Subquery(
                        models.User.where(emailaddress__email__in=from_addresses).values_list(
                            "emailaddress__email"
                        )
                    )
                ),
                token__startswith=message_id,
            ).first()
            or models.MailLog.all_objects.filter(token=message_id).first()
        )
        if ml:
            if site := ml.site:
                settings.SITE_ID = site.pk
            with transaction.atomic():
                if payload := (body or part.get_payload()):
                    if isinstance(payload, list):
                        payload = payload[0].get_payload(decode=True)
                    if payload:
                        for encoding in ["utf-8", "iso-8859-4"]:
                            try:
                                payload = payload.decode(encoding)
                                break
                            except:
                                pass
                        if ml.error:
                            ml.error += "\n\n****************************************\n"
                        else:
                            ml.error = ""
                        ml.error += (
                            f"{subject}\n{datetime.datetime.now()}\n"
                            f"========================================\n{payload}"
                        )
                subject_lower = subject.lower()
                if (
                    (has_disposition_notification)
                    or ("Read: " in subject and has_ms_tnef)
                    or "read:" in subject_lower
                    or not (
                        "undelivered" in subject_lower
                        or "fail" in subject_lower
                        or "error" in subject_lower
                    )
                ):
                    ml.was_sent_successfully = True
                else:
                    ml.was_sent_successfully = False
                ml.save()
                if ml.invitation:
                    site = ml.invitation.site
                    if site and site.pk:
                        settings.SITE_ID = site.pk
                    by = (
                        models.User.where(
                            models.Q(email=ml.recipient)
                            | models.Q(emailaddress__email=ml.recipient)
                        ).first()
                        or ml.user
                    )

                    if (has_disposition_notification) or ("Read: " in subject and has_ms_tnef):
                        ml.invitation.mark_read(
                            by=by,
                            description=subject,
                        )
                    elif re.search("automatic.*reply", subject_lower, re.I) or is_autoreply:
                        ml.invitation.mark_autoreplied(
                            by=by,
                            description=subject,
                        )
                    else:
                        ml.invitation.bounce(by=by, description=subject)
                    ml.invitation.save()
            break
        else:
            message_id = None

    reply_to = None
    token = models.get_unique_mail_token()
    domain = to.split("@")[1].lower()
    if not site:
        site = (alias := Alias.objects.filter(domain__contains=domain).first()) and alias.site
    by = models.User.where(
        models.Q(email__istartswith=sender) | models.Q(emailaddress__email__istartswith=sender)
    ).first()
    if (
        to
        and (message_id or thread_index)
        and (
            to.startswith("contracts")
            or to.startswith("comments")
            or to.startswith("change-requests")
        )
    ):
        if message_id:
            if to.startswith("change-requests"):
                reply_to = (
                    models.ChangeRequestComment.where(token=message_id).order_by("-pk").first()
                )
            else:
                reply_to = models.ContractComment.where(token=message_id).last()
            o = reply_to.object

        elif to.startswith("contracts"):
            contract = o = (
                models.Contract.get_by_thread_index(thread_index=thread_index)
                or models.Contract.all_objects.annotate(
                    subject=Value(f"{subject} - {thread_topic}")
                )
                .filter(subject__icontains=F("number"))
                .order_by("-id")
                .first()
            )
        elif to.startswith("change-requests") or to.startswith("variations"):
            o = models.ChangeRequest.get_by_thread_index(thread_index=thread_index)
            contract = o.contract if o else None
        elif to.startswith("comments"):
            o = models.Model.get_by_thread_index(thread_index=thread_index)
            contract = o.contract if o else None

        if not contract and (reply_to or message_id):
            contract = (
                reply_to and reply_to.object.contract
                if to.startswith("change-requests")
                else message_id
                and (
                    models.Contract.all_objects.filter(comments__token=message_id).last()
                    or models.ChangeRequest.where(token=message_id).first()
                )
            )

        if contract:
            if not site:
                site = contract.site
            if site:
                settings.SITE_ID = site.pk

            body = msg["body"]
            if not msg.is_multipart():
                body = msg.get_payload(decode=True)
            else:
                for part in msg.walk():
                    content_type = part.get_content_type()
                    if content_type == "multipart/alternative":
                        for p in part.get_payload():
                            body = p.get_payload(decode=True)
                            if p.get_content_type() == "text/html":
                                break

            attachments = [
                File(io.BytesIO(a.as_bytes()), name=a.get_filename())
                for a in msg.walk()
                if a.get_filename()
            ]

            if by or body:
                token = models.get_unique_mail_token()
                if body:
                    for encoding in ["utf-8", "iso-8859-4"]:
                        try:
                            body = body.decode(encoding)
                            break
                        except:
                            pass
                comment = models.ContractComment.create(
                    contract=contract,
                    submitted_by=by,
                    comment=body,
                    token=token,
                    # attachment=attachments and attachments[0] or None,
                )

                attachments.append(
                    File(io.BytesIO(msg.as_bytes()), name=f"{models.hash_int(comment.pk)}.eml")
                )
                # for a in attachments[1:]:
                for a in attachments:
                    ca = models.ContractCommentAttachment(comment=comment)
                    ca.attachment.save(content=a, name=a.name)
                    ca.save()

                if by:
                    a = contract.application
                    if (
                        contract.org.research_offices.filter(user=by).exists()
                        or a.submitted_by == by
                        or a.members.filter(user=by).exists()
                    ):
                        recipients = [u for u in site.staff_users.all()] or [
                            u for u in models.User.where(is_superuser=True)
                        ]
                    else:
                        recipients = (
                            contract.host_contact_email
                            or [ro.user for ro in contract.org.research_offices.all()]
                            or [
                                u
                                for u in models.User.where(
                                    models.Q(applications=a) | models.Q(members__application=a)
                                )
                            ]
                        )
                elif reply_to and reply_to.submitted_by:
                    recipients = [reply_to.submitted_by]
                else:
                    if (round := contract.application.round) and round.contact_email:
                        recipients = [round.contact_email]
                    elif (agency := contract.agency) and agency.contract_contact_email:
                        recipients = [agency.contract_contact_email]
                    else:
                        recipients = contract.agency_recipients

                respond_url = f"https://{domain}{reverse('contract-update', kwargs=dict(pk=contract.pk))}#correspondence"
                html_message = f'<p>Comment posted by {by and by.full_name_with_email or sender} to <data value="{contract.number}">{contract}</data>'
                html_message += f":</p>{body}" if body else "."
                html_message += f'<hr/>To respond to this message, please, click here: <a href="{respond_url}">REPLY</a>'
                send_mail(
                    from_email=to,
                    subject=f"Comment posted by {by and by.full_name_with_email or sender} to {contract}",
                    html_message=html_message,
                    cc=[by.full_email_address if by else sender],
                    attachments=attachments or None,
                    recipients=recipients,
                    thread_index=contract.thread_index,
                    thread_topic=contract.thread_topic,
                    token=token,
                    site=site,
                )
        else:
            # Could not find contract
            attachments = [
                File(
                    io.BytesIO(msg.as_bytes()),
                    name=f"{subject or models.hash_int(comment.pk)}.eml",
                )
            ]
            if site:
                recipients = (
                    ["tawhia@royalsociety.org.nz"]
                    if site.pk == 5
                    else [u for u in site.staff_users.all()]
                    or [u for u in models.User.where(is_superuser=True)]
                )
            else:
                recipients = [u for u in models.User.where(is_superuser=True)]
            send_mail(
                from_email=to,
                subject=f"FW: {subject or 'No Subject'}",
                html_message=(
                    "<p>This is an automated message.</p>"
                    "<p>Could not find contract for message sent by "
                    f"{by and by.full_name_with_email or sender} to {to}.</p>"
                ),
                cc=[by.full_email_address if by else sender],
                attachments=attachments,
                recipients=recipients,
                token=token,
                site=site,
                reply_to=by and by.full_email_address or sender,
            )

    if (
        to
        and to.startswith("reports")
        and thread_index
        or (message_id and (reply_to := models.ReportComment.where(token=message_id).last()))
    ):
        if reply_to:
            report = reply_to.report
        else:
            report = o = models.Report.get_by_thread_index(thread_index=thread_index)

        if site := report.contract.site:
            settings.SITE_ID = site.pk

        by = models.User.where(
            models.Q(email__istatswith=sender) | models.Q(emailaddress__email__istatswith=sender)
        ).first()
        body = msg["body"]
        if not msg.is_multipart():
            body = msg.get_payload(decode=True)
        else:
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "multipart/alternative":
                    for p in part.get_payload():
                        body = p.get_payload(decode=True)
                        if p.get_content_type() == "text/html":
                            break

        attachments = [
            File(io.BytesIO(a.as_bytes()), name=a.get_filename())
            for a in msg.walk()
            if a.get_filename()
        ]

        if by or body:
            token = models.get_unique_mail_token()
            if body:
                for encoding in ["utf-8", "iso-8859-4"]:
                    try:
                        body = body.decode(encoding)
                        break
                    except:
                        pass
            comment = models.ReportComment.create(
                report=report,
                submitted_by=by,
                comment=body,
                token=token,
                reply_to=reply_to,
                # attachment=attachments and attachments[0] or None,
            )
            if reply_to and reply_to.submitted_by:
                models.ReportCommentRecipient.create(
                    comment=comment,
                    user=reply_to.submitted_by,
                    email=reply_to.submitted_by.email,
                )
            attachments.append(
                File(io.BytesIO(msg.as_bytes()), name=f"{models.hash_int(comment.pk)}.eml")
            )

            # for a in attachments[1:]:
            for a in attachments:
                ca = models.ReportCommentAttachment(comment=comment)
                ca.attachment.save(content=a, name=a.name)
                ca.save()

            domain = to.split("@")[1]
            if reply_to and reply_to.submitted_by:
                recipients = [reply_to.submitted_by]
            else:
                if (round := report.application.round) and round.contact_email:
                    recipients = [round.contact_email]
                elif (agency := report.contract.agency) and agency.reporting_contact_email:
                    recipients = [agency.reporting_contact_email]
                else:
                    recipients = report.agency_recipients

            respond_url = f"https://{domain}{reverse('report-update', kwargs=dict(pk=report.pk))}#correspondence"
            html_message = f'<p>Comment posted by {by and by.full_name_with_email or sender} to <data value="{report}">{report}</data>'
            html_message += f":</p>{body}" if body else "."
            html_message += f'<hr/>To respond to this message, please, click here: <a href="{respond_url}">REPLY</a>'
            send_mail(
                from_email=to,
                subject=f"Comment posted by {by and by.full_name_with_email or sender} to {report}",
                html_message=html_message,
                cc=[by.full_email_address if by else sender],
                attachments=attachments or None,
                recipients=recipients,
                thread_index=report.thread_index,
                thread_topic=report.thread_topic,
                token=token,
                site=site,
            )

# vim:set ft=python.django:
