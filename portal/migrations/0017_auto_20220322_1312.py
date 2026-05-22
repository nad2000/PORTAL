from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("portal", "0016_auto_20220318_1748"),
    ]

    operations = [
        migrations.RenameField(
            model_name="application",
            old_name="is_bilingual_summary",
            new_name="is_bilingual",
        ),
        migrations.RenameField(
            model_name="historicalapplication",
            old_name="is_bilingual_summary",
            new_name="is_bilingual",
        ),
        migrations.AddField(
            model_name="application",
            name="application_title_en",
            field=models.CharField(
                blank=True, max_length=200, null=True, verbose_name="application name"
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="application_title_mi",
            field=models.CharField(
                blank=True, max_length=200, null=True, verbose_name="application name"
            ),
        ),
        migrations.AddField(
            model_name="historicalapplication",
            name="application_title_en",
            field=models.CharField(
                blank=True, max_length=200, null=True, verbose_name="application name"
            ),
        ),
        migrations.AddField(
            model_name="historicalapplication",
            name="application_title_mi",
            field=models.CharField(
                blank=True, max_length=200, null=True, verbose_name="application name"
            ),
        ),
        migrations.AddField(
            model_name="historicalround",
            name="has_title",
            field=models.BooleanField(default=False, verbose_name="can have a title"),
        ),
        migrations.AddField(
            model_name="round",
            name="has_title",
            field=models.BooleanField(default=False, verbose_name="can have a title"),
        ),
    ]
