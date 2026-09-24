from django.apps import AppConfig


class JarvisAppConfig(AppConfig):
    name = "jarvis_app"
    verbose_name = "JARVIS"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.contrib.auth import get_user_model
        from django.db.models.signals import post_save

        from .models import Profile

        def _ensure_profile(sender, instance, created, **kwargs):
            if created:
                Profile.objects.get_or_create(user=instance)

        post_save.connect(_ensure_profile, sender=get_user_model(), dispatch_uid="jarvis_profile")
