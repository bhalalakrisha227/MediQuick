from django.urls import path

from . import views

urlpatterns = [
    path("notifications/", views.NotificationsView.as_view(), name="notifications"),
    path("notifications/unread-count/", views.UnreadCountView.as_view(), name="notifications-unread"),
    path("notifications/read-all/", views.MarkAllReadView.as_view(), name="notifications-read-all"),
    path("notifications/settings/", views.SettingsView.as_view(), name="notifications-settings"),
    path("notifications/<str:notification_id>/read/", views.MarkReadView.as_view(), name="notification-read"),
]
