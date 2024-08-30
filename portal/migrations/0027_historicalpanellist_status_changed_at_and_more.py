import model_utils.fields
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("portal", "0026_remove_historicalmember_has_authorized_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="historicalpanellist",
            name="status_changed_at",
            field=model_utils.fields.MonitorField(monitor="status"),
        ),
        migrations.AddField(
            model_name="panellist",
            name="status_changed_at",
            field=model_utils.fields.MonitorField(monitor="status"),
        ),
    ]
