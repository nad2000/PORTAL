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
import sys
from pathlib import Path

import django
from django.db import transaction

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

    from portal.models import MailLog

    full_msg = open(sys.argv[1]).read() if len(sys.argv) > 1 else sys.stdin.read()
    msg = email.message_from_string(full_msg)

    to = msg["to"]
    subject = msg["subject"]
    body = msg["body"]
    if not msg.is_multipart():
        body = msg.get_payload(decode=True)

    message_id = msg["references"] or msg["in-reply-to"]

    for part in msg.walk():
        content_type = part.get_content_type()
        if not message_id:
            message_id = part["in-reply-to"] or part["original-message-id"] or part["message-id"]
        if not message_id:
            continue
        message_id = message_id.split("@")[0][1:]
        if not message_id:
            continue
        ml = MailLog.where(token=message_id).first()
        if ml:
            with transaction.atomic():
                if ml.error:
                    ml.error += "\n\n****************************************\n"
                else:
                    ml.error = ''
                ml.error += f"{subject}\n{datetime.datetime.now()}"
                if payload := (body or part.get_payload()):
                    if isinstance(payload, list):
                        payload = payload[0].get_payload()
                    ml.error += f"\n========================================\n{payload}"
                if content_type != 'message/disposition-notification':
                    ml.was_sent_successfully = False
                ml.save()
                if ml.invitation:
                    if content_type != 'message/disposition-notification':
                        ml.invitation.bounce()
                        ml.invitation.save()
            break
        else:
            message_id = None

    # with open("%s-%s.txt" % (msg["from"], subject), "w") as f:
    #     f.write(full_msg)
