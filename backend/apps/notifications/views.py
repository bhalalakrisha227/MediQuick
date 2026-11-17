from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.views import body, handle_errors

from . import deps


class AuthedView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]


class NotificationsView(AuthedView):
    @handle_errors
    def get(self, request):
        q = request.query_params
        page = int(q["page"]) if q.get("page", "").isdigit() else 1
        return Response(deps.get_notifications().list(request.user.id, q.get("unread") == "1", page))


class UnreadCountView(AuthedView):
    @handle_errors
    def get(self, request):
        return Response(deps.get_notifications().unread_count(request.user.id))


class MarkReadView(AuthedView):
    @handle_errors
    def post(self, request, notification_id):
        return Response(deps.get_notifications().mark_read(request.user.id, notification_id))


class MarkAllReadView(AuthedView):
    @handle_errors
    def post(self, request):
        return Response(deps.get_notifications().mark_all_read(request.user.id))


class SettingsView(AuthedView):
    @handle_errors
    def get(self, request):
        return Response(deps.get_notifications().get_settings(request.user.id))

    @handle_errors
    def patch(self, request):
        return Response(deps.get_notifications().update_settings(request.user.id, body(request)))
