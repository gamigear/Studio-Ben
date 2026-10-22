"""Tạo / dọn nội dung trong kho, dùng chung cho giao diện, API và đồng bộ Drive."""

from django.db import transaction

from ..models import Channel, MediaFile, Video


@transaction.atomic
def create_content(
    channel: Channel, source: str, uploads: list, *, title: str = "", notes: str = "", caption: str = ""
) -> Video:
    """Tạo nội dung từ các file tải lên (video, ảnh, nhiều ảnh) hoặc không file (bài chữ).

    Có `caption` thì dùng luôn (viết tay); để trống thì AI viết nếu kênh bật AI.
    """
    kinds = [MediaFile.kind_from_mime(u.content_type or "") for u in uploads]
    if any(k is None for k in kinds):
        raise ValueError("Chỉ nhận file video hoặc ảnh.")
    caption = caption.strip()
    manual = bool(caption) or not channel.auto_caption
    default_title = uploads[0].name.rsplit(".", 1)[0] if uploads else (notes or caption)[:60]
    video = Video.objects.create(
        channel=channel,
        source=source,
        kind=Video.kind_for(kinds),
        title=(title or default_title or "Bài viết")[:300],
        notes=notes,
        file_status=Video.FileStatus.READY,
        caption=caption or (channel.default_hashtags if manual else ""),
        caption_status=Video.CaptionStatus.MANUAL if manual else Video.CaptionStatus.PENDING,
    )
    for position, (upload, kind) in enumerate(zip(uploads, kinds, strict=True)):
        media = MediaFile(
            content=video,
            position=position,
            kind=kind,
            original_name=upload.name[:300],
            mime_type=upload.content_type or "",
            size=upload.size,
            status=Video.FileStatus.READY,
        )
        media.file.save(upload.name, upload, save=False)
        media.save()
    return video


def file_shared(media: MediaFile) -> bool:
    """File trên đĩa có đang được nội dung khác (kênh khác dùng chung thư mục Drive) sử dụng không."""
    return (
        MediaFile.objects.filter(file=media.file.name)
        .exclude(pk=media.pk)
        .exclude(status=Video.FileStatus.REMOVED)
        .exists()
    )


def remove_files(video: Video) -> None:
    """Xóa file trên máy chủ của nội dung (giữ file nếu kênh khác còn dùng)."""
    for media in video.media.all():
        if media.file and not file_shared(media):
            media.file.delete(save=False)
        media.file = ""
        media.status = Video.FileStatus.REMOVED
        media.save(update_fields=["file", "status"])
