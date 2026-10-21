"""Đồng bộ video từ Google Drive (mỗi kênh một thư mục) bằng service account.

Quy ước thư mục: mỗi file video là một bài. Nếu có file .txt cùng tên
(ví dụ `meo-vat.mp4` + `meo-vat.txt`) thì nội dung .txt được dùng làm
mô tả / kịch bản để AI viết caption.
"""

import json
import logging
import tempfile
import time
from pathlib import PurePosixPath

import httpx
from django.conf import settings
from django.core.files import File
from django.utils import timezone
from django.utils.text import get_valid_filename
from google.auth import crypt, jwt

from ..models import Channel, Post, Video
from . import http

logger = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/drive.readonly"
API = "https://www.googleapis.com/drive/v3"
MAX_NOTES_LENGTH = 20000


class DriveError(Exception):
    pass


def service_account_info() -> dict | None:
    raw = settings.GOOGLE_SERVICE_ACCOUNT_JSON
    if not raw and settings.GOOGLE_SERVICE_ACCOUNT_FILE:
        try:
            with open(settings.GOOGLE_SERVICE_ACCOUNT_FILE, encoding="utf-8") as fh:
                raw = fh.read()
        except OSError as exc:
            raise DriveError(f"Không đọc được file service account: {exc}") from exc
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise DriveError("Nội dung service account không phải JSON hợp lệ.") from exc


def service_account_email() -> str:
    try:
        info = service_account_info()
    except DriveError:
        return ""
    return (info or {}).get("client_email", "")


class DriveClient:
    def __init__(self, info: dict):
        self.info = info
        self._access_token = ""
        self._expires_at = 0.0

    def _token(self) -> str:
        if self._access_token and time.time() < self._expires_at - 60:
            return self._access_token
        now = int(time.time())
        token_uri = self.info.get("token_uri", "https://oauth2.googleapis.com/token")
        try:
            signer = crypt.RSASigner.from_service_account_info(self.info)
        except (KeyError, ValueError) as exc:
            raise DriveError("Service account thiếu private_key hoặc client_email.") from exc
        assertion = jwt.encode(
            signer,
            {"iss": self.info["client_email"], "scope": SCOPE, "aud": token_uri, "iat": now, "exp": now + 3600},
        )
        data = self._post_token(token_uri, assertion)
        self._access_token = data["access_token"]
        self._expires_at = time.time() + int(data.get("expires_in", 3600))
        return self._access_token

    def _post_token(self, token_uri: str, assertion: bytes) -> dict:
        try:
            with http.client(timeout=30) as c:
                resp = c.post(
                    token_uri,
                    data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
                )
        except httpx.HTTPError as exc:
            raise DriveError(f"Không lấy được token Google: {exc}") from exc
        if resp.status_code != 200:
            raise DriveError(f"Google từ chối service account ({resp.status_code}): {resp.text[:300]}")
        return resp.json()

    def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        try:
            with http.client(timeout=60) as c:
                resp = c.get(f"{API}{path}", params=params, headers={"Authorization": f"Bearer {self._token()}"})
        except httpx.HTTPError as exc:
            raise DriveError(f"Lỗi kết nối Google Drive: {exc}") from exc
        if resp.status_code == 404:
            raise DriveError("Không tìm thấy thư mục/file. Kiểm tra ID và đã chia sẻ cho service account chưa.")
        if resp.status_code != 200:
            raise DriveError(f"Google Drive trả lỗi {resp.status_code}: {resp.text[:300]}")
        return resp

    def list_folder(self, folder_id: str) -> list[dict]:
        files: list[dict] = []
        params = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "fields": "nextPageToken, files(id, name, mimeType, size, createdTime)",
            "pageSize": 200,
            "orderBy": "createdTime",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        while True:
            data = self._get("/files", params).json()
            files.extend(data.get("files", []))
            token = data.get("nextPageToken")
            if not token:
                return files
            params["pageToken"] = token

    def download_text(self, file_id: str) -> str:
        resp = self._get(f"/files/{file_id}", {"alt": "media", "supportsAllDrives": "true"})
        return resp.content.decode("utf-8", errors="replace")[:MAX_NOTES_LENGTH]

    def download_to(self, file_id: str, fileobj) -> int:
        """Tải file về theo luồng, không giữ cả video trong RAM."""
        size = 0
        try:
            with (
                http.client(timeout=600) as c,
                c.stream(
                    "GET",
                    f"{API}/files/{file_id}",
                    params={"alt": "media", "supportsAllDrives": "true"},
                    headers={"Authorization": f"Bearer {self._token()}"},
                ) as resp,
            ):
                if resp.status_code != 200:
                    resp.read()
                    raise DriveError(f"Tải video lỗi {resp.status_code}: {resp.text[:300]}")
                for chunk in resp.iter_bytes(1024 * 1024):
                    fileobj.write(chunk)
                    size += len(chunk)
        except httpx.HTTPError as exc:
            raise DriveError(f"Lỗi kết nối khi tải video: {exc}") from exc
        return size


def get_client() -> DriveClient | None:
    info = service_account_info()
    return DriveClient(info) if info else None


def _is_video(f: dict) -> bool:
    return f.get("mimeType", "").startswith("video/")


def _is_text(f: dict) -> bool:
    return f.get("mimeType") == "text/plain" or f.get("name", "").lower().endswith(".txt")


def sync_channel(channel: Channel, drive: DriveClient) -> int:
    """Thêm video mới trong thư mục Drive của kênh vào kho. Trả về số video mới."""
    try:
        files = drive.list_folder(channel.drive_folder_id)
        notes_files = {PurePosixPath(f["name"]).stem: f for f in files if _is_text(f)}
        known = {
            v.drive_file_id: v
            for v in channel.videos.exclude(drive_file_id="").only("id", "drive_file_id", "notes", "caption_status")
        }
        created = 0
        for f in files:
            if not _is_video(f):
                continue
            stem = PurePosixPath(f["name"]).stem
            notes_file = notes_files.get(stem)
            existing = known.get(f["id"])
            if existing:
                # File .txt có thể được đẩy lên sau video: bổ sung nếu AI chưa viết.
                if notes_file and not existing.notes and existing.caption_status == Video.CaptionStatus.PENDING:
                    existing.notes = drive.download_text(notes_file["id"])
                    existing.save(update_fields=["notes"])
                continue
            notes = drive.download_text(notes_file["id"]) if notes_file else ""
            manual = not channel.auto_caption
            Video.objects.create(
                channel=channel,
                source=Video.Source.DRIVE,
                title=stem[:300],
                original_name=f["name"][:300],
                notes=notes,
                drive_file_id=f["id"],
                size=int(f["size"]) if f.get("size") else None,
                caption=channel.default_hashtags if manual else "",
                caption_status=Video.CaptionStatus.MANUAL if manual else Video.CaptionStatus.PENDING,
            )
            created += 1
    except DriveError as exc:
        Channel.objects.filter(pk=channel.pk).update(drive_error=str(exc), drive_synced_at=timezone.now())
        logger.warning("Đồng bộ Drive lỗi cho kênh %s: %s", channel.pk, exc)
        return 0
    Channel.objects.filter(pk=channel.pk).update(drive_error="", drive_synced_at=timezone.now())
    return created


def sync_all() -> int:
    drive = get_client()
    if drive is None:
        return 0
    total = 0
    for channel in Channel.objects.filter(is_active=True).exclude(drive_folder_id=""):
        total += sync_channel(channel, drive)
    return total


def download_pending(limit: int = 3) -> int:
    """Tải file video từ Drive về máy chủ để nhân viên tải nhanh trên điện thoại."""
    videos = list(
        Video.objects.filter(
            source=Video.Source.DRIVE,
            file_status=Video.FileStatus.PENDING,
            channel__is_active=True,
            is_archived=False,
        ).order_by("created_at")[:limit]
    )
    if not videos:
        return 0
    drive = get_client()
    if drive is None:
        return 0
    done = 0
    for video in videos:
        try:
            with tempfile.TemporaryFile() as tmp:
                size = drive.download_to(video.drive_file_id, tmp)
                tmp.seek(0)
                suffix = PurePosixPath(video.original_name).suffix or ".mp4"
                name = get_valid_filename(f"{video.title}{suffix}") or f"video-{video.pk}{suffix}"
                video.file.save(name, File(tmp), save=False)
        except DriveError as exc:
            video.file_status = Video.FileStatus.FAILED
            video.file_error = str(exc)
            video.save(update_fields=["file_status", "file_error"])
            continue
        video.size = size
        video.file_status = Video.FileStatus.READY
        video.file_error = ""
        video.save(update_fields=["file", "size", "file_status", "file_error"])
        done += 1
    return done


def cleanup_media(now=None) -> int:
    """Xóa file video trên máy chủ sau khi bài đã đăng/bỏ qua quá MEDIA_RETENTION_DAYS ngày."""
    now = now or timezone.now()
    cutoff = now - timezone.timedelta(days=settings.MEDIA_RETENTION_DAYS)
    videos = (
        Video.objects.filter(
            file_status=Video.FileStatus.READY, posts__status__in=[Post.Status.POSTED, Post.Status.SKIPPED]
        )
        .exclude(posts__status=Post.Status.PENDING)
        .filter(posts__scheduled_at__lt=cutoff)
        .distinct()
    )
    removed = 0
    for video in videos:
        if video.file:
            video.file.delete(save=False)
        video.file_status = Video.FileStatus.REMOVED
        video.save(update_fields=["file", "file_status"])
        removed += 1
    return removed
