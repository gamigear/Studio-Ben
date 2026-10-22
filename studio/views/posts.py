from datetime import date, datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..forms import MarkPostedForm, PostEditForm
from ..models import Channel, MediaFile, Post, Video
from ..services import heartbeat, scheduler
from .common import ensure, manager_required, serve_media

User = get_user_model()


def _parse_day(value: str | None) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date() if value else timezone.localdate()
    except ValueError:
        return timezone.localdate()


def _day_range(day: date):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, datetime.min.time()), tz)
    return start, start + timedelta(days=1)


@login_required
def home(request):
    return redirect("studio:dashboard" if request.user.is_manager else "studio:my_tasks")


@login_required
def my_tasks(request):
    day = _parse_day(request.GET.get("ngay"))
    start, end = _day_range(day)
    staff = request.user
    staff_choices = None
    if request.user.is_manager:
        staff_choices = User.objects.filter(is_active=True).order_by("first_name", "username")
        if request.GET.get("nv", "").isdigit():
            staff = get_object_or_404(User, pk=request.GET["nv"])

    base = Post.objects.filter(assignee=staff).select_related("channel", "video").prefetch_related("video__media")
    channel_id = request.GET.get("kenh", "")
    if channel_id.isdigit():
        base = base.filter(channel_id=channel_id)
    posts = list(base.filter(scheduled_at__gte=start, scheduled_at__lt=end))
    # Bài các ngày trước chưa đăng vẫn hiện ở đầu danh sách hôm nay.
    overdue = (
        list(base.filter(status=Post.Status.PENDING, scheduled_at__lt=start)) if day == timezone.localdate() else []
    )
    pending = [p for p in posts if p.status == Post.Status.PENDING]
    return render(
        request,
        "studio/my_tasks.html",
        {
            "day": day,
            "prev_day": day - timedelta(days=1),
            "next_day": day + timedelta(days=1),
            "is_today": day == timezone.localdate(),
            "staff": staff,
            "staff_choices": staff_choices,
            "channel": Channel.objects.filter(pk=channel_id).first() if channel_id.isdigit() else None,
            "overdue": overdue,
            "posts": posts,
            "pending_count": len(pending) + len(overdue),
            "done_count": sum(1 for p in posts if p.status == Post.Status.POSTED),
        },
    )


@login_required
def post_media(request, pk, media_pk):
    post = get_object_or_404(Post, pk=pk)
    ensure(post.can_handle(request.user))
    media = get_object_or_404(MediaFile, pk=media_pk, content_id=post.video_id)
    return serve_media(request, media, as_attachment=request.GET.get("tai") == "1")


def _back(request, fallback="studio:my_tasks"):
    nxt = request.POST.get("next") or ""
    return redirect(nxt) if nxt.startswith("/") and not nxt.startswith("//") else redirect(fallback)


@login_required
@require_POST
def mark_posted(request, pk):
    post = get_object_or_404(Post, pk=pk)
    ensure(post.can_handle(request.user))
    form = MarkPostedForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Link bài đăng không hợp lệ.")
        return _back(request)
    post.status = Post.Status.POSTED
    post.posted_at = timezone.now()
    post.posted_by = request.user
    post.post_url = form.cleaned_data["post_url"] or post.post_url
    post.save(update_fields=["status", "posted_at", "posted_by", "post_url"])
    messages.success(
        request, f"Đã đánh dấu đăng: {post.channel.name} lúc {timezone.localtime(post.scheduled_at):%H:%M}."
    )
    return _back(request)


@login_required
@require_POST
def skip_post(request, pk):
    post = get_object_or_404(Post, pk=pk)
    ensure(post.can_handle(request.user))
    post.status = Post.Status.SKIPPED
    post.note = request.POST.get("note", "").strip() or post.note
    post.save(update_fields=["status", "note"])
    messages.info(request, "Đã bỏ qua bài này.")
    return _back(request)


@login_required
@require_POST
def undo_post(request, pk):
    post = get_object_or_404(Post, pk=pk)
    ensure(post.can_handle(request.user))
    post.status = Post.Status.PENDING
    post.posted_at = None
    post.posted_by = None
    post.save(update_fields=["status", "posted_at", "posted_by"])
    messages.info(request, "Đã chuyển bài về trạng thái chờ đăng.")
    return _back(request)


@manager_required
def dashboard(request):
    today = timezone.localdate()
    start, end = _day_range(today)
    now = timezone.now()
    grace = now - timedelta(minutes=settings.OVERDUE_GRACE_MINUTES)
    today_posts = Post.objects.filter(scheduled_at__gte=start, scheduled_at__lt=end)

    staff_rows = (
        User.objects.filter(is_active=True)
        .annotate(
            total=Count("assigned_posts", filter=Q(assigned_posts__in=today_posts)),
            done=Count(
                "assigned_posts", filter=Q(assigned_posts__in=today_posts, assigned_posts__status=Post.Status.POSTED)
            ),
            late=Count(
                "assigned_posts",
                filter=Q(assigned_posts__status=Post.Status.PENDING, assigned_posts__scheduled_at__lt=grace),
            ),
        )
        .filter(Q(total__gt=0) | Q(late__gt=0))
        .order_by("first_name", "username")
    )

    channels = list(
        Channel.objects.filter(is_active=True)
        .select_related("assignee")
        .annotate(
            ready=Count(
                "videos",
                filter=Q(
                    videos__file_status=Video.FileStatus.READY,
                    videos__caption_status__in=Video.READY_CAPTION_STATUSES,
                    videos__posts__isnull=True,
                    videos__is_archived=False,
                ),
                distinct=True,
            ),
            waiting=Count(
                "videos",
                filter=Q(videos__posts__isnull=True, videos__is_archived=False)
                & (
                    ~Q(videos__file_status=Video.FileStatus.READY)
                    | ~Q(videos__caption_status__in=Video.READY_CAPTION_STATUSES)
                ),
                distinct=True,
            ),
            today_total=Count("posts", filter=Q(posts__in=today_posts), distinct=True),
            today_done=Count("posts", filter=Q(posts__in=today_posts, posts__status=Post.Status.POSTED), distinct=True),
        )
    )
    for ch in channels:
        per_day = len(ch.get_post_times())
        ch.days_left = round(ch.ready / per_day, 1) if per_day else None

    late_posts = (
        Post.objects.filter(status=Post.Status.PENDING, scheduled_at__lt=grace)
        .select_related("channel", "assignee")
        .order_by("scheduled_at")[:50]
    )
    totals = today_posts.aggregate(
        total=Count("id"),
        done=Count("id", filter=Q(status=Post.Status.POSTED)),
        skipped=Count("id", filter=Q(status=Post.Status.SKIPPED)),
    )
    problems = {
        "caption_failed": Video.objects.filter(caption_status=Video.CaptionStatus.FAILED, is_archived=False).count(),
        "file_failed": Video.objects.filter(file_status=Video.FileStatus.FAILED, is_archived=False).count(),
        "drive_errors": [c for c in channels if c.drive_error],
        "worker_age": heartbeat.seconds_since_beat(),
        "worker_ok": heartbeat.worker_ok(),
    }
    return render(
        request,
        "studio/dashboard.html",
        {
            "today": today,
            "totals": totals,
            "staff_rows": staff_rows,
            "channels": channels,
            "late_posts": late_posts,
            "problems": problems,
        },
    )


WEEKDAY_LABELS = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "CN"]
VIEWS = {"ngay": "Ngày", "tuan": "Tuần", "thang": "Tháng"}


def _calendar_range(view: str, anchor: date) -> tuple[date, date, date, date]:
    """Trả về (ngày đầu, ngày cuối + 1, mốc trước, mốc sau) của khung lịch đang xem."""
    if view == "ngay":
        return anchor, anchor + timedelta(days=1), anchor - timedelta(days=1), anchor + timedelta(days=1)
    if view == "thang":
        first = anchor.replace(day=1)
        next_month = (first + timedelta(days=32)).replace(day=1)
        prev_month = (first - timedelta(days=1)).replace(day=1)
        grid_start = first - timedelta(days=first.weekday())
        grid_end = next_month + timedelta(days=(7 - next_month.weekday()) % 7)
        return grid_start, grid_end, prev_month, next_month
    week_start = anchor - timedelta(days=anchor.weekday())
    return week_start, week_start + timedelta(days=7), week_start - timedelta(days=7), week_start + timedelta(days=7)


@manager_required
def schedule_list(request):
    view = request.GET.get("xem") if request.GET.get("xem") in VIEWS else "tuan"
    anchor = _parse_day(request.GET.get("ngay"))
    first, last, prev_anchor, next_anchor = _calendar_range(view, anchor)
    range_start, _ = _day_range(first)
    range_end, _ = _day_range(last)

    posts = Post.objects.filter(scheduled_at__gte=range_start, scheduled_at__lt=range_end).select_related(
        "channel", "assignee", "video"
    )
    channel_id = request.GET.get("kenh", "")
    if channel_id.isdigit():
        posts = posts.filter(channel_id=channel_id)
    staff_id = request.GET.get("nv", "")
    if staff_id.isdigit():
        posts = posts.filter(assignee_id=staff_id)

    by_day: dict[date, list[Post]] = {}
    for post in posts:
        by_day.setdefault(timezone.localtime(post.scheduled_at).date(), []).append(post)
    today = timezone.localdate()
    days = [
        {
            "date": first + timedelta(days=i),
            "posts": by_day.get(first + timedelta(days=i), []),
            "is_today": first + timedelta(days=i) == today,
            "in_month": view != "thang" or (first + timedelta(days=i)).month == anchor.month,
        }
        for i in range((last - first).days)
    ]
    weeks = [days[i : i + 7] for i in range(0, len(days), 7)]

    if view == "ngay":
        title = f"{WEEKDAY_LABELS[anchor.weekday()]}, {anchor:%d/%m/%Y}"
    elif view == "thang":
        title = f"Tháng {anchor.month}/{anchor.year}"
    else:
        title = f"{first:%d/%m} – {last - timedelta(days=1):%d/%m/%Y}"

    filters = "".join(f"&{k}={v}" for k, v in (("kenh", channel_id), ("nv", staff_id)) if v.isdigit())
    return render(
        request,
        "studio/schedule.html",
        {
            "view": view,
            "views": VIEWS,
            "anchor": anchor,
            "title": title,
            "prev_anchor": prev_anchor,
            "next_anchor": next_anchor,
            "today": today,
            "weekday_labels": WEEKDAY_LABELS,
            "days": days,
            "weeks": weeks,
            "posts": list(posts),
            "filters": filters,
            "channels": Channel.objects.filter(is_active=True),
            "staff_choices": User.objects.filter(is_active=True).order_by("first_name", "username"),
            "channel_id": channel_id,
            "staff_id": staff_id,
        },
    )


@manager_required
@require_POST
def schedule_now(request):
    count = scheduler.schedule_all()
    messages.success(
        request, f"Đã xếp thêm {count} bài vào lịch." if count else "Không có khung giờ trống hoặc video sẵn sàng."
    )
    return _back(request, "studio:schedule")


@manager_required
def post_edit(request, pk):
    post = get_object_or_404(Post.objects.select_related("channel", "video"), pk=pk)
    form = PostEditForm(request.POST or None, instance=post)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Đã lưu bài đăng.")
        return redirect(f"{_schedule_url()}?ngay={timezone.localtime(post.scheduled_at):%Y-%m-%d}")
    return render(request, "studio/post_edit.html", {"post": post, "form": form})


@manager_required
@require_POST
def post_unschedule(request, pk):
    """Gỡ bài khỏi lịch; video quay lại kho để xếp vào khung giờ khác."""
    post = get_object_or_404(Post, pk=pk, status=Post.Status.PENDING)
    day = timezone.localtime(post.scheduled_at)
    post.delete()
    messages.info(request, "Đã gỡ bài khỏi lịch. Video quay lại kho.")
    return redirect(f"{_schedule_url()}?ngay={day:%Y-%m-%d}")


def _schedule_url():
    from django.urls import reverse

    return reverse("studio:schedule")
