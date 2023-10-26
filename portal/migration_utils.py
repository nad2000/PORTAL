from .models import QUALIFICATION_LEVEL

def disable_constraints(apps, schema_editor):
    engine = schema_editor.connection.settings_dict.get("ENGINE").split(".")[-1]
    if engine == "sqlite3":
        schema_editor.execute("PRAGMA foreign_keys = OFF;")
    # else:
    #     schema_editor.execute("SET FOREIGN_KEY_CHECKS=0;")


def enable_constraints(apps, schema_editor):
    engine = schema_editor.connection.settings_dict.get("ENGINE").split(".")[-1]
    if engine == "sqlite3":
        schema_editor.execute("PRAGMA foreign_keys = ON;")
    # else:
    #     schema_editor.execute("SET FOREIGN_KEY_CHECKS=1;")


def add_education_level_data(apps, schema_editor):
    from django.utils.translation import activate, gettext
    
    def get_name(value, language="en"):
        activate(language)
        return gettext(value)

    
    EducationLevel = apps.get_model("portal", "EducationLevel")
    db_alias = schema_editor.connection.alias

    EducationLevel.objects.using(db_alias).bulk_create(
        [
            EducationLevel(
                code=c, 
                name=get_name(v),
                name_en=get_name(v),
                name_mi=get_name(v, "mi")
            ) for (c, v) in QUALIFICATION_LEVEL
        ],
        update_conflicts=True,
        update_fields=["name", "name_en", "name_mi"],
        unique_fields=["code"]
    )


def dummy(*args, **kwargs):
    pass
