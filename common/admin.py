


class StaffPermsMixin:
    def get_model_perms(self, request):
        if (u := request.user) and u.is_admin:
            return {"add": True, "change": True, "delete": True, "view": True}
        return super().get_model_perms(request)

    def has_add_permission(self, request, *args):
        if (u := request.user) and u.is_admin:
            return True
        return super().has_add_permission(request, *args)

    def has_change_permission(self, request, obj=None):
        if (u := request.user) and u.is_admin:
            return True
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if (u := request.user) and u.is_admin:
            return True
        return super().has_delete_permission(request, obj)

    def has_view_permission(self, request, obj=None):
        if (u := request.user) and u.is_admin:
            return True
        return super().has_view_permission(request, obj)

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_admin


class StaffViewPermsMixin:

    def get_model_perms(self, request):
        if (u := request.user) and not u.is_superuser and (u.is_staff or u.is_site_staff):
            return {"add": False, "change": False, "delete": False, "view": True}
        return super().get_model_perms(request)

    def has_add_permission(self, request, *args):
        if (u := request.user) and not u.is_superuser and (u.is_staff or u.is_site_staff):
            return False
        return super().has_add_permission(request, *args)

    def has_change_permission(self, request, obj=None):
        if (u := request.user) and not u.is_superuser and (u.is_staff or u.is_site_staff):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if (u := request.user) and not u.is_superuser and (u.is_staff or u.is_site_staff):
            return False
        return super().has_delete_permission(request, obj)

    def has_view_permission(self, request, obj=None):
        if (u := request.user) and u.is_admin:
            return True
        return super().has_view_permission(request, obj)

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_admin



# vim:set ft=python.django:
