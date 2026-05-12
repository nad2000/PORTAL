from rest_framework import serializers

from . import models


class AffiliationSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Affiliation
        fields = "__all__"
        # fields = ["username", "email", "name", "url"]

        # extra_kwargs = {"url": {"view_name": "api:user-detail", "lookup_field": "username"}}


class OrganisationSerializer(serializers.ModelSerializer):
    class Meta:
        model = models.Organisation
        fields = "__all__"
        # fields = ["username", "email", "name", "url"]


class GeneralSerializer(serializers.ModelSerializer):
    class Meta:
        model = None
        fields = "__all__"


# vim:set ft=python.django:
