"""Tự xếp video sẵn sàng vào các khung giờ đăng của từng kênh."""

from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from ..models import Channel, Post, Video


def slot_datetimes(channel: Channel, start_date, days: int) -> list[datetime]:
    tz = timezone.get_current_timezone()
    times = channel.get_post_times()
    return [
        timezone.make_aware(datetime.combine(start_date + timedelta(days=offset), t), tz)
        for offset in range(days)
        for t in times
    ]


@transaction.atomic
def schedule_channel(channel: Channel, now: datetime | None = None, days: int | None = None) -> int:
    """Điền các khung giờ còn trống (trong tương lai) bằng video cũ nhất chưa xếp. Trả về số bài mới."""
    now = now or timezone.now()
    days = settings.SCHEDULE_DAYS_AHEAD if days is None else days
    slots = [dt for dt in slot_datetimes(channel, timezone.localtime(now).date(), days) if dt > now]
    if not slots:
        return 0
    taken = set(channel.posts.filter(scheduled_at__in=slots).values_list("scheduled_at", flat=True))
    free = [dt for dt in slots if dt not in taken]
    if not free:
        return 0
    videos = list(
        Video.schedulable()
        .filter(channel=channel)
        .select_for_update(of=("self",))
        .order_by("created_at", "id")[: len(free)]
    )
    for dt, video in zip(free, videos, strict=False):
        Post.objects.create(
            channel=channel, video=video, scheduled_at=dt, caption=video.caption, assignee=channel.assignee
        )
    return len(videos)


def schedule_all(now: datetime | None = None) -> int:
    total = 0
    for channel in Channel.objects.filter(is_active=True).exclude(post_times=""):
        total += schedule_channel(channel, now=now)
    return total
