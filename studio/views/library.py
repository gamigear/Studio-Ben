from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..forms import ChannelForm, VideoEditForm, VideoUploadForm
from ..models import Channel, Post, Video
from ..services import ai, drive
from .common import manager_required, serve_video

# --- Kênh -------------------------------------------------------------------


@manager_required
def channel_list(request):
    channels = Channel.objects.select_related("assignee").annotate(
        ready=Count(
            "videos",
            filter=Q(
                videos__file_status=Video.FileStatus.READY,
                videos__caption_status__in=Video.READY_CAPTION_STATUSES,
                videos__posts__isnull=True,
                videos__is_archived=False,
            ),
            distinct=True,
        )
    )
    return render(
        request,
        "studio/channel_list.html",
        {"channels": channels, "drive_email": drive.service_account_email()},
    )


@manager_required
def channel_form(request, pk=None):
    channel = get_object_or_404(Channel, pk=pk) if pk else None
    form = ChannelForm(request.POST or None, instance=channel)
    if request.method == "POST" and form.is_valid():
        channel = form.save()
        messages.success(request, f"Đã lưu kênh {channel.name}.")
        return redirect("studio:channels")
    return render(
        request,
        "studio/channel_form.html",
        {"form": form, "channel": channel, "drive_email": drive.service_account_email()},
    )


@manager_required
@require_POST
def channel_sync(request, pk):
    channel = get_object_or_404(Channel, pk=pk)
    if not channel.drive_folder_id:
        messages.error(request, "Kênh chưa có ID thư mục Google Drive.")
        return redirect("studio:channels")
    try:
        client = drive.get_client()
    except drive.DriveError as exc:
        messages.error(request, str(exc))
        return redirect("studio:channels")
    if client is None:
        messages.error(request, "Máy chủ chưa cấu hình service account Google Drive (xem README).")
        return redirect("studio:channels")
    count = drive.sync_channel(channel, client)
    channel.refresh_from_db()
    if channel.drive_error:
        messages.error(request, f"Đồng bộ lỗi: {channel.drive_error}")
    else:
        messages.success(request, f"Đã quét Drive: {count} video mới. Worker sẽ tải video và viết caption.")
    return redirect("studio:channels")


# --- Kho video ----------------------------------------------------------------

STATUS_FILTERS = {
    "cho-xu-ly": (
        "Đang xử lý",
        Q(posts__isnull=True)
        & (~Q(file_status=Video.FileStatus.READY) | Q(caption_status=Video.CaptionStatus.PENDING)),
    ),
    "loi": ("Lỗi", Q(caption_status=Video.CaptionStatus.FAILED) | Q(file_status=Video.FileStatus.FAILED)),
    "san-sang": (
        "Sẵn sàng, chưa xếp lịch",
        Q(posts__isnull=True, file_status=Video.FileStatus.READY, caption_status__in=Video.READY_CAPTION_STATUSES),
    ),
    "da-xep": ("Đã xếp lịch", Q(posts__status=Post.Status.PENDING)),
    "da-dang": ("Đã đăng", Q(posts__status=Post.Status.POSTED)),
}


@manager_required
def video_list(request):
    videos = (
        Video.objects.filter(is_archived=False)
        .select_related("channel")
        .prefetch_related("posts")
        .order_by("-created_at")
    )
    channel_id = request.GET.get("kenh", "")
    if channel_id.isdigit():
        videos = videos.filter(channel_id=channel_id)
    status = request.GET.get("trang-thai")
    if status in STATUS_FILTERS:
        videos = videos.filter(STATUS_FILTERS[status][1]).distinct()
    page = Paginator(videos, 50).get_page(request.GET.get("trang"))
    return render(
        request,
        "studio/video_list.html",
        {
            "page": page,
            "channels": Channel.objects.all(),
            "channel_id": channel_id,
            "status": status,
            "status_filters": [(k, v[0]) for k, v in STATUS_FILTERS.items()],
        },
    )


@manager_required
def video_upload(request):
    form = VideoUploadForm(request.POST or None, request.FILES or None, initial={"channel": request.GET.get("kenh")})
    if request.method == "POST" and form.is_valid():
        video = form.save(commit=False)
        video.source = Video.Source.UPLOAD
        upload = form.cleaned_data["file"]
        video.title = video.title or upload.name.rsplit(".", 1)[0]
        video.original_name = upload.name[:300]
        video.size = upload.size
        video.file_status = Video.FileStatus.READY
        caption = form.cleaned_data["caption"].strip()
        if caption or not video.channel.auto_caption:
            video.caption = caption or video.channel.default_hashtags
            video.caption_status = Video.CaptionStatus.MANUAL
        video.save()
        messages.success(request, f"Đã thêm video “{video.title}”.")
        return redirect("studio:video_detail", pk=video.pk)
    return render(request, "studio/video_upload.html", {"form": form})


@manager_required
def video_detail(request, pk):
    video = get_object_or_404(Video.objects.select_related("channel"), pk=pk)
    form = VideoEditForm(request.POST or None, instance=video)
    if request.method == "POST" and form.is_valid():
        caption_changed = "caption" in form.changed_data
        video = form.save()
        if caption_changed:
            video.apply_caption(video.caption, Video.CaptionStatus.MANUAL)
        messages.success(request, "Đã lưu video.")
        return redirect("studio:video_detail", pk=video.pk)
    return render(
        request,
        "studio/video_detail.html",
        {"video": video, "form": form, "posts": video.posts.select_related("assignee")},
    )


@manager_required
def video_file(request, pk):
    return serve_video(request, get_object_or_404(Video, pk=pk), as_attachment=request.GET.get("tai") == "1")


@manager_required
@require_POST
def video_regenerate(request, pk):
    video = get_object_or_404(Video.objects.select_related("channel"), pk=pk)
    try:
        caption = ai.generate_caption(video)
    except ai.AIError as exc:
        messages.error(request, f"AI chưa viết được: {exc}")
    else:
        video.apply_caption(caption, Video.CaptionStatus.DONE)
        messages.success(request, "AI đã viết lại caption.")
    return redirect("studio:video_detail", pk=video.pk)


@manager_required
@require_POST
def video_retry(request, pk):
    """Thử lại tải file / viết caption cho video bị lỗi."""
    video = get_object_or_404(Video, pk=pk)
    fields = []
    if video.file_status == Video.FileStatus.FAILED:
        video.file_status, video.file_error = Video.FileStatus.PENDING, ""
        fields += ["file_status", "file_error"]
    if video.caption_status == Video.CaptionStatus.FAILED:
        video.caption_status, video.caption_attempts, video.caption_error = Video.CaptionStatus.PENDING, 0, ""
        fields += ["caption_status", "caption_attempts", "caption_error"]
    if fields:
        video.save(update_fields=fields)
    messages.info(request, "Worker sẽ xử lý lại video này trong vài phút.")
    return redirect("studio:video_detail", pk=video.pk)


@manager_required
@require_POST
def video_delete(request, pk):
    video = get_object_or_404(Video, pk=pk)
    if video.posts.filter(status=Post.Status.POSTED).exists():
        messages.error(request, "Video đã đăng, không xóa được (để giữ lịch sử).")
        return redirect("studio:video_detail", pk=video.pk)
    if video.file:
        video.file.delete(save=False)
    title = video.title
    if video.source == Video.Source.DRIVE:
        video.posts.filter(status=Post.Status.PENDING).delete()
        video.file_status, video.is_archived = Video.FileStatus.REMOVED, True
        video.save(update_fields=["file", "file_status", "is_archived"])
    else:
        video.delete()
    messages.info(request, f"Đã xóa video “{title}”.")
    return redirect("studio:videos")
