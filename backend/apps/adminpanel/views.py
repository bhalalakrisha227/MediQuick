from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import has_role
from apps.accounts.views import body, handle_errors

from . import deps, rules


class AdminView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]


class OverviewView(AdminView):
    permission_classes = [has_role(*rules.ANALYTICS_ROLES)]

    @handle_errors
    def get(self, request):
        return Response(deps.get_services().analytics.operations(request.user.role))


class SalesView(AdminView):
    permission_classes = [has_role(*rules.ANALYTICS_ROLES)]

    @handle_errors
    def get(self, request):
        return Response(deps.get_services().analytics.sales(request.user.role, dict(request.query_params.items())))


class AttentionView(AdminView):
    permission_classes = [has_role(*rules.ATTENTION_ROLES)]

    @handle_errors
    def get(self, request):
        return Response(deps.get_services().attention.list(request.user.role))


class AttentionResolveView(AdminView):
    permission_classes = [has_role(*rules.ATTENTION_ROLES)]

    @handle_errors
    def post(self, request, order_id):
        data = body(request)
        return Response(deps.get_services().attention.resolve(request.user.id, request.user.role, order_id, data.get("flag"), data.get("note")))


class UsersView(AdminView):
    permission_classes = [has_role(*rules.USER_ADMIN_ROLES)]

    @handle_errors
    def get(self, request):
        return Response(deps.get_services().users.list(request.user.role, dict(request.query_params.items())))


class UserActiveView(AdminView):
    permission_classes = [has_role(*rules.USER_ADMIN_ROLES)]

    @handle_errors
    def post(self, request, user_id):
        return Response(deps.get_services().users.set_active(request.user.id, request.user.role, user_id, body(request)))


class AuditView(AdminView):
    permission_classes = [has_role(*rules.USER_ADMIN_ROLES)]

    @handle_errors
    def get(self, request):
        page = request.query_params.get("page", "")
        return Response(deps.get_services().audit.recent(request.user.role, int(page) if page.isdigit() else 1))
