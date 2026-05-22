from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("portal", "0024_remove_historicalreferee_has_testifed_and_more"),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name="member",
            unique_together={("application", "email")},
        ),
        migrations.AlterUniqueTogether(
            name="panellist",
            unique_together={("round", "email")},
        ),
        migrations.AlterUniqueTogether(
            name="referee",
            unique_together={("application", "email")},
        ),
    ]
