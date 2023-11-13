#!/usr/bin/env python
"""
.procmailrc
:0Wc:
| source $HOME/venv/bin/activate; python prod/email_receiver.py
"""
import datetime
import email
import importlib
import os
import re
import sys
from pathlib import Path
from email.header import decode_header, make_header

import django
from django.db import transaction

EMAIL_EX = r"([A-Za-z0-9]+[.-_+])*[A-Za-z0-9]+@[A-Za-z0-9-]+(\.[A-Z|a-z]{2,})+"


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

    # full_msg = open(sys.argv[1], "rb").read() if len(sys.argv) > 1 else sys.stdin.read()
    # msg = email.message_from_string(full_msg)
    msg = email.message_from_file(open(sys.argv[1], "r") if len(sys.argv) > 1 else sys.stdin)

    to = msg["to"]
    subject = msg["subject"]
    sender = msg["from"]
    from_addresses = []

    if sender and (match := re.search(EMAIL_EX, sender)):
        sender = match[0].lower()
        from_addresses.append(sender)

    if to and (recipient_match := re.search(EMAIL_EX, to)):
        to = recipient_match[0].lower()

    if subject:
        subject = str(make_header(decode_header(subject)))
    body = msg["body"]
    if not msg.is_multipart():
        body = msg.get_payload(decode=True)

    message_id = msg["references"] or msg["in-reply-to"]

    for part in msg.walk():
        content_type = part.get_content_type()
        if content_type == "message/delivery-status":
            for line in part.as_string().splitlines():
                if line and re.search(r"(final-recipient|original-recipient)", line, re.I):
                    match = re.search(EMAIL_EX, line, re.I)
                    if match:
                        final_recipient = match[0].lower()
                        from_addresses.append(final_recipient)

            pass
        if content_type == "message/disposition-notification":
            for p in part.walk():
                message_id = p["original-message-id"]
                if not body:
                    body = p.get_payload(decode=True)
                if message_id:
                    break
            match = re.search(EMAIL_EX, part.as_string())
            if match:
                final_recipient = match[0].lower()
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
        message_id = message_id.split("@")[0][1:]
        if not message_id:
            continue
        ml = models.MailLog.all_objects.filter(
            models.Q(recipient__in=from_addresses) | models.Q(recipient__in=models.Subquery(
                models.User.where(
                    emailaddress__email__in=from_addresses
                ).values_list("emailaddress__email")
            )),
            token__startswith=message_id, 
        ).first() or models.MailLog.all_objects.filter(token=message_id).first()
        if ml:
            with transaction.atomic():
                if payload := (body or part.get_payload()):
                    if isinstance(payload, list):
                        payload = payload[0].get_payload(decode=True)
                    if payload:
                        for encoding in ["utf-8", 'iso-8859-4']:
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
                if content_type == "message/disposition-notification" or "read:" in subject_lower or not (
                        "undelivered" in subject_lower
                        or "fail" in subject_lower
                        or "error" in subject_lower
                ):
                    ml.was_sent_successfully = True
                else:
                    ml.was_sent_successfully = False
                ml.save()
                if ml.invitation:
                    by = (
                        models.User.where(
                            models.Q(email=ml.recipient)
                            | models.Q(emailaddress__email=ml.recipient)
                        ).first()
                        or ml.user
                    )
                    if content_type == "message/disposition-notification":
                        ml.invitation.mark_read(
                            by=by,
                            description=subject,
                        )
                    elif re.search("automatic.*reply", subject, re.I):
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

    if to and (to.startswith("contracts") or to.startswith("comments")) and message_id:
        if contract := models.Contract.all_objects.filter(comments__token=message_id).last():
            by = models.User.where(
                models.Q(email=sender) | models.Q(emailaddress__email=sender)
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
            if by or body:
                token = models.get_unique_mail_token()
                if body:
                    for encoding in ["utf-8", 'iso-8859-4']:
                        try:
                            body = body.decode(encoding)
                            break
                        except:
                            pass
                models.ContractComment.create(
                    contract=contract,
                    submitted_by=by,
                    comment=body,
                    token=token,
                    # attachment=attachment,
                )
                if by:
                    if (
                        contract.org.research_offices.filter(user=by).exists()
                        or a.submitted_by == by
                        or a.members.filter(user=by).exists()
                    ):
                        recipients = i.host_contact_email or [u for u in Site.objects.get_current().staff_users.all()] or [
                            u for u in User.where(is_superuser=True)
                        ]
                    else:
                        recipients = [ro.user for ro in a.org.research_offices.all()] or [
                            u for u in User.where(Q(applications=a) | Q(members__application=a))
                        ]
                    respond_url = (
                        self.request.build_absolute_uri(
                            reverse("contract-update", kwargs=dict(pk=self.object.pk))
                        )
                        + "#correspondence"
                    )
                    html_message = f'<p>Comment posted by {u.full_name_with_email} to <data value="{i.number}">{i}</data>'
                    html_message += f":</p>{body}" if body else "."
                    html_message += f'<hr/>To responde to this message, please, click here: <a href="{respond_url}">REPLY</a>'
                    breakpoint()
                    send_mail(
                        request=self.request,
                        from_email="contracts",
                        subject=f"Comment posted by {u.full_name_with_email} to {i}",
                        html_message=html_message,
                        cc=[u.full_email_address],
                        attachments=attachment and [attachment],
                        recipients=recipients,
                        thread_index=i.thread_index,
                        thread_topic=i.thread_topic,
                        token=token,
                    )


    # with open("%s-%s.txt" % (msg["from"], subject), "w") as f:
    #     f.write(full_msg)
