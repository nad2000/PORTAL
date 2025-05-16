from rest_framework import routers
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin, UpdateModelMixin
from rest_framework.viewsets import GenericViewSet

from . import models, serializers

# class GeneralViewSet(ModelViewSet):
#     def get_queryset(self):
#         model = self.kwargs.get("model")
#         return model.objects.all()

#     def get_serializer_class(self):
#         klass = serializers.GeneralSerializer
#         klass.Meta.model = self.kwargs.get("model")
#         return klass


class AffiliationViewSet(RetrieveModelMixin, ListModelMixin, UpdateModelMixin, GenericViewSet):
    serializer_class = serializers.AffiliationSerializer
    queryset = models.Affiliation.objects.all()
    lookup_field = "person"

    def get_queryset(self, *args, **kwargs):
        if self.request.user.person:
            return self.queryset.filter(person=self.request.user.person)
        return models.Affiliation.objects.none()


class OrganisationViewSet(RetrieveModelMixin, ListModelMixin, UpdateModelMixin, GenericViewSet):
    serializer_class = serializers.OrganisationSerializer
    queryset = models.Organisation.objects.all()
    lookup_field = "name"


router = routers.DefaultRouter()
router.register("affiliations", AffiliationViewSet)
router.register("organisations", OrganisationViewSet)

# vim:set ft=python.django:
