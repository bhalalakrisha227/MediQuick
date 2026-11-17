from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import roles
from apps.accounts.permissions import has_role
from apps.accounts.views import body, handle_errors

from . import deps

MANAGERS = has_role(roles.PHARMACY_MANAGER, roles.ADMIN)


class CategoryListView(APIView):
    """Public: anyone may browse the catalogue."""
    authentication_classes = []
    permission_classes = [AllowAny]

    @handle_errors
    def get(self, request):
        return Response({"results": deps.get_service().list_categories()})


class ProductListView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @handle_errors
    def get(self, request):
        return Response(deps.get_service().list_products(request.query_params.dict()))


class ProductDetailView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @handle_errors
    def get(self, request, slug):
        return Response(deps.get_service().get_product(slug))


class ManageCategoryCreateView(APIView):
    permission_classes = [MANAGERS]
    parser_classes = [JSONParser]

    @handle_errors
    def post(self, request):
        return Response(deps.get_service().create_category(body(request)), status=201)


class ManageProductCreateView(APIView):
    permission_classes = [MANAGERS]
    parser_classes = [JSONParser]

    @handle_errors
    def post(self, request):
        return Response(deps.get_service().create_product(body(request)), status=201)


class ManageProductDetailView(APIView):
    permission_classes = [MANAGERS]
    parser_classes = [JSONParser]

    @handle_errors
    def patch(self, request, product_id):
        return Response(deps.get_service().update_product(product_id, body(request)))

    @handle_errors
    def delete(self, request, product_id):
        deps.get_service().deactivate_product(product_id)  # soft delete: keeps order history intact
        return Response(status=204)
