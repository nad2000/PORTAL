from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("portal", "0025_alter_member_unique_together_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="historicalmember",
            name="has_authorized",
        ),
        migrations.RemoveField(
            model_name="member",
            name="has_authorized",
        ),
    ]
