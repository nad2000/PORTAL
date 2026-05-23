import getpass
from urllib.parse import urljoin
import itertools

import html2text
from django.conf import settings
from django.contrib.sites.models import Site
from django.core import mail
from django.urls import reverse
from django.db.models import query
import mimetypes
from multisite.models import Alias
from sentry_sdk import capture_exception

from .. import models

__send_mail = mail.send_mail

DEFAULT_HTML_FOOTER = """
<br>To learn more about the Prime Minister’s Science Prizes
<a href='https://www.pmscienceprizes.org.nz/'>click here</a>.<br>
<br>Ngā mihi nui,</p><br>
<p style='margin-bottom:12.0pt'><span style='font-size:12.0pt;
font-family:"Helvetica",sans-serif;color:black'>
<img border='0' src='%(logo_url)s'
alt='PM’s Science Prizes Logo Alternative - Consider the environment before printing this email.'></span><br>
<br>
Ngā Kaiwhakahaere o Te Puiaki Pūtaiao a Te Pirimia<br>
Prime Minister’s Science Prize Secretariat</p>
<table border='0' cellspacing='0' cellpadding='0' style=
'border-collapse:collapse'>
<tbody><tr><td style='padding:0cm 0cm 0cm 0cm'>
<p style='line-height:115%%'><b><span style='font-size:8.5pt;
line-height:115%%;color:black'>Waea telephone &nbsp;</span></b><span
style='font-size:8.5pt;line-height:115%%;color:black'>+64 4 470 5762<br>
<b><style='font-size:8.5pt;line-height:115%%;color:black'>Īmēra email</span></b><span
style='font-size:8.5pt;line-height:115%%'>&nbsp;</span><span
style='font-size:8.5pt;line-height:115%%;color:black;background:white'>
<a href='mailto:pmscienceprizes@royalsociety.org.nz'>
<span style='color:black'>pmscienceprizes@royalsociety.org.nz</span></a></span></p>
<p><b><span style='font-size:8.5pt;color:black'>C/- Royal Society Te Apārangi</span>
</b><span style='font-size:8.5pt;color:black'><br>
11 Turnbull Street, Thorndon, Wellington 6011<br>
PO Box 598, Wellington 6140, New Zealand<br>
<a href='http://royalsociety.org.nz/' ><b><span style='color:black'>ROYALSOCIETY.ORG.NZ</span>
</b></a></span></p><br>
<p><i><span style='font-size:8.0pt;color:black'>Please consider the environment before
printing this email. The information contained in this email message is intended only
for the addressee and may be confidential. If you are not the intended recipient, please
 notify us immediately.</span></i></p>
</td><td width='25%%' valign='bottom' style='width:25.0%%;padding:0cm 5.4pt 0cm 5.4pt'></td>
</tr></tbody></table>
"""

# TODO:
DEFAULT_SITE_HTML_FOOTER = {
    "portal.pmscienceprizes.org.nz": DEFAULT_HTML_FOOTER,
    "portal.pmspaceprizes.org.nz": """
<br>To learn more about the Prime Minister’s Space Prizes
<a href='https://pmspaceprizes.org.nz/'>click here</a>.<br>
<br>Ngā mihi nui,</p><br>
<p style='margin-bottom:12.0pt'><span style='font-size:12.0pt;
font-family:"Helvetica",sans-serif;color:black'><img border='0'
    src='%(logo_url)s'
    alt='PM’s Space Prizes Logo Alternative - Consider the environment before printing this email.'></span><br>
<br>
Prime Minister’s Space Prize Secretariat</p>
<table border='0' cellspacing='0' cellpadding='0' style=
'border-collapse:collapse'>
<tbody><tr><td style='padding:0cm 0cm 0cm 0cm'>
<p style='line-height:115%%'><b><span style='font-size:8.5pt;
line-height:115%%;color:black'>Waea telephone &nbsp;</span></b><span
style='font-size:8.5pt;line-height:115%%;color:black'>+64 4 470 5762<br>
<b><style='font-size:8.5pt;line-height:115%%;color:black'>Īmēra email</span></b><span
style='font-size:8.5pt;line-height:115%%'>&nbsp;</span><span
style='font-size:8.5pt;line-height:115%%;color:black;background:white'>
<a href='mailto:pmspaceprizes@royalsociety.org.nz'>
<span style='color:black'>pmspaceprizes@royalsociety.org.nz</span></a></span></p>
<p><b><span style='font-size:8.5pt;color:black'>C/- Royal Society Te Apārangi</span>
</b><span style='font-size:8.5pt;color:black'><br>
11 Turnbull Street, Thorndon, Wellington 6011<br>
PO Box 598, Wellington 6140, New Zealand<br>
<a href='http://royalsociety.org.nz/' ><b><span style='color:black'>ROYALSOCIETY.ORG.NZ</span>
</b></a></span></p><br>
<p><i><span style='font-size:8.0pt;color:black'>Please consider the environment before
printing this email. The information contained in this email message is intended only
for the addressee and may be confidential. If you are not the intended recipient, please
 notify us immediately.</span></i></p>
</td><td width='25%%' valign='bottom' style='width:25.0%%;padding:0cm 5.4pt 0cm 5.4pt'></td>
</tr></tbody></table>
""",
    "international.royalsociety.org.nz": """
<br>To learn more about the Catalyst Fund administered by the Royal Society Te Apārangi
<a href='https://www.royalsociety.org.nz/what-we-do/funds-and-opportunities/catalyst-fund/'>click here</a>.<br>
<br>Ngā mihi nui,</p><br>
<p style='margin-bottom:12.0pt'><span style='font-size:12.0pt;
font-family:"Helvetica",sans-serif;color:black'>
<img border='0' src='%(logo_url)s'alt='Catalyst Fund Logo Alternative - Consider the environment before printing this email.'></span><br>
<br>
<br>
International Applications</p>
<table border='0' cellspacing='0' cellpadding='0' style=
'border-collapse:collapse'>
<tbody><tr><td style='padding:0cm 0cm 0cm 0cm'>
<p style='line-height:115%%'><b><span style='font-size:8.5pt;
line-height:115%%;color:black'>Waea telephone &nbsp;</span></b><span
style='font-size:8.5pt;line-height:115%%;color:black'>+64 4 470 5756<br>
<b><style='font-size:8.5pt;line-height:115%%;color:black'>Īmēra email</span></b><span
style='font-size:8.5pt;line-height:115%%'>&nbsp;</span><span
style='font-size:8.5pt;line-height:115%%;color:black;background:white'>
<a href='mailto:International.Applications@royalsociety.org.nz'>
<span style='color:black'>International.Applications@royalsociety.org.nz</span></a></span></p>
<p><b><span style='font-size:8.5pt;color:black'>Royal Society Te Apārangi</span>
</b><span style='font-size:8.5pt;color:black'><br>
11 Turnbull Street, Thorndon, Wellington 6011<br>
PO Box 598, Wellington 6140, New Zealand<br>
<a href='http://royalsociety.org.nz/' ><b><span style='color:black'>ROYALSOCIETY.ORG.NZ</span>
</b></a></span></p><br>
<p><i><span style='font-size:8.0pt;color:black'>Please consider the environment before
printing this email. The information contained in this email message is intended only
for the addressee and may be confidential. If you are not the intended recipient, please
 notify us immediately.</span></i></p>
</td><td width='25%%' valign='bottom' style='width:25.0%%;padding:0cm 5.4pt 0cm 5.4pt'></td>
</tr></tbody></table>
""",
    "puanga.royalsociety.org.nz": """
<br>To learn more about %(site_name)s administered by the Royal Society Te Apārangi
<a href='https://www.royalsociety.org.nz/what-we-do/funds-and-opportunities/puanga'>click here</a>.<br>
<br>Ngā mihi nui,</p><br>
<p style='margin-bottom:12.0pt'><span style='font-size:12.0pt;
font-family:"Helvetica",sans-serif;color:black'>
<table border="0"><tr>
<td style="text-align: left;">
<img border='0'
  style="display: inline-block; margin-top: 5px; margin-bottom: 10px; vertical-align: top; width: auto"
  src="https://%(domain)s/static/images/MBIE_logo.webp"
  alt='Ministry of Business, Innovation & Employment Logo Alternative - Consider the environment before printing this email.'>
</td>
<td style="text-align: right;">
<img border='0'
  style="float: right; display: inline-block; margin-top: 5px; margin-bottom: 10px; vertical-align: top; width: auto"
  src="https://%(domain)s/static/images/RS_logo.webp"
  alt='Royal Society Te Apārangi'>
</td>
</tr></table>
</span><br>
<br>
<br>
%(site_name)s</p>
<table border='0' cellspacing='0' cellpadding='0' style=
'border-collapse:collapse'>
<tbody><tr><td style='padding:0cm 0cm 0cm 0cm'>
<p style='line-height:115%%'><b><span style='font-size:8.5pt;
line-height:115%%;color:black'>Waea telephone &nbsp;</span></b><span
style='font-size:8.5pt;line-height:115%%;color:black'>+64 4 470 5756<br>
<b><style='font-size:8.5pt;line-height:115%%;color:black'>Īmēra email</span></b><span
style='font-size:8.5pt;line-height:115%%'>&nbsp;</span><span
style='font-size:8.5pt;line-height:115%%;color:black;background:white'>
<a href='mailto:puanga@royalsociety.org.nz'>
<span style='color:black'>puanga@royalsociety.org.nz</span></a></span></p>
<p><b><span style='font-size:8.5pt;color:black'>Royal Society Te Apārangi</span>
</b><span style='font-size:8.5pt;color:black'><br>
11 Turnbull Street, Thorndon, Wellington 6011<br>
PO Box 598, Wellington 6140, New Zealand<br>
<a href='http://royalsociety.org.nz/' ><b><span style='color:black'>ROYALSOCIETY.ORG.NZ</span>
</b></a></span></p><br>
<p><i><span style='font-size:8.0pt;color:black'>Please consider the environment before
printing this email. The information contained in this email message is intended only
for the addressee and may be confidential. If you are not the intended recipient, please
 notify us immediately.</span></i></p>
</td><td width='25%%' valign='bottom' style='width:25.0%%;padding:0cm 5.4pt 0cm 5.4pt'></td>
</tr></tbody></table>
""",
    "xn--twhia-fwa.royalsociety.org.nz": """
<br>To learn more about %(site_name)s administered by the Royal Society Te Apārangi
<a href='https://www.royalsociety.org.nz/what-we-do/funds-and-opportunities/tawhia-te-mana/'>click here</a>.<br>
<br>Ngā mihi nui,</p><br>
<p style='margin-bottom:12.0pt'><span style='font-size:12.0pt;
font-family:"Helvetica",sans-serif;color:black'>
<table border="0"><tr>
<td style="text-align: left; width: 50%%;">
<img border='0'
  style="display: inline-block; margin-top: 5px; margin-bottom: 10px; vertical-align: top; width: 100%%;"
  src="https://%(domain)s/static/images/MBIE_logo.webp"
  alt='Ministry of Business, Innovation & Employment Logo Alternative - Consider the environment before printing this email.'>
</td>
<td style="text-align: right; width: 50%%;">
<img border='0'
  style="float: right; max-height: 120px; display: inline-block; margin-top: 5px; margin-bottom: 10px; vertical-align: top; width: 100%%;"
  src="https://%(domain)s/static/images/RS_logo.webp"
  alt='Royal Society Te Apārangi'>
</td>
</tr></table>
</span><br>
<br>
<br>
%(site_name)s</p>
<table border='0' cellspacing='0' cellpadding='0' style=
'border-collapse:collapse'>
<tbody><tr><td style='padding:0cm 0cm 0cm 0cm'>
<p style='line-height:115%%'><b><span style='font-size:8.5pt;
line-height:115%%;color:black'>Waea telephone &nbsp;</span></b><span
style='font-size:8.5pt;line-height:115%%;color:black'>+64 4 470 5764<br>
<b><style='font-size:8.5pt;line-height:115%%;color:black'>Īmēra email</span></b><span
style='font-size:8.5pt;line-height:115%%'>&nbsp;</span><span
style='font-size:8.5pt;line-height:115%%;color:black;background:white'>
<a href='mailto:tawhia@royalsociety.org.nz'>
<span style='color:black'>tawhia@royalsociety.org.nz</span></a></span></p>
<p><b><span style='font-size:8.5pt;color:black'>Royal Society Te Apārangi</span>
</b><span style='font-size:8.5pt;color:black'><br>
11 Turnbull Street, Thorndon, Wellington 6011<br>
PO Box 598, Wellington 6140, New Zealand<br>
<a href='http://royalsociety.org.nz/' ><b><span style='color:black'>ROYALSOCIETY.ORG.NZ</span>
</b></a></span></p><br>
<p><i><span style='font-size:8.0pt;color:black'>Please consider the environment before
printing this email. The information contained in this email message is intended only
for the addressee and may be confidential. If you are not the intended recipient, please
 notify us immediately.</span></i></p>
</td><td width='25%%' valign='bottom' style='width:25.0%%;padding:0cm 5.4pt 0cm 5.4pt'></td>
</tr></tbody></table>
""",
}


def send_mail(
    subject,
    message=None,
    from_email=None,
    recipients=None,
    cc=None,
    bcc=None,
    attachments=None,
    fail_silently=False,
    auth_user=None,
    auth_password=None,
    connection=None,
    html_message=None,
    html_footer=None,
    request=None,
    reply_to=None,
    invitation=None,
    token=None,
    # convert_to_html=False,
    convert_to_html=True,
    thread_topic=None,
    thread_index=None,
    site=None,
):
    if site and isinstance(site, int):
        site = Site.objects.get(pk=site)
    if not site:
        site = (invitation and invitation.site) or Site.objects.get_current()

    if request:
        domain = request.get_host()
    elif site:
        domain = site.domain
    elif from_email and "@" in from_email:
        domain = from_email.split("@")[1]

    # if ":" in domain:
    #     domain = domain.split(":")[0]
    if domain and domain.startswith("xn--"):
        utf_domain = domain.encode().decode("idna")
    else:
        utf_domain = domain
    root = f"https://{domain}"

    if domain:
        if ":" in domain:
            domain, port = domain.split(":")
        else:
            port = None

        if not site:
            alias = Alias.objects.resolve(host=domain, port=port)
            site = alias.site

    if not recipients:
        recipients = settings.ADMINS

    if recipients and isinstance(recipients, (list, tuple, query.QuerySet)):
        recipients = [
            (
                r.lower()
                if isinstance(r, str)
                else (
                    f"{r[0]} <{r[1].lower()}>"
                    if isinstance(r, (tuple, list))
                    else r.full_email_address
                )
            )
            for r in recipients
        ]
    if recipients and isinstance(recipients, str):
        recipients = [recipients.strip().lower()]

    if not from_email or "@" not in from_email:
        if port or ":" in domain or "." not in domain:
            from_email = f"{site.name} <{from_email or 'noreply'}@{site.domain}>"
        else:
            from_email = f"{site.name} <{from_email or 'noreply'}@{domain}>"

    if not message and html_message:
        message = html2text.html2text(html_message)
    elif message and not html_message and convert_to_html:
        html_message = "\n".join(
            f"<p>{line}</p>" if line.strip() else "<br/>" for line in message.splitlines()
        )
        # html_message = f"<html><body><pre>{html_message}</pre></body></html>"

    if message:
        message = message.replace("\r\n", "\n").replace("\r", "\n")
        message = f"""{message}

***
**🌱 Think Before You Print | Green Communicator**

*Please consider the environment before printing this email. Let's keep it on the screen to preserve our natural resources.*

By choosing to read this digitally, you help:
* **Conserve forests:** Reduces raw paper demand and protects crucial biodiversity.
* **Lower carbon emissions:** Decreases the energy used in paper manufacturing, toner production, and transportation.
* **Minimize waste:** Prevents paper clutter and ensures our operational footprint stays as light as possible.

*"Earth provides enough to satisfy every person's need, but not every person's waste."*

Together, we can build a more sustainable, paperless future. Please consider filing this email digitally rather than printing.
"""

    if html_message:
        if not html_footer:
            html_footer = DEFAULT_SITE_HTML_FOOTER.get(site.domain, DEFAULT_HTML_FOOTER) % {
                "domain": domain,
                "utf_domain": utf_domain,
                "site_name": site.name,
                "logo_url": (
                    f"{urljoin(root, 'static/images/alt_logo.webp')}"
                    if site.domain == "portal.pmscienceprizes.org.nz"
                    else (
                        f"{urljoin(root, 'static/images/pmspace-logo.webp')}"
                        if site.pk == 7
                        else f"{urljoin(root, f'static/images/{site.domain}/alt_logo_small.webp')}"
                    )
                ),
            }
        html_message = f"""<html>
  <body>
    {html_message}
    {html_footer}
    <-- The above footer is designed to be visually appealing and informative, while also conveying the importance of environmental responsibility. It includes a clear call to action, benefits of reading digitally, and a relevant quote to inspire sustainable behavior. The styling is clean and professional, using colors and fonts that align with the organization's branding. -->
    <div style="font-family: Arial, sans-serif; font-size: 13px; color: #2e3d30; line-height: 1.5; border-top: 1px solid #dcdcdc; padding-top: 12px; margin-top: 20px;">
        <!-- Main Eco Heading -->
        <p style="margin: 0 0 8px 0; font-size: 14px; font-weight: bold; color: #1e5631;">
            🌱 Think Before You Print | Green Communicator
        </p>

        <!-- Core Message -->
        <p style="margin: 0 0 12px 0; font-style: italic;">
            Please consider the environment before printing this email.
            Let's keep it on the screen to preserve our natural resources.
        </p>

        <!-- Benefits List Header -->
        <p style="margin: 0 0 6px 0; font-weight: bold; color: #4a5d4e;">
            By choosing to read this digitally, you help:
        </p>

        <!-- Benefits Bullet Points -->
        <ul style="margin: 0 0 12px 0; padding-left: 20px;">
            <li style="margin-bottom: 4px;">
                <strong>Conserve forests:</strong> Reduces raw paper demand
                and protects crucial biodiversity.</li>
            <li style="margin-bottom: 4px;"><strong>Lower carbon emissions:</strong> Decreases the energy used in paper manufacturing, toner production, and transportation.</li>
            <li style="margin-bottom: 4px;"><strong>Minimize waste:</strong> Prevents paper clutter and ensures our operational footprint stays as light as possible.</li>
        </ul>

        <!-- Closing Quote & Call to Action -->
        <p style="margin: 0; font-size: 12px; color: #556b2f; line-height: 1.4;">
            <em>"Earth provides enough to satisfy every person's need, but not every person's waste."</em><br>
            Together, we can build a more sustainable, paperless future. Please consider filing this email digitally rather than printing.
        </p>
    </div>

  </body>
</html>
"""

    if not token:
        token = models.get_unique_mail_token()
    if not thread_index:
        thread_index = token
    url = reverse("unsubscribe", kwargs=dict(token=token))
    if request:
        url = request.build_absolute_uri(url)
    else:
        url = f"{urljoin(root, url)}"
    if port or ":" in domain or "." not in domain:
        headers = {
            "Message-ID": f"<{token}@{site.domain}>",
            "List-Unsubscribe": f"<{url}>",
            "Return-Path": f"{getpass.getuser()}@{site.domain}",
            "Return-Receipt-To": f"{getpass.getuser()}@{site.domain}",
            "Disposition-Notification-To": f"{getpass.getuser()}@{site.domain}",
        }
    else:
        headers = {
            "Message-ID": f"<{token}@{domain}>",
            "List-Unsubscribe": f"<{url}>",
            "Return-Path": f"{getpass.getuser()}@{domain}",
            "Return-Receipt-To": f"{getpass.getuser()}@{domain}",
            "Disposition-Notification-To": f"{getpass.getuser()}@{domain}",
        }
    # headers["Content-Type"] = "text/plain; markup=markdown"
    # headers["MIME-Version"] = "1.0"
    # headers["Auto-Submitted"] = "auto-generated"

    subject_prefix = f"[{site.name}]" if site else settings.EMAIL_SUBJECT_PREFIX
    if subject and "\n" in subject:
        subject = subject.replace("\n", " -- ")
    if not subject.startswith(subject_prefix):
        subject = f"{subject_prefix} {subject}"
    if not thread_topic:
        thread_topic = subject
    headers["Thread-Index"] = thread_index
    headers["Thread-Topic"] = thread_topic
    if cc and not isinstance(cc, (list, tuple, query.QuerySet)):
        cc = [cc]
    if bcc and not isinstance(bcc, (list, tuple, query.QuerySet)):
        bcc = [bcc]
    msg = mail.EmailMultiAlternatives(
        subject=subject,
        body=message,
        from_email=from_email,
        to=recipients,
        # attachments=attachments,
        cc=cc or None,
        bcc=bcc or None,
        headers=headers,
    )
    # msg.content_subtype = "markdown"
    if attachments:
        for a in attachments:
            msg.attach(
                a.name,
                a.file.getvalue(),
                getattr(a, "content_type", None) or mimetypes.guess_type(a.name)[0],
            )
    if not reply_to and invitation and (inviter := invitation.inviter):
        reply_to = inviter.full_email_address
    if reply_to:
        msg.reply_to = [reply_to]

    if message:
        msg.attach_alternative(message, 'text/plain; markup=markdown; charset="utf-8"')

    if message:
        msg.attach_alternative(message, 'text/markdown; charset="utf-8"')

    if html_message:
        msg.attach_alternative(html_message, "text/html")

    try:
        resp = msg.send()
    except Exception as ex:
        capture_exception(ex)
        if not fail_silently:
            raise ex
        resp = ex

    all_recipients = list(
        recipients.union(bcc or [])
        if isinstance(recipients, set)
        else ((recipients or []) + (bcc or []))
    )
    ml = models.MailLog.create(
        user=request.user if request and request.user.is_authenticated else None,
        recipient=all_recipients[0],
        sender=from_email,
        subject=subject,
        was_sent_successfully=resp,
        token=token,
        invitation=invitation,
        site=site,
        thread_index=thread_index,
        thread_topic=thread_topic,
        message=message,
        html_message=html_message,
    )
    models.Recipient.bulk_create(
        [
            models.Recipient(
                message=ml,
                recipient=r,
            )
            for t, r in itertools.chain(
                (("to", r) for r in (recipients or [])),
                (("bcc", r) for r in (bcc or [])),
                (("cc", r) for r in (cc or [])),
            )
        ]
    )

    if not resp:
        if isinstance(resp, int):
            raise Exception(
                f"Failed to email the message; error code: {resp}. Please contact a Hub administrator!"
            )
        else:
            raise Exception(
                f"Failed to email the message: {resp.error}. Please contact a Hub administrator!"
            )
    return resp


def mail_admins(subject, message, fail_silently=False, connection=None, html_message=None):
    """Send a message to the admins, as defined by the ADMINS setting."""
    if not all(isinstance(a, (list, tuple)) and len(a) == 2 for a in settings.ADMINS):
        raise ValueError("The ADMINS setting must be a list of 2-tuples.")
    recipients = set([f'"{a[0]}" <{a[1]}>' for a in settings.ADMINS])
    recipients.update([u.full_email_address for u in models.User.where(is_superuser=True).all()])

    send_mail(
        subject=subject,
        message=message,
        recipients=recipients,
        fail_silently=fail_silently,
        connection=connection,
        html_message=html_message,
    )
