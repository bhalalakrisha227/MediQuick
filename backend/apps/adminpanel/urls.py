from django.urls import path

from . import views

urlpatterns = [
    path("admin/overview/", views.OverviewView.as_view(), name="admin-overview"),
    path("admin/sales/", views.SalesView.as_view(), name="admin-sales"),
    path("admin/attention/", views.AttentionView.as_view(), name="admin-attention"),
    path("admin/attention/<str:order_id>/resolve/", views.AttentionResolveView.as_view(), name="admin-attention-resolve"),
    path("admin/users/", views.UsersView.as_view(), name="admin-users"),
    path("admin/users/<str:user_id>/active/", views.UserActiveView.as_view(), name="admin-user-active"),
    path("admin/audit/", views.AuditView.as_view(), name="admin-audit"),
]
