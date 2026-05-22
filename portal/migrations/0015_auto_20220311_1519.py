from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("portal", "0014_auto_20220302_1722"),
    ]

    operations = [
        migrations.AddField(
            model_name="historicalround",
            name="has_referees",
            field=models.BooleanField(default=True, verbose_name="can invite referees"),
        ),
        migrations.AddField(
            model_name="round",
            name="has_referees",
            field=models.BooleanField(default=True, verbose_name="can invite referees"),
        ),
    ]
