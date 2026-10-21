import hashlib
import secrets
from datetime import time

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .crypto import EncryptedTextField


class User(AbstractUser):
    class Role(models.TextChoices):
        MANAGER = "manager", "Quản lý"
        STAFF = "staff", "Nhân viên"

    role = models.CharField("vai trò", max_length=20, choices=Role.choices, default=Role.STAFF)

    @property
    def is_manager(self) -> bool:
        return self.is_superuser or self.role == self.Role.MANAGER

    def __str__(self):
        return self.get_full_name() or self.username


def parse_post_times(value: str) -> list[time]:
    """ "08:00, 12:30,19:00" -> [time(8,0), time(12,30), time(19,0)] (đã sắp xếp, bỏ trùng)."""
    result = set()
    for part in value.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            hour, minute = part.split(":")
            result.add(time(int(hour), int(minute)))
        except ValueError as exc:
            raise ValidationError(f"Giờ đăng không hợp lệ: '{part}'. Dùng dạng HH:MM, ví dụ 08:00, 19:30.") from exc
    return sorted(result)


class AIProvider(models.Model):
    """Một dịch vụ AI tương thích OpenAI Chat Completions (OpenAI, OpenRouter, DeepSeek, Gemini...)."""

    name = models.CharField("tên", max_length=100)
    base_url = models.URLField("API base URL", default="https://api.openai.com/v1")
    api_key = EncryptedTextField("API key")
    model = models.CharField(
        "model", max_length=100, help_text="Ví dụ: gpt-4.1-mini. Xem danh sách model trong tài khoản của bạn."
    )
    temperature = models.FloatField(
        "temperature", null=True, blank=True, help_text="Để trống nếu model không hỗ trợ (các model suy luận)."
    )
    system_prompt = models.TextField(
        "hướng dẫn chung cho AI",
        blank=True,
        help_text="Áp dụng cho mọi kênh dùng dịch vụ này. Để trống sẽ dùng hướng dẫn mặc định.",
    )
    is_default = models.BooleanField("mặc định", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "dịch vụ AI"
        verbose_name_plural = "dịch vụ AI"
        ordering = ["-is_default", "name"]

    def __str__(self):
        return f"{self.name} ({self.model})"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            AIProvider.objects.exclude(pk=self.pk).update(is_default=False)

    @property
    def masked_key(self) -> str:
        key = self.api_key or ""
        return f"{key[:3]}…{key[-4:]}" if len(key) > 8 else "••••"


class Channel(models.Model):
    class Platform(models.TextChoices):
        TIKTOK = "tiktok", "TikTok"
        FACEBOOK = "facebook", "Facebook"
        INSTAGRAM = "instagram", "Instagram"
        YOUTUBE = "youtube", "YouTube"

    name = models.CharField("tên kênh", max_length=150)
    platform = models.CharField("nền tảng", max_length=20, choices=Platform.choices, default=Platform.TIKTOK)
    handle = models.CharField("tài khoản (@)", max_length=150, blank=True)
    topic = models.TextField("chủ đề", blank=True)
    content_instructions = models.TextField(
        "hướng dẫn viết caption",
        blank=True,
        help_text="Giọng văn, độ dài, cách mở đầu, lời kêu gọi, ví dụ caption mẫu... AI sẽ làm theo.",
    )
    default_hashtags = models.CharField("hashtag mặc định", max_length=500, blank=True)
    post_times = models.CharField(
        "giờ đăng mỗi ngày", max_length=200, blank=True, help_text="Cách nhau bằng dấu phẩy, ví dụ: 08:00, 12:00, 19:30"
    )
    auto_caption = models.BooleanField("AI tự viết caption", default=True)
    ai_provider = models.ForeignKey(
        AIProvider,
        verbose_name="dịch vụ AI",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Để trống để dùng dịch vụ AI mặc định.",
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="nhân viên phụ trách",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="channels",
    )
    device = models.CharField("điện thoại", max_length=100, blank=True, help_text="Máy đang đăng nhập tài khoản này.")
    drive_folder_id = models.CharField(
        "ID thư mục Google Drive",
        max_length=200,
        blank=True,
        help_text="Dán link thư mục Drive hoặc chỉ phần ID (drive.google.com/drive/folders/<ID>).",
    )
    drive_synced_at = models.DateTimeField(null=True, blank=True)
    drive_error = models.TextField(blank=True)
    is_active = models.BooleanField("đang hoạt động", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "kênh"
        verbose_name_plural = "kênh"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_platform_display()})"

    def clean(self):
        parse_post_times(self.post_times)
        if self.drive_folder_id and "/" in self.drive_folder_id:
            self.drive_folder_id = self.drive_folder_id.rstrip("/").split("/")[-1].split("?")[0]

    def get_post_times(self) -> list[time]:
        try:
            return parse_post_times(self.post_times)
        except ValidationError:
            return []

    def get_ai_provider(self):
        return self.ai_provider or AIProvider.objects.filter(is_default=True).first()


def video_upload_to(instance, filename):
    return f"videos/{instance.channel_id}/{timezone.now():%Y%m}/{filename}"


class Video(models.Model):
    class Source(models.TextChoices):
        DRIVE = "drive", "Google Drive"
        UPLOAD = "upload", "Tải lên"
        API = "api", "API / agent"

    class CaptionStatus(models.TextChoices):
        PENDING = "pending", "Chờ AI viết"
        DONE = "done", "AI đã viết"
        MANUAL = "manual", "Viết tay"
        FAILED = "failed", "AI lỗi"

    class FileStatus(models.TextChoices):
        PENDING = "pending", "Chờ tải về"
        READY = "ready", "Có sẵn"
        FAILED = "failed", "Tải lỗi"
        REMOVED = "removed", "Đã dọn"

    READY_CAPTION_STATUSES = (CaptionStatus.DONE, CaptionStatus.MANUAL)

    channel = models.ForeignKey(Channel, verbose_name="kênh", on_delete=models.CASCADE, related_name="videos")
    source = models.CharField("nguồn", max_length=20, choices=Source.choices, default=Source.UPLOAD)
    title = models.CharField("tiêu đề", max_length=300)
    notes = models.TextField("mô tả / kịch bản", blank=True, help_text="Thông tin để AI viết caption.")
    file = models.FileField("file video", upload_to=video_upload_to, blank=True, max_length=500)
    file_status = models.CharField(max_length=20, choices=FileStatus.choices, default=FileStatus.PENDING)
    file_error = models.TextField(blank=True)
    drive_file_id = models.CharField(max_length=200, blank=True, db_index=True)
    original_name = models.CharField("tên file gốc", max_length=300, blank=True)
    size = models.BigIntegerField(null=True, blank=True)
    caption = models.TextField("caption", blank=True)
    caption_status = models.CharField(max_length=20, choices=CaptionStatus.choices, default=CaptionStatus.PENDING)
    caption_attempts = models.PositiveSmallIntegerField(default=0)
    caption_error = models.TextField(blank=True)
    # Video Drive bị "xóa" chỉ được lưu trữ, để lần quét sau không thêm lại.
    is_archived = models.BooleanField("đã lưu trữ", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "video"
        verbose_name_plural = "video"
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["channel", "drive_file_id"],
                condition=~models.Q(drive_file_id=""),
                name="unique_drive_file_per_channel",
            )
        ]

    def __str__(self):
        return self.title

    @property
    def is_ready(self) -> bool:
        return self.file_status == self.FileStatus.READY and self.caption_status in self.READY_CAPTION_STATUSES

    def apply_caption(self, text: str, status: str) -> None:
        """Lưu caption và cập nhật luôn các bài đang chờ đăng của video này."""
        self.caption = text
        self.caption_status = status
        self.caption_error = ""
        self.save(update_fields=["caption", "caption_status", "caption_error"])
        self.posts.filter(status=Post.Status.PENDING).update(caption=text)

    @classmethod
    def schedulable(cls):
        """Video đã có file + caption và chưa từng được xếp lịch."""
        return cls.objects.filter(
            file_status=cls.FileStatus.READY,
            caption_status__in=cls.READY_CAPTION_STATUSES,
            posts__isnull=True,
            is_archived=False,
        )


class Post(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Chờ đăng"
        POSTED = "posted", "Đã đăng"
        SKIPPED = "skipped", "Bỏ qua"

    channel = models.ForeignKey(Channel, verbose_name="kênh", on_delete=models.CASCADE, related_name="posts")
    video = models.ForeignKey(Video, verbose_name="video", on_delete=models.CASCADE, related_name="posts")
    scheduled_at = models.DateTimeField("giờ đăng", db_index=True)
    caption = models.TextField("caption", blank=True)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="người đăng",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_posts",
    )
    status = models.CharField("trạng thái", max_length=20, choices=Status.choices, default=Status.PENDING)
    posted_at = models.DateTimeField("đăng lúc", null=True, blank=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    post_url = models.URLField("link bài đăng", blank=True, max_length=500)
    note = models.TextField("ghi chú", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "bài đăng"
        verbose_name_plural = "bài đăng"
        ordering = ["scheduled_at", "id"]

    def __str__(self):
        return f"{self.channel.name} @ {timezone.localtime(self.scheduled_at):%d/%m %H:%M}"

    @property
    def is_overdue(self) -> bool:
        if self.status != self.Status.PENDING:
            return False
        grace = timezone.timedelta(minutes=settings.OVERDUE_GRACE_MINUTES)
        return self.scheduled_at + grace < timezone.now()

    @property
    def is_due(self) -> bool:
        return self.status == self.Status.PENDING and self.scheduled_at <= timezone.now()

    def can_handle(self, user) -> bool:
        return user.is_manager or self.assignee_id == user.id


API_KEY_PREFIX = "lenlich_"


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class ApiKey(models.Model):
    """Khóa cho agent bên ngoài gọi REST API. Chỉ lưu hash; khóa gốc hiện một lần khi tạo."""

    name = models.CharField("tên", max_length=100)
    prefix = models.CharField(max_length=20, editable=False)
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "API key"
        verbose_name_plural = "API key"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.prefix}…)"

    @classmethod
    def issue(cls, name: str, user=None) -> tuple["ApiKey", str]:
        raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
        key = cls.objects.create(
            name=name, prefix=raw[: len(API_KEY_PREFIX) + 6], key_hash=hash_api_key(raw), created_by=user
        )
        return key, raw

    @classmethod
    def authenticate(cls, raw: str):
        if not raw or not raw.startswith(API_KEY_PREFIX):
            return None
        key = cls.objects.filter(key_hash=hash_api_key(raw), is_active=True).first()
        if key:
            cls.objects.filter(pk=key.pk).update(last_used_at=timezone.now())
        return key
