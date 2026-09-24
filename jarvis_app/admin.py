from django.contrib import admin

from .models import (
    Alarm, ChatMessage, JobState, LicenseKey, Notification, Profile, Reminder,
    StateFile, UpdateApp, UpdateVersion,
)


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "full_access", "wake_word_mode", "hydration_reminder")
    list_editable = ("full_access",)


@admin.register(LicenseKey)
class LicenseKeyAdmin(admin.ModelAdmin):
    list_display = ("key", "label", "uses", "max_uses", "active", "created_at")


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "source", "created_at", "short")
    list_filter = ("role", "source", "user")

    def short(self, obj):
        return obj.text[:80]


@admin.register(StateFile)
class StateFileAdmin(admin.ModelAdmin):
    list_display = ("path", "sha1", "updated_at")
    exclude = ("content",)


class UpdateVersionInline(admin.TabularInline):
    model = UpdateVersion
    extra = 0


@admin.register(UpdateApp)
class UpdateAppAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    inlines = [UpdateVersionInline]


admin.site.register([Notification, Reminder, Alarm, JobState])
