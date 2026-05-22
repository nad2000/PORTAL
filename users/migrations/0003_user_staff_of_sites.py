from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sites", "0004_auto_20210331_1418"),
        ("users", "0002_auto_20211029_1257"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="staff_of_sites",
            field=models.ManyToManyField(blank=True, null=True, to="sites.Site"),
        ),
    ]
