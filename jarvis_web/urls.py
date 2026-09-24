from django.contrib import admin
from django.urls import path

from jarvis_app import views

urlpatterns = [
    # Seiten
    path("", views.index, name="index"),
    path("login/", views.login_view, name="login"),
    path("setup/", views.setup_view, name="setup"),
    path("logout/", views.logout_view, name="logout"),
    path("settings/", views.settings_view, name="settings"),
    path("admin-panel/", views.admin_panel, name="admin_panel"),
    path("django-admin/", admin.site.urls),
    path("health", views.health),
    path("files/<path:name>", views.file_download, name="file_download"),

    # Chat & Dateien
    path("api/chat", views.api_chat),
    path("api/reset", views.api_reset),
    path("api/history", views.api_history),
    path("api/upload", views.api_upload),
    path("api/files", views.api_files),
    path("api/files/delete", views.api_file_delete),

    # Status, Benachrichtigungen, Erinnerungen, Wecker, Profil
    path("api/status", views.api_status),
    path("api/notifications", views.api_notifications),
    path("api/reminders", views.api_reminders),
    path("api/alarms", views.api_alarms),
    path("api/profile", views.api_profile),
    path("api/autopilot", views.api_autopilot),
    path("api/hermes/status", views.api_hermes_status),

    # Konfiguration
    path("api/config", views.api_config),
    path("api/keys", views.api_keys),
    path("api/memory", views.api_memory),

    # Auth (JSON, kompatibel)
    path("api/auth/login", views.api_auth_login),
    path("api/auth/register", views.api_auth_register),
    path("api/auth/me", views.api_auth_me),

    # Admin
    path("api/admin/licenses", views.api_admin_licenses),
    path("api/admin/licenses/<str:key>", views.api_admin_license_revoke),
    path("api/admin/users", views.api_admin_users),
    path("api/admin/users/<int:user_id>", views.api_admin_user),
    path("api/admin/state", views.api_admin_state),

    # Live-Sync vom Desktop-JARVIS
    path("api/push", views.api_push),
    path("api/sync-logs", views.api_sync_logs),

    # Autoupdate (gleiche URLs wie zuvor)
    path("api/autoupdate/apps", views.au_apps),
    path("api/autoupdate/apps/<slug:slug>", views.au_app_delete),
    path("api/autoupdate/versions/<slug:slug>", views.au_versions),
    path("api/autoupdate/check/<slug:slug>", views.au_check),
]
