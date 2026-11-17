from django.urls import path

from . import views

urlpatterns = [
    path("inventory/overview/", views.OverviewView.as_view(), name="inventory-overview"),
    path("inventory/batches/", views.BatchListCreateView.as_view(), name="inventory-batches"),
    path("inventory/batches/<str:batch_id>/movements/", views.BatchMovementsView.as_view(), name="inventory-movements"),
    path("inventory/batches/<str:batch_id>/adjust/", views.BatchAdjustView.as_view(), name="inventory-adjust"),
    path("inventory/batches/<str:batch_id>/status/", views.BatchStatusView.as_view(), name="inventory-status"),
]
