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


def add_title_data(apps, schema_editor):
    """
    Add to the migrations:
    migrations.RunPython(portal.models.add_title_data, lambda *args, **kwargs: None),
    """
    Title = apps.get_model("portal", "Title")
    db_alias = schema_editor.connection.alias
    Title.objects.using(db_alias).bulk_create(
        [
            Title(code="MR", name="Mr", name_en="Mr"),
            Title(code="MRS", name="Mrs", name_en="Mrs"),
            Title(code="MS", name="Ms", name_en="Ms"),
            Title(code="DR", name="Dr", name_en="Dr"),
            Title(code="PROF", name="Prof", name_en="Prof"),
        ],
        update_conflicts=True,
        update_fields=["name", "name_en"],
        unique_fields=["code"],
    )


def add_role_type_data(apps, schema_editor):
    """
    Add to the migrations:
    from portal import migration_utils
    migrations.RunPython(migration_utils.add_role_type_data, lambda *args, **kwargs: None),
    """
    RoleType = apps.get_model("portal", "RoleType")
    db_alias = schema_editor.connection.alias
    RoleType.objects.using(db_alias).bulk_create(
        [
            RoleType(
                code="CR",
                name="Coordinator",
                description=None,
                name_en="Coordinator",
                description_en=None,
            ),
            RoleType(
                code="AI",
                name="Associate investigator",
                description=None,
                name_en="Associate investigator",
                description_en=None,
            ),
            RoleType(
                code="MT", name="Mentor", description=None, name_en="Mentor", description_en=None
            ),
            RoleType(
                code="OT", name="Other", description=None, name_en="Other", description_en=None
            ),
            RoleType(
                code="RA",
                name="Research assistant",
                description=None,
                name_en="Research assistant",
                description_en=None,
            ),
            RoleType(
                code="SC",
                name="Subcontractor",
                description=None,
                name_en="Subcontractor",
                description_en=None,
            ),
            RoleType(
                code="AC",
                name="Added collaborator",
                description="For collaborators added during the course of the contract (not part of original proposal)",
                name_en="Added collaborator",
                description_en=(
                    "For collaborators added during the course of the contract (not part of original proposal)"
                ),
            ),
            RoleType(
                code="CC",
                name="Cost Chair",
                description=None,
                name_en="Cost Chair",
                description_en=None,
            ),
            RoleType(
                code="CO",
                name="Collaborator",
                description="Collaborator which is part of original application",
                name_en="Collaborator",
                description_en="Collaborator which is part of original application",
            ),
            RoleType(
                code="DE",
                name="Delegate",
                description=None,
                name_en="Delegate",
                description_en=None,
            ),
            RoleType(
                code="NP",
                name="New Zealand PI",
                description="For New Zealand PI, if contract PI is an internation person",
                name_en="New Zealand PI",
                description_en="For New Zealand PI, if contract PI is an internation person",
            ),
            RoleType(
                code="PD", name="Postdoc", description=None, name_en="Postdoc", description_en=None
            ),
            RoleType(
                code="PG",
                name="Postgraduate Student",
                description=None,
                name_en="Postgraduate Student",
                description_en=None,
            ),
            RoleType(
                code="PI",
                name="Principal Investigator",
                description=None,
                name_en="Principal Investigator",
                description_en=None,
            ),
            RoleType(
                code="SP", name="Sponsor", description=None, name_en="Sponsor", description_en=None
            ),
            RoleType(
                code="SU",
                name="Supervisor",
                description=None,
                name_en="Supervisor",
                description_en=None,
            ),
            RoleType(
                code="WP",
                name="Workshop Participant",
                description=None,
                name_en="Workshop Participant",
                description_en=None,
            ),
        ],
        update_conflicts=True,
        update_fields=["name", "name_en", "description", "description_en"],
        unique_fields=["code"],
    )


def add_qualification_level_data(apps, schema_editor):
    from django.utils.translation import activate, gettext

    def get_name(value, language="en"):
        activate(language)
        return gettext(value)

    QualificationLevel = apps.get_model("portal", "QualificationLevel")
    db_alias = schema_editor.connection.alias

    QualificationLevel.objects.using(db_alias).bulk_create(
        [
            QualificationLevel(id=id, name_en=get_name(v), name=v, name_mi=get_name(v, "mi"))
            for (id, v) in QUALIFICATION_LEVEL
        ],
        update_conflicts=True,
        update_fields=["name", "name_en", "name_mi"],
        unique_fields=["id"],
    )


def dummy(*args, **kwargs):
    pass
