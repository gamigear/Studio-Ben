from datetime import datetime, time

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import timezone

from studio import crypto
from studio.models import AIProvider, ApiKey, Post, Video, parse_post_times
from studio.services import scheduler

from .conftest import chat_response, json_body


def local(*args):
    return timezone.make_aware(datetime(*args))


# --- Mã hóa -------------------------------------------------------------------


def test_encrypt_roundtrip():
    token = crypto.encrypt("sk-bi-mat")
    assert token.startswith("v1:") and "sk-bi-mat" not in token
    assert crypto.decrypt(token) == "sk-bi-mat"


def test_api_key_is_encrypted_in_db(provider):
    with connection.cursor() as cur:
        cur.execute("SELECT api_key FROM studio_aiprovider WHERE id = %s", [provider.pk])
        raw = cur.fetchone()[0]
    assert raw.startswith("v1:") and "sk-test" not in raw
    assert AIProvider.objects.get(pk=provider.pk).api_key == "sk-test-1234567890"


# --- Model --------------------------------------------------------------------


def test_parse_post_times_sorts_and_dedupes():
    assert parse_post_times("19:00, 8:00;12:30, 08:00") == [time(8), time(12, 30), time(19)]


def test_parse_post_times_rejects_garbage():
    with pytest.raises(ValidationError):
        parse_post_times("8h sáng")


def test_api_key_issue_and_authenticate(manager):
    key, raw = ApiKey.issue("agent", manager)
    assert raw.startswith("lenlich_") and key.key_hash != raw
    assert ApiKey.authenticate(raw) == key
    key.is_active = False
    key.save()
    assert ApiKey.authenticate(raw) is None
    assert ApiKey.authenticate("sai") is None


def test_only_one_default_provider(provider):
    second = AIProvider.objects.create(name="B", api_key="k" * 12, model="m", is_default=True)
    provider.refresh_from_db()
    assert not provider.is_default and second.is_default


# --- Xếp lịch -------------------------------------------------------------------


def test_schedule_fills_future_slots_oldest_first(channel, make_video, staff):
    v1, v2, v3, v4 = (make_video() for _ in range(4))
    now = local(2026, 10, 21, 10, 0)  # sau 08:00 → hôm nay còn 12:00 và 19:00
    created = scheduler.schedule_channel(channel, now=now, days=2)
    assert created == 4
    posts = list(Post.objects.order_by("scheduled_at"))
    assert [p.video for p in posts] == [v1, v2, v3, v4]
    assert [timezone.localtime(p.scheduled_at).strftime("%d %H:%M") for p in posts] == [
        "21 12:00",
        "21 19:00",
        "22 08:00",
        "22 12:00",
    ]
    assert all(p.assignee == staff and p.caption.startswith("Caption") for p in posts)


def test_schedule_is_idempotent_and_skips_not_ready(channel, make_video):
    make_video()
    make_video(caption_status=Video.CaptionStatus.PENDING, caption="")
    make_video(file_status=Video.FileStatus.PENDING)
    make_video(is_archived=True)
    now = local(2026, 10, 21, 6, 0)
    assert scheduler.schedule_channel(channel, now=now, days=1) == 1
    assert scheduler.schedule_channel(channel, now=now, days=1) == 0
    assert Post.objects.count() == 1


def test_schedule_does_not_reuse_taken_slot(channel, make_video):
    first = make_video()
    now = local(2026, 10, 21, 6, 0)
    scheduler.schedule_channel(channel, now=now, days=1)
    Post.objects.filter(video=first).update(status=Post.Status.SKIPPED)
    make_video()
    make_video()
    assert scheduler.schedule_channel(channel, now=now, days=1) == 2
    assert Post.objects.count() == 3


def test_apply_caption_updates_pending_posts(channel, make_video):
    video = make_video()
    scheduler.schedule_channel(channel, now=local(2026, 10, 21, 6, 0), days=1)
    video.apply_caption("Caption mới", Video.CaptionStatus.MANUAL)
    assert Post.objects.get(video=video).caption == "Caption mới"


# --- AI -------------------------------------------------------------------------


def test_caption_generation_success(channel, make_video, provider, mock_http):
    video = make_video(caption="", caption_status=Video.CaptionStatus.PENDING, notes="Mẹo tẩy vết dầu mỡ")
    calls = mock_http(lambda request: chat_response('"Mẹo hay quá! #meovat"'))
    from studio.services import ai

    assert ai.process_pending_captions() == 1
    video.refresh_from_db()
    assert video.caption == "Mẹo hay quá! #meovat"
    assert video.caption_status == Video.CaptionStatus.DONE
    req = calls[0]
    assert str(req.url) == "https://api.openai.com/v1/chat/completions"
    assert req.headers["Authorization"] == "Bearer sk-test-1234567890"
    body = json_body(req)
    assert body["model"] == "gpt-test" and "temperature" not in body
    user_msg = body["messages"][1]["content"]
    assert "Giọng vui, xưng mình" in user_msg and "Mẹo tẩy vết dầu mỡ" in user_msg and "#meovat" in user_msg


def test_caption_generation_failure_counts_attempts(channel, make_video, provider, mock_http):
    import httpx

    from studio.services import ai

    video = make_video(caption="", caption_status=Video.CaptionStatus.PENDING)
    mock_http(lambda request: httpx.Response(401, json={"error": {"message": "Incorrect API key"}}))
    assert ai.process_pending_captions() == 0
    video.refresh_from_db()
    assert video.caption_status == Video.CaptionStatus.FAILED
    assert video.caption_attempts == 1 and "Incorrect API key" in video.caption_error


def test_caption_waits_without_provider(channel, make_video):
    from studio.services import ai

    video = make_video(caption="", caption_status=Video.CaptionStatus.PENDING)
    assert ai.process_pending_captions() == 0
    video.refresh_from_db()
    assert video.caption_status == Video.CaptionStatus.PENDING and video.caption_attempts == 0
    assert "Chưa cấu hình" in video.caption_error


def test_temperature_sent_when_set(channel, make_video, provider, mock_http):
    from studio.services import ai

    provider.temperature = 0.7
    provider.save()
    video = make_video(caption="", caption_status=Video.CaptionStatus.PENDING)
    calls = mock_http(lambda request: chat_response("ok"))
    ai.generate_caption(video)
    assert json_body(calls[0])["temperature"] == 0.7
