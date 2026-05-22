import subprocess
from datetime import date
from html import escape

from django.core.management.base import BaseCommand


def extract_messages(file_name_prefix, messages):
    date_suffix = date.today().strftime("%y%m%d")
    html_file_name = f"{file_name_prefix}_{date_suffix}.html"
    docx_file_name = f"{file_name_prefix}_{date_suffix}.docx"

    with open(html_file_name, "w") as of:
        print(
            """<html><head><style>
table, th, td {
  border: 1px solid black;
  border-collapse: collapse;
}</style></head><body>""",
            file=of,
        )
        print("<table><thead>", file=of)
        print("<tr><th>EN</th><th>MI</th></tr></thead><tbody>", file=of)
        row_no = 0
        for e in messages:
            if row_no % 2:
                print("<tr>", file=of)
            else:
                print('<tr style="background-color: silver;">', file=of)
            row_no += 1
            print(
                f"""<tr>
  <td>{escape(e.msgid)}</td>
  <td>{e.msgstr and escape(e.msgstr) or "&nbsp;"}</td>
</tr>""",
                file=of,
            )
        print("</tbody></table></body></html>", file=of)

    cp = subprocess.run(
        [
            "lowriter",
            "--headless",
            "--convert-to",
            "docx",
            "--outdir",
            "./",
            # tempfile.gettempdir(),
            html_file_name,
        ],
        capture_output=True,
    )
    if cp.returncode or (
        (stderr := (cp.stderr and cp.stderr.decode())) and "error" in stderr.lower()
    ):
        raise Exception(f"Failed to convert the message file: {stderr}")
    print(f"*** File generated: {docx_file_name}")


class Command(BaseCommand):
    help = (
        "Extract messages and export into MS Word documents. NB! don't forget to refresh PO file: "
        "./manage.py makemessages  -i docs -i genkey -i rapidconnect -i venv -l mi"
    )

    # def add_arguments(self, parser):
    #     parser.add_argument('sample', nargs='+')

    def handle(self, *args, **options):
        import polib

        print(
            "*** Double check if you have refreshed PO file: "
            "./manage.py makemessages  -i docs -i genkey -i rapidconnect -i venv -l mi"
        )
        pofile = polib.pofile("locale/mi/LC_MESSAGES/django.po")
        extract_messages("not_translated", (m for m in pofile if m.msgstr == ""))
        extract_messages("fuzzy_translated", (m for m in pofile if m.fuzzy))
        extract_messages("translated", (m for m in pofile if not m.fuzzy and m.msgstr))
