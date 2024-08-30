import model_utils.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("portal", "0017_auto_20220322_1312"),
    ]

    operations = [
        migrations.AddField(
            model_name="historicalmember",
            name="status_changed_at",
            field=model_utils.fields.MonitorField(monitor="status"),
        ),
        migrations.AddField(
            model_name="historicalreferee",
            name="status_changed_at",
            field=model_utils.fields.MonitorField(monitor="status"),
        ),
        migrations.AddField(
            model_name="member",
            name="status_changed_at",
            field=model_utils.fields.MonitorField(monitor="status"),
        ),
        migrations.AddField(
            model_name="referee",
            name="status_changed_at",
            field=model_utils.fields.MonitorField(monitor="status"),
        ),
        migrations.AlterField(
            model_name="application",
            name="is_bilingual",
            field=models.BooleanField(default=False, verbose_name="is bilingual"),
        ),
        migrations.AlterField(
            model_name="application",
            name="is_tac_accepted",
            field=models.BooleanField(
                default=False, verbose_name="I have read and accept the Terms and Conditions"
            ),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="is_bilingual",
            field=models.BooleanField(default=False, verbose_name="is bilingual"),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="is_tac_accepted",
            field=models.BooleanField(
                default=False, verbose_name="I have read and accept the Terms and Conditions"
            ),
        ),
    ]
