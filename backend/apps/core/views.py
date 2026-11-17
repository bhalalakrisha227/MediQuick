from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from common import mongo


class HealthView(APIView):
    """Liveness check: confirms the API process is running. No database access."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok", "service": "mediquick-api"})


class DatabaseHealthView(APIView):
    """Readiness check: confirms MongoDB Atlas answers a ping.

    Returns a generic message on failure; the real error is only logged.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        if mongo.ping():
            return Response({"status": "ok", "database": "reachable"})
        return Response(
            {"status": "unavailable", "database": "unreachable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
