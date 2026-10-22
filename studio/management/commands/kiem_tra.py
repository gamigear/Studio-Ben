"""Kiểm tra cài đặt sau khi triển khai: database, thư mục file, worker, Google Drive, dịch vụ AI, kênh.

Chạy: docker compose exec web python manage.py kiem_tra
"""

import tempfile

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

from studio.models import AIProvider, Channel, User
from studio.services import ai, drive, heartbeat


class Command(BaseCommand):
    help = "Kiểm tra cấu hình Lên Lịch và báo những gì còn thiếu."

    def add_arguments(self, parser):
        parser.add_argument("--bo-qua-ai", action="store_true", help="Không gọi thử dịch vụ AI.")
        parser.add_argument("--bo-qua-drive", action="store_true", help="Không gọi thử Google Drive.")

    def handle(self, *args, **options):
        self.failures = 0
        self.ok_count = 0

        self.section("Hệ thống")
        try:
            connection.ensure_connection()
            self.ok(f"Database kết nối được ({connection.vendor})")
        except Exception as exc:  # noqa: BLE001 - in lỗi kết nối ra cho người cài
            self.fail(f"Không kết nối được database: {exc}")
            return
        if User.objects.filter(is_superuser=True).exists():
            self.ok("Đã có tài khoản quản trị")
        else:
            self.fail("Chưa có tài khoản quản trị: chạy `python manage.py createsuperuser`")
        if settings.APP_URL.startswith("https://"):
            self.ok(f"APP_URL = {settings.APP_URL}")
        else:
            self.warn(f"APP_URL = {settings.APP_URL} (chưa HTTPS: nút Chia sẻ / Copy trên điện thoại sẽ không chạy)")
        try:
            settings.MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=settings.MEDIA_ROOT):
                pass
            self.ok(f"Ghi được thư mục file: {settings.MEDIA_ROOT}")
        except OSError as exc:
            self.fail(f"Không ghi được thư mục file {settings.MEDIA_ROOT}: {exc}")
        age = heartbeat.seconds_since_beat()
        if heartbeat.worker_ok():
            self.ok(f"Worker đang chạy (lần cuối {age} giây trước)")
        elif age is None:
            self.fail("Worker chưa chạy lần nào: kiểm tra `docker compose logs worker`")
        else:
            self.fail(f"Worker đã dừng {age} giây: kiểm tra `docker compose logs worker`")

        self.section("Google Drive")
        try:
            client = drive.get_client()
        except drive.DriveError as exc:
            client = None
            self.fail(str(exc))
        if client is None:
            self.warn(
                "Chưa cấu hình service account (secrets/google-service-account.json). Kênh sẽ chỉ nhận nội dung tải lên / API."
            )
        else:
            self.ok(f"Service account: {drive.service_account_email()}")
            channels = Channel.objects.filter(is_active=True).exclude(drive_folder_id="")
            if not channels:
                self.warn("Chưa kênh nào gắn thư mục Drive")
            for channel in channels if not options["bo_qua_drive"] else []:
                try:
                    files = client.list_folder(channel.drive_folder_id)
                    self.ok(f"{channel.name}: đọc được thư mục ({len(files)} mục)")
                except drive.DriveError as exc:
                    self.fail(f"{channel.name}: {exc}")

        self.section("Dịch vụ AI")
        providers = list(AIProvider.objects.all())
        default = next((p for p in providers if p.is_default), None)
        if not providers:
            self.warn("Chưa có dịch vụ AI: vào Cài đặt → Thêm dịch vụ AI (nội dung sẽ chờ caption)")
        elif default is None:
            self.warn("Chưa chọn dịch vụ AI mặc định")
        for provider in providers if not options["bo_qua_ai"] else []:
            try:
                reply = ai.test_provider(provider)
                self.ok(f"{provider.name} ({provider.model}): {reply[:60]}")
            except ai.AIError as exc:
                self.fail(f"{provider.name}: {exc}")

        self.section("Kênh")
        channels = list(Channel.objects.filter(is_active=True).select_related("assignee"))
        if not channels:
            self.warn("Chưa có kênh nào")
        for channel in channels:
            problems = []
            if not channel.get_post_times():
                problems.append("chưa đặt giờ đăng")
            if not channel.assignee:
                problems.append("chưa giao nhân viên")
            label = f"{channel.name} ({channel.get_platform_display()})"
            if problems:
                self.warn(f"{label}: {', '.join(problems)}")
            else:
                self.ok(f"{label}: {len(channel.get_post_times())} bài/ngày, giao cho {channel.assignee}")

        self.stdout.write("")
        if self.failures:
            self.stdout.write(self.style.ERROR(f"Còn {self.failures} lỗi cần sửa ({self.ok_count} mục ổn)."))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS(f"Mọi thứ sẵn sàng ({self.ok_count} mục ổn)."))

    def section(self, title):
        self.stdout.write(f"\n== {title} ==")

    def ok(self, msg):
        self.ok_count += 1
        self.stdout.write(self.style.SUCCESS("  ✓ ") + msg)

    def warn(self, msg):
        self.stdout.write(self.style.WARNING("  ! ") + msg)

    def fail(self, msg):
        self.failures += 1
        self.stdout.write(self.style.ERROR("  ✗ ") + msg)
