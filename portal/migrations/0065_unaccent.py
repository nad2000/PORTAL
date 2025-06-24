from django.contrib.postgres.operations import UnaccentExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("portal", "0064_changetype_alter_contract_preamble_and_more"),
    ]

    operations = [
        UnaccentExtension(),
    ]
