from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("portal", "0021_historicalround_tac_historicalround_tac_en_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="historicalround",
            name="notify_nominator",
            field=models.BooleanField(
                default=False, verbose_name="Notify nominator/principal/mentor"
            ),
        ),
        migrations.AddField(
            model_name="round",
            name="notify_nominator",
            field=models.BooleanField(
                default=False, verbose_name="Notify nominator/principal/mentor"
            ),
        ),
    ]
