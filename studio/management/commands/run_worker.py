"""Worker nền: quét Drive, tải file, AI viết caption, xếp lịch, dọn file cũ."""

import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from studio.services import ai, drive, heartbeat, scheduler

logger = logging.getLogger("studio.worker")

LOOP_SECONDS = 30
CLEANUP_INTERVAL = 3600


class Command(BaseCommand):
    help = "Chạy worker nền của Lên Lịch."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Chạy một vòng rồi thoát (dùng cho cron/kiểm tra).")

    def handle(self, *args, **options):
        last_sync = last_cleanup = 0.0
        logger.info("Worker bắt đầu")
        while True:
            close_old_connections()
            now = time.monotonic()
            if options["once"] or now - last_sync >= settings.DRIVE_SYNC_INTERVAL:
                self._step("Quét Drive", drive.sync_all)
                last_sync = now
            self._step("Tải file", drive.download_pending)
            self._step("Viết caption", ai.process_pending_captions)
            self._step("Xếp lịch", scheduler.schedule_all)
            if options["once"] or now - last_cleanup >= CLEANUP_INTERVAL:
                self._step("Dọn file cũ", drive.cleanup_media)
                last_cleanup = now
            try:
                heartbeat.beat()
            except OSError:
                logger.exception("Không ghi được nhịp tim worker")
            if options["once"]:
                return
            time.sleep(LOOP_SECONDS)

    def _step(self, label, func):
        try:
            count = func()
        except Exception:
            logger.exception("%s: lỗi", label)
            return
        if count:
            logger.info("%s: %s", label, count)
