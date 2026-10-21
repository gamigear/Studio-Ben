from datetime import datetime, timedelta

from django.db.models import Count, Q
from django.utils import timezone

from .models import Channel, Post


def sidebar(request):
    """Danh sách kênh + số bài chờ đăng (tới hết hôm nay, gồm cả bài trễ) cho thanh menu trái."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    tz = timezone.get_current_timezone()
    end_of_today = timezone.make_aware(datetime.combine(timezone.localdate(), datetime.min.time()), tz) + timedelta(
        days=1
    )
    pending = Q(posts__status=Post.Status.PENDING, posts__scheduled_at__lt=end_of_today)
    channels = Channel.objects.filter(is_active=True)
    if not user.is_manager:
        channels = channels.filter(assignee=user)
    channels = channels.annotate(pending_today=Count("posts", filter=pending))

    def my_pending_count():
        return Post.objects.filter(assignee=user, status=Post.Status.PENDING, scheduled_at__lt=end_of_today).count()

    return {"sidebar_channels": channels, "my_pending_count": my_pending_count}
