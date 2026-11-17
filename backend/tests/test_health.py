"""Health endpoint tests. MongoDB is mocked, so no Atlas connection is needed."""
from unittest import mock

from django.test import SimpleTestCase


class HealthEndpointTests(SimpleTestCase):
    def test_liveness_ok(self):
        response = self.client.get("/api/v1/health/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    @mock.patch("apps.core.views.mongo.ping", return_value=True)
    def test_db_health_ok(self, _ping):
        response = self.client.get("/api/v1/health/db/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["database"], "reachable")

    @mock.patch("apps.core.views.mongo.ping", return_value=False)
    def test_db_health_unavailable_returns_503_without_details(self, _ping):
        response = self.client.get("/api/v1/health/db/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable", "database": "unreachable"})

    def test_unknown_routes_are_not_exposed(self):
        self.assertEqual(self.client.get("/api/v1/secret/").status_code, 404)
