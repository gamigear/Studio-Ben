import httpx

from studio.models import Channel, Post, Video
from studio.services import drive


class FakeDrive:
    def __init__(self, files, texts=None):
        self.files = files
        self.texts = texts or {}

    def list_folder(self, folder_id):
        return self.files

    def download_text(self, file_id):
        return self.texts[file_id]


def test_sync_creates_videos_with_sidecar_notes(channel):
    channel.drive_folder_id = "folder1"
    channel.save()
    fake = FakeDrive(
        [
            {"id": "v1", "name": "meo-tay-dau-mo.mp4", "mimeType": "video/mp4", "size": "1000"},
            {"id": "t1", "name": "meo-tay-dau-mo.txt", "mimeType": "text/plain"},
            {"id": "v2", "name": "clip2.mov", "mimeType": "video/quicktime"},
            {"id": "x", "name": "anh.jpg", "mimeType": "image/jpeg"},
        ],
        {"t1": "Kịch bản: tẩy dầu mỡ bằng baking soda"},
    )
    assert drive.sync_channel(channel, fake) == 3
    assert Video.objects.get(drive_file_id="x").kind == Video.Kind.IMAGE
    v1 = Video.objects.get(drive_file_id="v1")
    assert v1.title == "meo-tay-dau-mo" and v1.notes.startswith("Kịch bản")
    media = v1.media.get()
    assert media.size == 1000 and v1.file_status == Video.FileStatus.PENDING and v1.kind == Video.Kind.VIDEO
    assert v1.caption_status == Video.CaptionStatus.PENDING and media.original_name == "meo-tay-dau-mo.mp4"
    # Quét lại không tạo trùng.
    assert drive.sync_channel(channel, fake) == 0
    channel.refresh_from_db()
    assert channel.drive_synced_at and not channel.drive_error


def test_sync_manual_caption_channel_uses_default_hashtags(channel):
    channel.auto_caption = False
    channel.save()
    drive.sync_channel(channel, FakeDrive([{"id": "v1", "name": "a.mp4", "mimeType": "video/mp4"}]))
    video = Video.objects.get()
    assert video.caption_status == Video.CaptionStatus.MANUAL and video.caption == "#meovat #giadinh"


def test_sync_records_error(channel):
    class Broken:
        def list_folder(self, folder_id):
            raise drive.DriveError("Không tìm thấy thư mục")

    assert drive.sync_channel(channel, Broken()) == 0
    assert Channel.objects.get(pk=channel.pk).drive_error == "Không tìm thấy thư mục"


def test_archived_drive_video_is_not_recreated(channel):
    fake = FakeDrive([{"id": "v1", "name": "a.mp4", "mimeType": "video/mp4"}])
    drive.sync_channel(channel, fake)
    Video.objects.update(is_archived=True)
    assert drive.sync_channel(channel, fake) == 0


def _drive_content(channel, drive_id="v1", name="clip.mov"):
    return drive._new_content(
        channel,
        title="clip",
        notes="",
        drive_id=drive_id,
        media=[{"id": drive_id, "name": name, "mimeType": "video/quicktime"}],
    )


def test_download_pending_streams_file(channel, mock_http, monkeypatch, settings):
    settings.GOOGLE_SERVICE_ACCOUNT_JSON = '{"client_email": "sa@x.iam.gserviceaccount.com"}'
    monkeypatch.setattr(drive.DriveClient, "_token", lambda self: "tok")
    video = _drive_content(channel)
    calls = mock_http(lambda request: httpx.Response(200, content=b"videobytes"))
    assert drive.download_pending() == 1
    video.refresh_from_db()
    media = video.media.get()
    assert video.file_status == Video.FileStatus.READY and media.size == 10
    assert media.file.name.endswith(".mov")
    with media.file.open("rb") as fh:
        assert fh.read() == b"videobytes"
    assert calls[0].url.params["alt"] == "media" and calls[0].headers["Authorization"] == "Bearer tok"


def test_download_failure_is_recorded(channel, mock_http, monkeypatch, settings):
    settings.GOOGLE_SERVICE_ACCOUNT_JSON = '{"client_email": "sa@x.iam.gserviceaccount.com"}'
    monkeypatch.setattr(drive.DriveClient, "_token", lambda self: "tok")
    video = _drive_content(channel)
    mock_http(lambda request: httpx.Response(403, text="forbidden"))
    assert drive.download_pending() == 0
    video.refresh_from_db()
    assert video.file_status == Video.FileStatus.FAILED and "403" in video.file_error


def test_shared_folder_downloads_once_and_cleanup_keeps_shared_file(channel, mock_http, monkeypatch, settings, staff):
    """Hai kênh (TikTok + Facebook) dùng chung thư mục Drive: tải 1 lần, file chỉ bị xóa khi cả hai đã xong."""
    settings.GOOGLE_SERVICE_ACCOUNT_JSON = '{"client_email": "sa@x.iam.gserviceaccount.com"}'
    monkeypatch.setattr(drive.DriveClient, "_token", lambda self: "tok")
    fb = Channel.objects.create(name="Fanpage", platform=Channel.Platform.FACEBOOK, assignee=staff)
    a, b = _drive_content(channel), _drive_content(fb)
    calls = mock_http(lambda request: httpx.Response(200, content=b"videobytes"))
    assert drive.download_pending() == 2
    assert len(calls) == 1
    ma, mb = a.media.get(), b.media.get()
    assert ma.file.name == mb.file.name and ma.file.storage.exists(ma.file.name)
    from studio.services.content import remove_files

    remove_files(a)
    assert mb.file.storage.exists(mb.file.name)
    remove_files(b)
    assert not mb.file.storage.exists(mb.file.name)


def test_sync_album_subfolder_waits_until_settled(channel):
    from datetime import timedelta

    from django.utils import timezone

    now = timezone.now()
    old = (now - timedelta(minutes=30)).isoformat()
    recent = (now - timedelta(minutes=2)).isoformat()

    class AlbumDrive(FakeDrive):
        def __init__(self, child_time):
            super().__init__(
                [{"id": "f1", "name": "Album bộ sưu tập", "mimeType": drive.FOLDER_MIME}], {"t": "Mô tả album"}
            )
            self.child_time = child_time

        def list_folder(self, folder_id):
            if folder_id == "f1":
                return [
                    {"id": "i2", "name": "2.jpg", "mimeType": "image/jpeg", "modifiedTime": self.child_time},
                    {"id": "i1", "name": "1.jpg", "mimeType": "image/jpeg", "modifiedTime": old},
                    {"id": "t", "name": "mo-ta.txt", "mimeType": "text/plain", "modifiedTime": old},
                ]
            return self.files

    assert drive.sync_channel(channel, AlbumDrive(recent), now=now) == 0
    assert drive.sync_channel(channel, AlbumDrive(old), now=now) == 1
    album = Video.objects.get()
    assert album.kind == Video.Kind.ALBUM and album.notes == "Mô tả album" and album.drive_file_id == "f1"
    assert [m.original_name for m in album.media.all()] == ["1.jpg", "2.jpg"]
    assert drive.sync_channel(channel, AlbumDrive(old), now=now) == 0


def test_sync_single_image(channel):
    drive.sync_channel(channel, FakeDrive([{"id": "i", "name": "anh.jpg", "mimeType": "image/jpeg"}]))
    assert Video.objects.get().kind == Video.Kind.IMAGE


def test_cleanup_removes_old_posted_files(channel, make_video, settings):
    from django.utils import timezone

    settings.MEDIA_RETENTION_DAYS = 7
    old = make_video()
    recent = make_video()
    pending = make_video()
    now = timezone.now()
    Post.objects.create(
        channel=channel, video=old, scheduled_at=now - timezone.timedelta(days=10), status=Post.Status.POSTED
    )
    Post.objects.create(
        channel=channel, video=recent, scheduled_at=now - timezone.timedelta(days=1), status=Post.Status.POSTED
    )
    Post.objects.create(channel=channel, video=pending, scheduled_at=now - timezone.timedelta(days=10))
    assert drive.cleanup_media(now) == 1
    old.refresh_from_db()
    assert old.file_status == Video.FileStatus.REMOVED and not old.media.get().file


def test_missing_service_account_file_means_not_configured(settings, tmp_path):
    settings.GOOGLE_SERVICE_ACCOUNT_FILE = str(tmp_path / "khong-co.json")
    assert drive.service_account_info() is None
    bad = tmp_path / "hong.json"
    bad.write_text("không phải json")
    settings.GOOGLE_SERVICE_ACCOUNT_FILE = str(bad)
    import pytest

    with pytest.raises(drive.DriveError):
        drive.service_account_info()
