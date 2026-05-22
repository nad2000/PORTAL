from django.db import migrations

try:
    from django.contrib.postgres.operations import UnaccentExtension

    class Migration(migrations.Migration):
        dependencies = [
            ("portal", "0064_changetype_alter_contract_preamble_and_more"),
        ]

        operations = [
            UnaccentExtension(),
        ]
except:

    class Migration(migrations.Migration):
        dependencies = [
            ("portal", "0064_changetype_alter_contract_preamble_and_more"),
        ]
        operations = []
