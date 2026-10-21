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
from ..models import Channel, Post, Video
from ..services import scheduler
from .common import ensure, manager_required, serve_video

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

    base = Post.objects.filter(assignee=staff).select_related("channel", "video")
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
            "overdue": overdue,
            "posts": posts,
            "pending_count": len(pending) + len(overdue),
            "done_count": sum(1 for p in posts if p.status == Post.Status.POSTED),
        },
    )


@login_required
def post_video(request, pk):
    post = get_object_or_404(Post.objects.select_related("video"), pk=pk)
    ensure(post.can_handle(request.user))
    return serve_video(request, post.video, as_attachment=request.GET.get("tai") == "1")


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


@manager_required
def schedule_list(request):
    day = _parse_day(request.GET.get("ngay"))
    start, end = _day_range(day)
    posts = Post.objects.filter(scheduled_at__gte=start, scheduled_at__lt=end).select_related(
        "channel", "assignee", "video"
    )
    channel_id = request.GET.get("kenh", "")
    if channel_id.isdigit():
        posts = posts.filter(channel_id=channel_id)
    return render(
        request,
        "studio/schedule.html",
        {
            "day": day,
            "prev_day": day - timedelta(days=1),
            "next_day": day + timedelta(days=1),
            "posts": posts,
            "channels": Channel.objects.filter(is_active=True),
            "channel_id": channel_id,
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
