from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import AIProvider, ApiKey, Channel, MediaFile, Post, User, Video

admin.site.site_header = "Lên Lịch – Quản trị"
admin.site.site_title = "Lên Lịch"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "first_name", "last_name", "role", "is_active")
    list_filter = ("role", "is_active")
    fieldsets = BaseUserAdmin.fieldsets + (("Lên Lịch", {"fields": ("role",)}),)
    add_fieldsets = BaseUserAdmin.add_fieldsets + (("Lên Lịch", {"fields": ("role", "first_name", "last_name")}),)


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ("name", "platform", "default_format", "handle", "assignee", "device", "post_times", "is_active")
    list_filter = ("platform", "is_active", "assignee")
    search_fields = ("name", "handle")


class MediaFileInline(admin.TabularInline):
    model = MediaFile
    extra = 0
    fields = ("position", "kind", "original_name", "file", "status", "drive_file_id")


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ("title", "channel", "kind", "source", "file_status", "caption_status", "created_at")
    list_filter = ("channel", "kind", "source", "file_status", "caption_status")
    inlines = [MediaFileInline]
    search_fields = ("title", "caption")


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ("channel", "scheduled_at", "post_format", "assignee", "status", "posted_at")
    list_filter = ("status", "channel", "assignee")
    date_hierarchy = "scheduled_at"


@admin.register(AIProvider)
class AIProviderAdmin(admin.ModelAdmin):
    list_display = ("name", "model", "base_url", "is_default")
    exclude = ("api_key",)


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ("name", "prefix", "is_active", "last_used_at", "created_at")
    readonly_fields = ("prefix", "created_by", "last_used_at")
