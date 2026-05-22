from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("sites", "0004_auto_20210331_1418"),
        ("users", "0004_auto_20220308_1655"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="staff_of_sites",
            field=models.ManyToManyField(blank=True, related_name="staff_users", to="sites.Site"),
        ),
    ]
