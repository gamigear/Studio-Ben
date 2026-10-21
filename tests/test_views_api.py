import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from studio.models import ApiKey, Post, Video


@pytest.fixture
def post(channel, make_video, staff):
    video = make_video()
    return Post.objects.create(
        channel=channel,
        video=video,
        scheduled_at=timezone.now() + timezone.timedelta(hours=1),
        caption="Hi",
        assignee=staff,
    )


# --- Giao diện ------------------------------------------------------------------


def test_login_required(client, db):
    resp = client.get(reverse("studio:my_tasks"))
    assert resp.status_code == 302 and reverse("studio:login") in resp["Location"]


def test_staff_sees_own_tasks(client, staff, post):
    client.force_login(staff)
    resp = client.get(reverse("studio:my_tasks"))
    assert resp.status_code == 200
    assert "Mẹo vặt" in resp.content.decode() and "Chia sẻ sang TikTok" in resp.content.decode()


def test_staff_home_redirects_to_tasks(client, staff):
    client.force_login(staff)
    assert client.get(reverse("studio:home"))["Location"] == reverse("studio:my_tasks")


def test_staff_cannot_open_manager_pages(client, staff):
    client.force_login(staff)
    for name in ["studio:dashboard", "studio:schedule", "studio:channels", "studio:videos", "studio:settings"]:
        assert client.get(reverse(name)).status_code == 403, name


def test_other_staff_cannot_touch_post(client, other_staff, post):
    client.force_login(other_staff)
    assert client.get(reverse("studio:post_video", args=[post.pk])).status_code == 403
    assert client.post(reverse("studio:mark_posted", args=[post.pk])).status_code == 403


def test_mark_posted_and_undo(client, staff, post):
    client.force_login(staff)
    resp = client.post(
        reverse("studio:mark_posted", args=[post.pk]), {"post_url": "https://www.tiktok.com/@meovat/video/1"}
    )
    assert resp.status_code == 302
    post.refresh_from_db()
    assert post.status == Post.Status.POSTED and post.posted_by == staff and post.post_url.endswith("/1")
    client.post(reverse("studio:undo_post", args=[post.pk]))
    post.refresh_from_db()
    assert post.status == Post.Status.PENDING and post.posted_at is None


def test_skip_post(client, staff, post):
    client.force_login(staff)
    client.post(reverse("studio:skip_post", args=[post.pk]), {"note": "Video lỗi tiếng"})
    post.refresh_from_db()
    assert post.status == Post.Status.SKIPPED and post.note == "Video lỗi tiếng"


def test_video_supports_range_requests(client, staff, post):
    client.force_login(staff)
    url = reverse("studio:post_video", args=[post.pk])
    resp = client.get(url, HTTP_RANGE="bytes=0-9")
    assert resp.status_code == 206 and resp["Content-Range"] == "bytes 0-9/100"
    assert b"".join(resp.streaming_content) == b"0123456789"
    full = client.get(url + "?tai=1")
    assert full.status_code == 200 and "attachment" in full["Content-Disposition"]


def test_manager_pages_render(client, manager, post, provider):
    client.force_login(manager)
    pages = [
        reverse("studio:dashboard"),
        reverse("studio:schedule"),
        reverse("studio:channels"),
        reverse("studio:channel_add"),
        reverse("studio:channel_edit", args=[post.channel_id]),
        reverse("studio:videos"),
        reverse("studio:videos") + "?trang-thai=da-xep",
        reverse("studio:video_upload"),
        reverse("studio:video_detail", args=[post.video_id]),
        reverse("studio:post_edit", args=[post.pk]),
        reverse("studio:settings"),
        reverse("studio:provider_add"),
        reverse("studio:provider_edit", args=[provider.pk]),
        reverse("studio:my_tasks") + f"?nv={post.assignee_id}",
    ]
    for url in pages:
        assert client.get(url).status_code == 200, url


def test_dashboard_counts(client, manager, post, make_video):
    make_video()
    make_video()
    client.force_login(manager)
    resp = client.get(reverse("studio:dashboard"))
    channel = next(c for c in resp.context["channels"] if c.pk == post.channel_id)
    assert channel.ready == 2 and channel.today_total in (0, 1)
    assert channel.days_left == round(2 / 3, 1)


def test_channel_form_normalises_fields(client, manager, staff):
    client.force_login(manager)
    resp = client.post(
        reverse("studio:channel_add"),
        {
            "name": "Bếp nhà",
            "platform": "tiktok",
            "post_times": "19:00,7:30",
            "drive_folder_id": "https://drive.google.com/drive/folders/abc123?usp=sharing",
            "assignee": staff.pk,
            "auto_caption": "on",
            "is_active": "on",
        },
    )
    assert resp.status_code == 302
    from studio.models import Channel

    ch = Channel.objects.get(name="Bếp nhà")
    assert ch.post_times == "07:30, 19:00" and ch.drive_folder_id == "abc123"


def test_upload_video_with_caption_is_manual(client, manager, channel):
    client.force_login(manager)
    resp = client.post(
        reverse("studio:video_upload"),
        {"channel": channel.pk, "file": SimpleUploadedFile("tu-quay.mp4", b"abc", "video/mp4"), "caption": "Viết tay"},
    )
    assert resp.status_code == 302
    video = Video.objects.get()
    assert video.title == "tu-quay" and video.caption_status == Video.CaptionStatus.MANUAL and video.is_ready


def test_provider_form_keeps_key_when_blank(client, manager, provider):
    client.force_login(manager)
    client.post(
        reverse("studio:provider_edit", args=[provider.pk]),
        {
            "name": "OpenAI 2",
            "base_url": "https://api.openai.com/v1",
            "api_key": "",
            "model": "gpt-x",
            "is_default": "on",
        },
    )
    provider.refresh_from_db()
    assert provider.name == "OpenAI 2" and provider.api_key == "sk-test-1234567890"


def test_api_key_shown_once(client, manager):
    client.force_login(manager)
    client.post(reverse("studio:api_key_create"), {"name": "Agent Douyin"})
    first = client.get(reverse("studio:settings")).context["new_api_key"]
    assert first.startswith("lenlich_")
    assert client.get(reverse("studio:settings")).context["new_api_key"] is None


def test_delete_drive_video_archives_it(client, manager, post):
    Video.objects.filter(pk=post.video_id).update(source=Video.Source.DRIVE, drive_file_id="d1")
    client.force_login(manager)
    client.post(reverse("studio:video_delete", args=[post.video_id]))
    video = Video.objects.get(pk=post.video_id)
    assert video.is_archived and not Post.objects.filter(pk=post.pk).exists()


# --- REST API -------------------------------------------------------------------


@pytest.fixture
def api_auth(manager):
    _, raw = ApiKey.issue("test", manager)
    return {"HTTP_AUTHORIZATION": f"Bearer {raw}"}


def test_api_requires_key(client, db):
    assert client.get("/api/v1/channels").status_code == 401
    assert client.get("/api/v1/channels", HTTP_AUTHORIZATION="Bearer lenlich_sai").status_code == 401


def test_api_list_and_patch_channel(client, channel, api_auth):
    data = client.get("/api/v1/channels", **api_auth).json()
    assert data[0]["name"] == "Mẹo vặt" and data[0]["post_times"] == "08:00, 12:00, 19:00"
    resp = client.patch(
        f"/api/v1/channels/{channel.pk}",
        data={"content_instructions": "Giọng chuyên gia"},
        content_type="application/json",
        **api_auth,
    )
    assert resp.status_code == 200 and resp.json()["content_instructions"] == "Giọng chuyên gia"


def test_api_upload_video(client, channel, api_auth):
    resp = client.post(
        "/api/v1/videos",
        {
            "channel_id": channel.pk,
            "file": SimpleUploadedFile("dich-douyin.mp4", b"abc", "video/mp4"),
            "notes": "Kịch bản",
        },
        **api_auth,
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["caption_status"] == "pending" and body["state"] == "processing" and body["notes"] == "Kịch bản"
    video = Video.objects.get(pk=body["id"])
    assert video.source == Video.Source.API and video.file_status == Video.FileStatus.READY


def test_api_rejects_non_video(client, channel, api_auth):
    resp = client.post(
        "/api/v1/videos",
        {"channel_id": channel.pk, "file": SimpleUploadedFile("a.txt", b"x", "text/plain")},
        **api_auth,
    )
    assert resp.status_code == 400


def test_api_patch_caption_updates_post(client, post, api_auth):
    resp = client.patch(
        f"/api/v1/videos/{post.video_id}",
        data={"caption": "Caption từ agent"},
        content_type="application/json",
        **api_auth,
    )
    assert resp.status_code == 200 and resp.json()["state"] == "scheduled"
    post.refresh_from_db()
    assert post.caption == "Caption từ agent"


def test_api_list_posts_today(client, post, api_auth):
    day = timezone.localtime(post.scheduled_at).date().isoformat()
    data = client.get(f"/api/v1/posts?day={day}", **api_auth).json()
    assert [p["id"] for p in data] == [post.pk]
    assert client.get(f"/api/v1/posts?day={day}&status=posted", **api_auth).json() == []


def test_api_cannot_edit_posted(client, post, api_auth):
    Post.objects.filter(pk=post.pk).update(status=Post.Status.POSTED)
    resp = client.patch(f"/api/v1/posts/{post.pk}", data={"caption": "x"}, content_type="application/json", **api_auth)
    assert resp.status_code == 409


def test_bad_query_params_do_not_crash(client, manager, post):
    client.force_login(manager)
    assert client.get(reverse("studio:my_tasks") + "?nv=abc&ngay=xx").status_code == 200
    assert client.get(reverse("studio:videos") + "?kenh=abc&trang-thai=khong-co").status_code == 200
    assert client.get(reverse("studio:schedule") + "?kenh=abc").status_code == 200


def test_calendar_views(client, manager, post, staff):
    client.force_login(manager)
    day = timezone.localtime(post.scheduled_at).date().isoformat()
    for view in ["ngay", "tuan", "thang"]:
        resp = client.get(reverse("studio:schedule") + f"?xem={view}&ngay={day}&kenh={post.channel_id}&nv={staff.pk}")
        assert resp.status_code == 200, view
        assert post in resp.context["posts"]
    week = client.get(reverse("studio:schedule") + f"?xem=tuan&ngay={day}").context
    assert len(week["days"]) == 7 and week["days"][0]["date"].weekday() == 0
    month = client.get(reverse("studio:schedule") + f"?xem=thang&ngay={day}").context
    assert len(month["days"]) % 7 == 0 and all(len(w) == 7 for w in month["weeks"])
    assert client.get(reverse("studio:schedule") + f"?nv={manager.pk}").context["posts"] == []


def test_sidebar_counts_pending(client, staff, post):
    client.force_login(staff)
    resp = client.get(reverse("studio:my_tasks"))
    channels = list(resp.context["sidebar_channels"])
    assert channels[0].pending_today == 1
    assert resp.context["my_pending_count"]() == 1
    assert client.get(reverse("studio:my_tasks") + f"?kenh={post.channel_id}").context["posts"] == [post]
