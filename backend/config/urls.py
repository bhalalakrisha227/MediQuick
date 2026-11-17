from django.urls import include, path

handler404 = "common.errors.json_404"
handler500 = "common.errors.json_500"

urlpatterns = [
    path("api/v1/", include("apps.core.urls")),
    path("api/v1/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.catalogue.urls")),
    path("api/v1/", include("apps.inventory.urls")),
    path("api/v1/", include("apps.orders.urls")),
    path("api/v1/", include("apps.prescriptions.urls")),
    path("api/v1/", include("apps.notifications.urls")),
    path("api/v1/", include("apps.adminpanel.urls")),
]
