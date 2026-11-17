from django.apps import AppConfig


class AdminPanelConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.adminpanel"
    label = "mq_adminpanel"       # do not clash with Django's own "admin" label (we do not use django.contrib.admin)
