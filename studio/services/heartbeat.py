"""Nhịp tim của worker: worker ghi thời điểm vào một file trong MEDIA_ROOT (volume dùng chung với web),
để trang Tổng quan cảnh báo khi worker không chạy."""

import time
from pathlib import Path

from django.conf import settings

STALE_SECONDS = 180


def _path() -> Path:
    return Path(settings.MEDIA_ROOT) / ".worker-heartbeat"


def beat() -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(int(time.time())))


def seconds_since_beat() -> int | None:
    """Số giây kể từ lần worker chạy gần nhất; None nếu worker chưa từng chạy."""
    try:
        return int(time.time() - int(_path().read_text().strip()))
    except (OSError, ValueError):
        return None


def worker_ok() -> bool:
    age = seconds_since_beat()
    return age is not None and age < STALE_SECONDS
