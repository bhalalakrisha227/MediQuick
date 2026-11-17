import functools

from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import deps
from .errors import ServiceError


def handle_errors(func):
    @functools.wraps(func)
    def wrapper(self, request, *args, **kwargs):
        try:
            return func(self, request, *args, **kwargs)
        except ServiceError as exc:
            body = {"error": {"code": exc.code, "message": exc.message}}
            if exc.fields:
                body["error"]["fields"] = exc.fields
            return Response(body, status=exc.status)

    return wrapper


def body(request) -> dict:
    return request.data if isinstance(request.data, dict) else {}


class PublicAuthView(APIView):
    """Base for register/login/refresh/logout: no auth required, rate limited, JSON only."""
    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"


class RegisterView(PublicAuthView):
    @handle_errors
    def post(self, request):
        return Response(deps.get_services().auth.register(body(request)), status=201)


class LoginView(PublicAuthView):
    @handle_errors
    def post(self, request):
        return Response(deps.get_services().auth.login(body(request)))


class RefreshView(PublicAuthView):
    @handle_errors
    def post(self, request):
        return Response(deps.get_services().auth.refresh(body(request)))


class LogoutView(PublicAuthView):
    @handle_errors
    def post(self, request):
        deps.get_services().auth.logout(body(request))
        return Response(status=204)


class MeView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    @handle_errors
    def get(self, request):
        return Response(deps.get_services().profile.get(request.user.id))

    @handle_errors
    def patch(self, request):
        return Response(deps.get_services().profile.update(request.user.id, body(request)))


class AddressListView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    @handle_errors
    def get(self, request):
        return Response({"results": deps.get_services().addresses.list(request.user.id)})

    @handle_errors
    def post(self, request):
        return Response(deps.get_services().addresses.create(request.user.id, body(request)), status=201)


class AddressDetailView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    @handle_errors
    def patch(self, request, address_id):
        return Response(deps.get_services().addresses.update(request.user.id, address_id, body(request)))

    @handle_errors
    def delete(self, request, address_id):
        deps.get_services().addresses.delete(request.user.id, address_id)
        return Response(status=204)
