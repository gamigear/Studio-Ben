"""REST API cho agent bên ngoài: /api/v1/  (tài liệu tự sinh tại /api/v1/docs).

Xác thực: header `Authorization: Bearer lenlich_...` (tạo ở Cài đặt → API key).
"""

from datetime import date, datetime, timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import File, Form, NinjaAPI, Schema, Status
from ninja.errors import HttpError
from ninja.files import UploadedFile
from ninja.security import HttpBearer

from .models import ApiKey, Channel, MediaFile, Post, Video
from .services import ai
from .services.content import create_content


class ApiKeyAuth(HttpBearer):
    def authenticate(self, request, token):
        return ApiKey.authenticate(token)


api = NinjaAPI(
    title="Lên Lịch API",
    version="1",
    description="API cho agent: đọc kênh, đẩy video / ảnh / album kèm caption, sửa caption, xem lịch đăng.",
    auth=ApiKeyAuth(),
    urls_namespace="api",
)


class ChannelOut(Schema):
    id: int
    name: str
    platform: str
    default_format: str
    handle: str
    topic: str
    content_instructions: str
    default_hashtags: str
    post_times: str
    auto_caption: bool
    is_active: bool


class ChannelPatch(Schema):
    topic: str | None = None
    content_instructions: str | None = None
    default_hashtags: str | None = None


class MediaOut(Schema):
    id: int
    kind: str
    original_name: str
    size: int | None
    status: str


class VideoOut(Schema):
    id: int
    channel_id: int
    kind: str
    source: str
    title: str
    notes: str
    caption: str
    caption_status: str
    file_status: str
    state: str
    media: list[MediaOut]
    created_at: datetime

    @staticmethod
    def resolve_state(obj: Video) -> str:
        statuses = {p.status for p in obj.posts.all()}
        if Post.Status.POSTED in statuses:
            return "posted"
        if Post.Status.PENDING in statuses:
            return "scheduled"
        if obj.caption_status == Video.CaptionStatus.FAILED or obj.file_status == Video.FileStatus.FAILED:
            return "failed"
        return "ready" if obj.is_ready else "processing"


class VideoPatch(Schema):
    title: str | None = None
    notes: str | None = None
    caption: str | None = None


class PostOut(Schema):
    id: int
    channel_id: int
    video_id: int
    scheduled_at: datetime
    post_format: str
    caption: str
    status: str
    assignee: str | None
    posted_at: datetime | None
    post_url: str

    @staticmethod
    def resolve_assignee(obj: Post) -> str | None:
        return str(obj.assignee) if obj.assignee else None


class PostPatch(Schema):
    scheduled_at: datetime | None = None
    caption: str | None = None


# --- Kênh ---------------------------------------------------------------------


@api.get("/channels", response=list[ChannelOut], tags=["Kênh"])
def list_channels(request):
    return Channel.objects.all()


@api.get("/channels/{channel_id}", response=ChannelOut, tags=["Kênh"])
def get_channel(request, channel_id: int):
    return get_object_or_404(Channel, pk=channel_id)


@api.patch("/channels/{channel_id}", response=ChannelOut, tags=["Kênh"])
def update_channel(request, channel_id: int, payload: ChannelPatch):
    """Agent tinh chỉnh cách viết nội dung của kênh (chủ đề, hướng dẫn caption, hashtag)."""
    channel = get_object_or_404(Channel, pk=channel_id)
    for field, value in payload.dict(exclude_none=True).items():
        setattr(channel, field, value)
    channel.save()
    return channel


# --- Video --------------------------------------------------------------------


@api.get("/videos", response=list[VideoOut], tags=["Video"])
def list_videos(request, channel_id: int | None = None, limit: int = 50):
    qs = Video.objects.filter(is_archived=False).prefetch_related("posts", "media").order_by("-created_at")
    if channel_id:
        qs = qs.filter(channel_id=channel_id)
    return qs[: max(1, min(limit, 200))]


@api.post("/videos", response={201: VideoOut}, tags=["Video"])
def create_video(
    request,
    channel_id: int = Form(...),
    files: list[UploadedFile] = File(None),
    title: str = Form(""),
    notes: str = Form(""),
    caption: str = Form(""),
):
    """Đẩy một nội dung vào kho của kênh: gửi 1 video, 1 ảnh, nhiều ảnh (album), hoặc không file (bài chữ).

    Field file là `files` (lặp lại để gửi nhiều ảnh). Có `caption` thì dùng luôn; để trống thì AI viết theo
    hướng dẫn của kênh.
    """
    channel = get_object_or_404(Channel, pk=channel_id)
    files = files or []
    kinds = [MediaFile.kind_from_mime(f.content_type or "") for f in files]
    if any(k is None for k in kinds):
        raise HttpError(400, "File phải là video hoặc ảnh.")
    if len(files) > 1 and MediaFile.Kind.VIDEO in kinds:
        raise HttpError(400, "Album chỉ gồm ảnh. Gửi video thành từng bài riêng.")
    if not files and not (caption.strip() or notes.strip()):
        raise HttpError(400, "Bài chỉ có chữ cần caption hoặc notes.")
    video = create_content(channel, Video.Source.API, files, title=title, notes=notes, caption=caption)
    return Status(201, video)


@api.get("/videos/{video_id}", response=VideoOut, tags=["Video"])
def get_video(request, video_id: int):
    return get_object_or_404(Video.objects.prefetch_related("posts", "media"), pk=video_id, is_archived=False)


@api.patch("/videos/{video_id}", response=VideoOut, tags=["Video"])
def update_video(request, video_id: int, payload: VideoPatch):
    video = get_object_or_404(Video, pk=video_id, is_archived=False)
    data = payload.dict(exclude_none=True)
    caption = data.pop("caption", None)
    for field, value in data.items():
        setattr(video, field, value)
    if data:
        video.save(update_fields=list(data))
    if caption is not None:
        video.apply_caption(caption, Video.CaptionStatus.MANUAL)
    return video


@api.post("/videos/{video_id}/regenerate-caption", response=VideoOut, tags=["Video"])
def regenerate_caption(request, video_id: int):
    """Cho AI viết lại caption ngay (dùng hướng dẫn hiện tại của kênh)."""
    video = get_object_or_404(Video.objects.select_related("channel"), pk=video_id, is_archived=False)
    try:
        caption = ai.generate_caption(video)
    except ai.AIError as exc:
        raise HttpError(502, str(exc)) from exc
    video.apply_caption(caption, Video.CaptionStatus.DONE)
    return video


# --- Lịch đăng ----------------------------------------------------------------


@api.get("/posts", response=list[PostOut], tags=["Lịch đăng"])
def list_posts(request, day: date | None = None, channel_id: int | None = None, status: str | None = None):
    """Bài đăng trong một ngày (mặc định hôm nay, theo giờ Việt Nam)."""
    day = day or timezone.localdate()
    start = timezone.make_aware(datetime.combine(day, datetime.min.time()))
    qs = Post.objects.filter(scheduled_at__gte=start, scheduled_at__lt=start + timedelta(days=1)).select_related(
        "assignee"
    )
    if channel_id:
        qs = qs.filter(channel_id=channel_id)
    if status:
        qs = qs.filter(status=status)
    return qs


@api.patch("/posts/{post_id}", response=PostOut, tags=["Lịch đăng"])
def update_post(request, post_id: int, payload: PostPatch):
    post = get_object_or_404(Post, pk=post_id)
    if post.status != Post.Status.PENDING:
        raise HttpError(409, "Chỉ sửa được bài đang chờ đăng.")
    data = payload.dict(exclude_none=True)
    for field, value in data.items():
        setattr(post, field, value)
    if data:
        post.save(update_fields=list(data))
    return post
