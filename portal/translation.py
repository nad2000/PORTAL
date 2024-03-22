import simple_history
from modeltranslation.translator import TranslationOptions, register

from . import models


@register(models.DocumentType)
class DocumentTypeTranslationOptions(TranslationOptions):
    fields = ("name",)


@register(models.RequiredDocument)
class RequiredDocumentTranslationOptions(TranslationOptions):
    fields = ("title",)


@register(models.RequiredContractDocument)
class RequiredContractDocumentTranslationOptions(TranslationOptions):
    fields = ("title",)


@register(models.Fund)
class FundTranslationOptions(TranslationOptions):
    fields = ("name", "description",)


simple_history.register(models.Fund, inherit=True, table_name="fund_history")


@register(models.Title)
class TitleTranslationOptions(TranslationOptions):
    fields = ("name",)


@register(models.Scheme)
class SchemeTranslationOptions(TranslationOptions):
    fields = (
        "title",
        # "description",
    )


@register(models.Category)
class CategoryTranslationOptions(TranslationOptions):
    fields = ("description",)


@register(models.Round)
class RoundTranslationOptions(TranslationOptions):
    fields = (
        "title",
        "description",
        "tac",
    )


simple_history.register(models.Round, inherit=True, table_name="round_history")


@register(models.Application)
class ApplicationTranslationOptions(TranslationOptions):
    fields = (
        "application_title",
        "summary",
    )


simple_history.register(
    models.Application,
    inherit=True,
    table_name="application_history",
    bases=[models.ApplicationMixin, models.Model],
)


@register(models.Criterion)
class CriterionTranslationOptions(TranslationOptions):
    fields = ("definition",)


simple_history.register(models.Criterion, inherit=True, table_name="criterion_history")


# @register(models.SchemeApplication)
# class SchemeApplicationTranslationOptions(TranslationOptions):
#     fields = (
#         "title",
#         "description",
#     )


@register(models.ProtectionPattern)
class ProtectionPatternOptions(TranslationOptions):
    fields = (
        "description",
        "comment",
    )


@register(models.ProtectionPatternPerson)
class ProtectionPatternPersonOptions(TranslationOptions):
    fields = (
        "description",
        "comment",
    )


@register(models.RoleType)
class RoleTypeOptions(TranslationOptions):
    fields = (
        "name",
        "description",
    )


@register(models.EducationLevel)
class EducationLevelOptions(TranslationOptions):
    fields = ("name",)


# vim:set ft=python.django:
