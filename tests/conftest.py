import json

import httpx
import pytest

from studio.models import AIProvider, Channel, User, Video
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
    from django.core.files.base import ContentFile

    counter = {"n": 0}

    def make(**kwargs):
        counter["n"] += 1
        defaults = {
            "channel": channel,
            "title": f"video-{counter['n']}",
            "caption": f"Caption {counter['n']}",
            "caption_status": Video.CaptionStatus.MANUAL,
            "file_status": Video.FileStatus.READY,
        }
        defaults.update(kwargs)
        video = Video(**defaults)
        if video.file_status == Video.FileStatus.READY and "file" not in kwargs:
            video.file.save(f"{video.title}.mp4", ContentFile(b"0123456789" * 10), save=False)
        video.save()
        return video

    return make


def chat_response(content: str):
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})


def json_body(request: httpx.Request) -> dict:
    return json.loads(request.content)
