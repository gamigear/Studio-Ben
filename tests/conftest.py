import json

import httpx
import pytest

from studio.models import AIProvider, Channel, MediaFile, User, Video
from studio.services import http


@pytest.fixture(autouse=True)
def _media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture
def mock_http():
    """Đặt handler cho mọi request ra ngoài: mock_http(lambda request: httpx.Response(...))."""
    calls = []

    def install(handler):
        def wrapped(request):
            calls.append(request)
            return handler(request)

        http.transport = httpx.MockTransport(wrapped)
        return calls

    yield install
    http.transport = None


@pytest.fixture
def manager(db):
    return User.objects.create_user("quanly", password="matkhau123", role=User.Role.MANAGER, first_name="Quản lý")


@pytest.fixture
def staff(db):
    return User.objects.create_user("nhanvien", password="matkhau123", role=User.Role.STAFF, first_name="Lan")


@pytest.fixture
def other_staff(db):
    return User.objects.create_user("nhanvien2", password="matkhau123", role=User.Role.STAFF, first_name="Minh")


@pytest.fixture
def provider(db):
    return AIProvider.objects.create(name="OpenAI", api_key="sk-test-1234567890", model="gpt-test", is_default=True)


@pytest.fixture
def channel(db, staff):
    return Channel.objects.create(
        name="Mẹo vặt",
        handle="meovat",
        topic="Mẹo vặt gia đình",
        content_instructions="Giọng vui, xưng mình",
        default_hashtags="#meovat #giadinh",
        post_times="08:00, 12:00, 19:00",
        assignee=staff,
        device="Máy 1",
    )


@pytest.fixture
def make_video(channel, tmp_path):
    """Tạo nội dung sẵn sàng. `files=[("a.jpg", "image/jpeg"), ...]` để tạo ảnh / album; mặc định 1 video."""
    from django.core.files.base import ContentFile

    counter = {"n": 0}

    def make(files=None, **kwargs):
        counter["n"] += 1
        defaults = {
            "channel": channel,
            "title": f"video-{counter['n']}",
            "caption": f"Caption {counter['n']}",
            "caption_status": Video.CaptionStatus.MANUAL,
            "file_status": Video.FileStatus.READY,
        }
        defaults.update(kwargs)
        if files is None:
            files = [(f"{defaults['title']}.mp4", "video/mp4")] if defaults.get("kind") != Video.Kind.TEXT else []
        defaults.setdefault("kind", Video.kind_for([MediaFile.kind_from_mime(mime) for _, mime in files]))
        video = Video.objects.create(**defaults)
        for i, (name, mime) in enumerate(files):
            media = MediaFile(
                content=video,
                position=i,
                kind=MediaFile.kind_from_mime(mime),
                original_name=name,
                mime_type=mime,
                status=Video.FileStatus.READY if video.file_status == Video.FileStatus.READY else video.file_status,
            )
            if media.status == Video.FileStatus.READY:
                media.file.save(name, ContentFile(b"0123456789" * 10), save=False)
                media.size = 100
            media.save()
        return video

    return make


def chat_response(content: str):
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})


def json_body(request: httpx.Request) -> dict:
    return json.loads(request.content)
