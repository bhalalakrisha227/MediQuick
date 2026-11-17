"""Backend role checks. Usage: permission_classes = [has_role(roles.PHARMACIST, roles.ADMIN)]"""
from rest_framework.permissions import BasePermission


def has_role(*allowed: str):
    class _HasRole(BasePermission):
        message = "You do not have permission to perform this action."

        def has_permission(self, request, view):
            user = request.user
            return bool(user and getattr(user, "is_authenticated", False) and user.role in allowed)

    _HasRole.__name__ = "HasRole_" + "_".join(allowed)
    return _HasRole
