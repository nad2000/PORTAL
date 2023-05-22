import common.models
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import simple_history.models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("portal", "0031_alter_historicalinvitation_first_name_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Keyword",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("name", models.CharField(max_length=100, unique=True, verbose_name="name")),
                (
                    "slug",
                    models.SlugField(
                        allow_unicode=True, max_length=100, unique=True, verbose_name="slug"
                    ),
                ),
            ],
            options={
                "verbose_name": "Keyword",
                "verbose_name_plural": "Keywords",
                "db_table": "keyword",
            },
        ),
        migrations.CreateModel(
            name="SocioEconomicObjective",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True)),
                ("code", models.CharField(max_length=6, primary_key=True, serialize=False)),
                ("description", models.CharField(blank=True, max_length=150, null=True)),
                ("source", models.CharField(blank=True, max_length=255, null=True)),
            ],
            options={
                "verbose_name": "SEO",
                "verbose_name_plural": "SEOs",
                "db_table": "socio_economic_objective",
            },
            bases=(common.models.HelperMixin, models.Model),
        ),
        migrations.AlterModelOptions(
            name="historicalaffiliation",
            options={
                "get_latest_by": ("history_date", "history_id"),
                "ordering": ("-history_date", "-history_id"),
                "verbose_name": "historical affiliation",
                "verbose_name_plural": "historical affiliations",
            },
        ),
        migrations.AlterModelOptions(
            name="historicalapplication",
            options={
                "get_latest_by": ("history_date", "history_id"),
                "ordering": ("-history_date", "-history_id"),
                "verbose_name": "historical application",
                "verbose_name_plural": "historical applications",
            },
        ),
        migrations.AlterModelOptions(
            name="historicalcriterion",
            options={
                "get_latest_by": ("history_date", "history_id"),
                "ordering": ("-history_date", "-history_id"),
                "verbose_name": "historical criterion",
                "verbose_name_plural": "historical criteria",
            },
        ),
        migrations.AlterModelOptions(
            name="historicalevaluation",
            options={
                "get_latest_by": ("history_date", "history_id"),
                "ordering": ("-history_date", "-history_id"),
                "verbose_name": "historical evaluation",
                "verbose_name_plural": "historical evaluations",
            },
        ),
        migrations.AlterModelOptions(
            name="historicalinvitation",
            options={
                "get_latest_by": ("history_date", "history_id"),
                "ordering": ("-history_date", "-history_id"),
                "verbose_name": "historical invitation",
                "verbose_name_plural": "historical invitations",
            },
        ),
        migrations.AlterModelOptions(
            name="historicalmember",
            options={
                "get_latest_by": ("history_date", "history_id"),
                "ordering": ("-history_date", "-history_id"),
                "verbose_name": "historical member",
                "verbose_name_plural": "historical members",
            },
        ),
        migrations.AlterModelOptions(
            name="historicalnomination",
            options={
                "get_latest_by": ("history_date", "history_id"),
                "ordering": ("-history_date", "-history_id"),
                "verbose_name": "historical nomination",
                "verbose_name_plural": "historical nominations",
            },
        ),
        migrations.AlterModelOptions(
            name="historicalorganisation",
            options={
                "get_latest_by": ("history_date", "history_id"),
                "ordering": ("-history_date", "-history_id"),
                "verbose_name": "historical organisation",
                "verbose_name_plural": "historical organisations",
            },
        ),
        migrations.AlterModelOptions(
            name="historicalpanellist",
            options={
                "get_latest_by": ("history_date", "history_id"),
                "ordering": ("-history_date", "-history_id"),
                "verbose_name": "historical panellist",
                "verbose_name_plural": "historical panellists",
            },
        ),
        migrations.AlterModelOptions(
            name="historicalprofile",
            options={
                "get_latest_by": ("history_date", "history_id"),
                "ordering": ("-history_date", "-history_id"),
                "verbose_name": "historical profile",
                "verbose_name_plural": "historical profiles",
            },
        ),
        migrations.AlterModelOptions(
            name="historicalreferee",
            options={
                "get_latest_by": ("history_date", "history_id"),
                "ordering": ("-history_date", "-history_id"),
                "verbose_name": "historical referee",
                "verbose_name_plural": "historical referees",
            },
        ),
        migrations.AlterModelOptions(
            name="historicalround",
            options={
                "get_latest_by": ("history_date", "history_id"),
                "ordering": ("-history_date", "-history_id"),
                "verbose_name": "historical round",
                "verbose_name_plural": "historical rounds",
            },
        ),
        migrations.AlterModelOptions(
            name="historicaltestimonial",
            options={
                "get_latest_by": ("history_date", "history_id"),
                "ordering": ("-history_date", "-history_id"),
                "verbose_name": "historical testimonial",
                "verbose_name_plural": "historical testimonials",
            },
        ),
        migrations.AddField(
            model_name="application",
            name="toa_applied",
            field=models.PositiveSmallIntegerField(
                blank=True,
                default=0,
                help_text="Applied research",
                null=True,
                verbose_name="Applied",
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="toa_basic",
            field=models.PositiveSmallIntegerField(
                blank=True,
                default=0,
                help_text="Pure basic research",
                null=True,
                verbose_name="Basic",
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="toa_experimental",
            field=models.PositiveSmallIntegerField(
                blank=True,
                default=0,
                help_text="Experimental development",
                null=True,
                verbose_name="Experimental",
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="toa_strategic",
            field=models.PositiveSmallIntegerField(
                blank=True,
                default=0,
                help_text="Strategic basic research",
                null=True,
                verbose_name="Strategic",
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="vm_ecs",
            field=models.PositiveSmallIntegerField(
                blank=True,
                default=0,
                help_text="Contributing to Economic Growth through Distinctive R&D. New Zealand needs its businesses and for-profit enterprises to perform at an optimum level and contribute to economic growth. This theme concerns the development of distinctive products, processes, systems and services from Māori knowledge, resources and people. Of particular interest are products that may be distinctive in the international marketplace.",
                null=True,
                verbose_name="Indigenous Innovation",
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="vm_ens",
            field=models.PositiveSmallIntegerField(
                blank=True,
                default=0,
                help_text="Achieving Environmental Sustainability through Iwi and Hapū relationships with land and sea. Like all communities, Māori communities aspire to live in sustainable communities dwelling in healthy environments. Much general environmental research is relevant to Māori. Distinctive environmental research arising in Māori communities relates to the expression of iwi and hapū knowledge, culture and experience – including Kaitiakitanga - in New Zealand land and seascapes.",
                null=True,
                verbose_name="Taiao",
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="vm_hsw",
            field=models.PositiveSmallIntegerField(
                blank=True,
                default=0,
                help_text="Improving Māori Health and Social Well-being. Distinctive challenges to Māori health and social well-being continue to arise within Māori communities disadvantaging them in relation to the general population. Research is needed to meet these ongoing needs.",
                null=True,
                verbose_name="Hauora/Oranga",
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="vm_ink",
            field=models.PositiveSmallIntegerField(
                blank=True,
                default=0,
                help_text="Exploring Indigenous Knowledge and RS&T. This exploratory theme aims to develop a body of knowledge, as a contribution to RS&T, at the interface between indigenous knowledge including mātauranga Māori – and research, science and technology.",
                null=True,
                verbose_name="Mātauranga",
            ),
        ),
        migrations.AddField(
            model_name="historicalapplication",
            name="toa_applied",
            field=models.PositiveSmallIntegerField(
                blank=True,
                default=0,
                help_text="Applied research",
                null=True,
                verbose_name="Applied",
            ),
        ),
        migrations.AddField(
            model_name="historicalapplication",
            name="toa_basic",
            field=models.PositiveSmallIntegerField(
                blank=True,
                default=0,
                help_text="Pure basic research",
                null=True,
                verbose_name="Basic",
            ),
        ),
        migrations.AddField(
            model_name="historicalapplication",
            name="toa_experimental",
            field=models.PositiveSmallIntegerField(
                blank=True,
                default=0,
                help_text="Experimental development",
                null=True,
                verbose_name="Experimental",
            ),
        ),
        migrations.AddField(
            model_name="historicalapplication",
            name="toa_strategic",
            field=models.PositiveSmallIntegerField(
                blank=True,
                default=0,
                help_text="Strategic basic research",
                null=True,
                verbose_name="Strategic",
            ),
        ),
        migrations.AddField(
            model_name="historicalapplication",
            name="vm_ecs",
            field=models.PositiveSmallIntegerField(
                blank=True,
                default=0,
                help_text="Contributing to Economic Growth through Distinctive R&D. New Zealand needs its businesses and for-profit enterprises to perform at an optimum level and contribute to economic growth. This theme concerns the development of distinctive products, processes, systems and services from Māori knowledge, resources and people. Of particular interest are products that may be distinctive in the international marketplace.",
                null=True,
                verbose_name="Indigenous Innovation",
            ),
        ),
        migrations.AddField(
            model_name="historicalapplication",
            name="vm_ens",
            field=models.PositiveSmallIntegerField(
                blank=True,
                default=0,
                help_text="Achieving Environmental Sustainability through Iwi and Hapū relationships with land and sea. Like all communities, Māori communities aspire to live in sustainable communities dwelling in healthy environments. Much general environmental research is relevant to Māori. Distinctive environmental research arising in Māori communities relates to the expression of iwi and hapū knowledge, culture and experience – including Kaitiakitanga - in New Zealand land and seascapes.",
                null=True,
                verbose_name="Taiao",
            ),
        ),
        migrations.AddField(
            model_name="historicalapplication",
            name="vm_hsw",
            field=models.PositiveSmallIntegerField(
                blank=True,
                default=0,
                help_text="Improving Māori Health and Social Well-being. Distinctive challenges to Māori health and social well-being continue to arise within Māori communities disadvantaging them in relation to the general population. Research is needed to meet these ongoing needs.",
                null=True,
                verbose_name="Hauora/Oranga",
            ),
        ),
        migrations.AddField(
            model_name="historicalapplication",
            name="vm_ink",
            field=models.PositiveSmallIntegerField(
                blank=True,
                default=0,
                help_text="Exploring Indigenous Knowledge and RS&T. This exploratory theme aims to develop a body of knowledge, as a contribution to RS&T, at the interface between indigenous knowledge including mātauranga Māori – and research, science and technology.",
                null=True,
                verbose_name="Mātauranga",
            ),
        ),
        migrations.AddField(
            model_name="historicalround",
            name="has_fors",
            field=models.BooleanField(
                default=False,
                help_text="Has Field of Research Categories",
                verbose_name="Has FoRs",
            ),
        ),
        migrations.AddField(
            model_name="historicalround",
            name="has_keywords",
            field=models.BooleanField(
                default=False, help_text="Has Keywords", verbose_name="Has keywords"
            ),
        ),
        migrations.AddField(
            model_name="historicalround",
            name="has_seos",
            field=models.BooleanField(
                default=False,
                help_text="Has Socio-Economic Objective Categories",
                verbose_name="Has SEOs",
            ),
        ),
        migrations.AddField(
            model_name="historicalround",
            name="has_toas",
            field=models.BooleanField(
                default=False, help_text="Has Type of Activity Categories", verbose_name="Has ToA"
            ),
        ),
        migrations.AddField(
            model_name="historicalround",
            name="has_vmts",
            field=models.BooleanField(
                default=False,
                help_text="Has Vision Mātauranga Theme Categories",
                verbose_name="Has VMTs",
            ),
        ),
        migrations.AddField(
            model_name="round",
            name="has_fors",
            field=models.BooleanField(
                default=False,
                help_text="Has Field of Research Categories",
                verbose_name="Has FoRs",
            ),
        ),
        migrations.AddField(
            model_name="round",
            name="has_keywords",
            field=models.BooleanField(
                default=False, help_text="Has Keywords", verbose_name="Has keywords"
            ),
        ),
        migrations.AddField(
            model_name="round",
            name="has_seos",
            field=models.BooleanField(
                default=False,
                help_text="Has Socio-Economic Objective Categories",
                verbose_name="Has SEOs",
            ),
        ),
        migrations.AddField(
            model_name="round",
            name="has_toas",
            field=models.BooleanField(
                default=False, help_text="Has Type of Activity Categories", verbose_name="Has ToA"
            ),
        ),
        migrations.AddField(
            model_name="round",
            name="has_vmts",
            field=models.BooleanField(
                default=False,
                help_text="Has Vision Mātauranga Theme Categories",
                verbose_name="Has VMTs",
            ),
        ),
        migrations.AlterField(
            model_name="historicalaffiliation",
            name="history_date",
            field=models.DateTimeField(db_index=True),
        ),
        migrations.AlterField(
            model_name="historicalapplication",
            name="history_date",
            field=models.DateTimeField(db_index=True),
        ),
        migrations.AlterField(
            model_name="historicalcriterion",
            name="history_date",
            field=models.DateTimeField(db_index=True),
        ),
        migrations.AlterField(
            model_name="historicalevaluation",
            name="history_date",
            field=models.DateTimeField(db_index=True),
        ),
        migrations.AlterField(
            model_name="historicalinvitation",
            name="history_date",
            field=models.DateTimeField(db_index=True),
        ),
        migrations.AlterField(
            model_name="historicalmember",
            name="history_date",
            field=models.DateTimeField(db_index=True),
        ),
        migrations.AlterField(
            model_name="historicalnomination",
            name="history_date",
            field=models.DateTimeField(db_index=True),
        ),
        migrations.AlterField(
            model_name="historicalorganisation",
            name="history_date",
            field=models.DateTimeField(db_index=True),
        ),
        migrations.AlterField(
            model_name="historicalpanellist",
            name="history_date",
            field=models.DateTimeField(db_index=True),
        ),
        migrations.AlterField(
            model_name="historicalprofile",
            name="history_date",
            field=models.DateTimeField(db_index=True),
        ),
        migrations.AlterField(
            model_name="historicalreferee",
            name="history_date",
            field=models.DateTimeField(db_index=True),
        ),
        migrations.AlterField(
            model_name="historicalround",
            name="history_date",
            field=models.DateTimeField(db_index=True),
        ),
        migrations.AlterField(
            model_name="historicaltestimonial",
            name="history_date",
            field=models.DateTimeField(db_index=True),
        ),
        migrations.CreateModel(
            name="HistoricalSocioEconomicObjective",
            fields=[
                ("created_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("updated_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("code", models.CharField(db_index=True, max_length=6)),
                ("description", models.CharField(blank=True, max_length=150, null=True)),
                ("source", models.CharField(blank=True, max_length=255, null=True)),
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                ("history_date", models.DateTimeField(db_index=True)),
                ("history_change_reason", models.CharField(max_length=100, null=True)),
                (
                    "history_type",
                    models.CharField(
                        choices=[("+", "Created"), ("~", "Changed"), ("-", "Deleted")],
                        max_length=1,
                    ),
                ),
                (
                    "history_user",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "historical SEO",
                "verbose_name_plural": "historical SEOs",
                "db_table": "seo_history",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": ("history_date", "history_id"),
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
        migrations.CreateModel(
            name="ApplicationSeo",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True)),
                ("share", models.PositiveSmallIntegerField(blank=True, default=None, null=True)),
                (
                    "application",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="application_seos",
                        to="portal.application",
                    ),
                ),
                (
                    "code",
                    models.ForeignKey(
                        db_column="code",
                        on_delete=django.db.models.deletion.CASCADE,
                        to="portal.socioeconomicobjective",
                        verbose_name="SEO",
                    ),
                ),
            ],
            options={
                "verbose_name": "application SEO",
                "verbose_name_plural": "application SEOs",
                "db_table": "application_seo",
                "unique_together": {("application", "code")},
            },
            bases=(common.models.HelperMixin, models.Model),
        ),
        migrations.CreateModel(
            name="ApplicationKeyword",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True)),
                (
                    "application",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="portal.application"
                    ),
                ),
                (
                    "keyword",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="portal.keyword"
                    ),
                ),
            ],
            options={
                "db_table": "application_keyword",
            },
            bases=(common.models.HelperMixin, models.Model),
        ),
        migrations.CreateModel(
            name="ApplicationFor",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True, null=True)),
                ("share", models.PositiveSmallIntegerField(blank=True, default=None, null=True)),
                (
                    "application",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="application_fors",
                        to="portal.application",
                    ),
                ),
                (
                    "code",
                    models.ForeignKey(
                        db_column="code",
                        on_delete=django.db.models.deletion.CASCADE,
                        to="portal.fieldofresearch",
                        verbose_name="FoR",
                    ),
                ),
            ],
            options={
                "verbose_name": "application FOR",
                "verbose_name_plural": "application FORs",
                "db_table": "application_for",
                "unique_together": {("application", "code")},
            },
            bases=(common.models.HelperMixin, models.Model),
        ),
        migrations.AddField(
            model_name="application",
            name="fors",
            field=models.ManyToManyField(
                blank=True,
                related_name="applications",
                through="portal.ApplicationFor",
                to="portal.fieldofresearch",
                verbose_name="FoRs",
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="keywords",
            field=models.ManyToManyField(
                blank=True,
                related_name="applications",
                through="portal.ApplicationKeyword",
                to="portal.keyword",
                verbose_name="Keywords",
            ),
        ),
        migrations.AddField(
            model_name="application",
            name="seos",
            field=models.ManyToManyField(
                blank=True,
                related_name="applications",
                through="portal.ApplicationSeo",
                to="portal.socioeconomicobjective",
                verbose_name="SEOs",
            ),
        ),
    ]
