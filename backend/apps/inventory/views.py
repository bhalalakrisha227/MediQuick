from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import roles
from apps.accounts.permissions import has_role
from apps.accounts.views import body, handle_errors

from . import deps

WRITERS = has_role(roles.INVENTORY_STAFF, roles.PHARMACY_MANAGER, roles.ADMIN)
READERS = has_role(roles.INVENTORY_STAFF, roles.PHARMACY_MANAGER, roles.ADMIN, roles.PHARMACIST)


def actor(request) -> dict:
    return {"id": request.user.id, "role": request.user.role}


class BatchListCreateView(APIView):
    parser_classes = [JSONParser]

    def get_permissions(self):
        return [(READERS if self.request.method == "GET" else WRITERS)()]

    @handle_errors
    def get(self, request):
        return Response(deps.get_service().list_batches(request.query_params.dict()))

    @handle_errors
    def post(self, request):
        return Response(deps.get_service().receive(actor(request), body(request)), status=201)


class BatchMovementsView(APIView):
    permission_classes = [READERS]

    @handle_errors
    def get(self, request, batch_id):
        return Response({"results": deps.get_service().list_movements(batch_id)})


class BatchAdjustView(APIView):
    permission_classes = [WRITERS]
    parser_classes = [JSONParser]

    @handle_errors
    def post(self, request, batch_id):
        return Response(deps.get_service().adjust(actor(request), batch_id, body(request)))


class BatchStatusView(APIView):
    permission_classes = [WRITERS]
    parser_classes = [JSONParser]

    @handle_errors
    def post(self, request, batch_id):
        return Response(deps.get_service().set_status(actor(request), batch_id, body(request)))


class OverviewView(APIView):
    permission_classes = [READERS]

    @handle_errors
    def get(self, request):
        return Response(deps.get_service().overview())
