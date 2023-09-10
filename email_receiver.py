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

EMAIL_EX = r"([A-Za-z0-9]+[.-_])*[A-Za-z0-9]+@[A-Za-z0-9-]+(\.[A-Z|a-z]{2,})+"


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

    full_msg = open(sys.argv[1]).read() if len(sys.argv) > 1 else sys.stdin.read()
    msg = email.message_from_string(full_msg)

    to = msg["to"]
    subject = msg["subject"]
    sender = msg["from"]
    from_addresses = []

    if sender and (match := re.search(EMAIL_EX, sender)):
        sender = match[0].lower()
        from_addresses.append(sender)

    if subject:
        subject = str(make_header(decode_header(subject)))
    body = msg["body"]
    if not msg.is_multipart():
        body = msg.get_payload(decode=True)

    message_id = msg["references"] or msg["in-reply-to"]

    for part in msg.walk():
        content_type = part.get_content_type()
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
            token__startswith=message_id, recipient__in=from_addresses
        ).first()
        if ml:
            with transaction.atomic():
                if payload := (body or part.get_payload()):
                    if isinstance(payload, list):
                        payload = payload[0].get_payload()
                    if payload:
                        if ml.error:
                            ml.error += "\n\n****************************************\n"
                        else:
                            ml.error = ""
                        ml.error += (
                            f"{subject}\n{datetime.datetime.now()}\n"
                            f"========================================\n{payload}"
                        )
                if (
                    content_type == "message/disposition-notification"
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

    # with open("%s-%s.txt" % (msg["from"], subject), "w") as f:
    #     f.write(full_msg)
