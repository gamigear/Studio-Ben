"""Cấu hình Lên Lịch (Studio-Ben).

Mọi giá trị đọc từ biến môi trường; xem `.env.example`.
"""

import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = env_bool("DEBUG", False)
SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError("Thiếu SECRET_KEY. Đặt biến môi trường SECRET_KEY (chuỗi ngẫu nhiên dài).")
    SECRET_KEY = "dev-only-insecure-key"

# Khóa mã hóa API key lưu trong DB. Mặc định dùng SECRET_KEY; đặt riêng để có thể
# đổi SECRET_KEY mà không mất các API key đã lưu.
FIELD_ENCRYPTION_KEY = os.environ.get("FIELD_ENCRYPTION_KEY", SECRET_KEY)

APP_URL = os.environ.get("APP_URL", "http://localhost:8000").rstrip("/")
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", APP_URL)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "studio",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "studio.context_processors.sidebar",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": dj_database_url.parse(
        os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
        conn_max_age=60,
    )
}

AUTH_USER_MODEL = "studio.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]
LOGIN_URL = "studio:login"
LOGIN_REDIRECT_URL = "studio:home"
LOGOUT_REDIRECT_URL = "studio:login"

LANGUAGE_CODE = "vi"
TIME_ZONE = os.environ.get("TIME_ZONE", "Asia/Ho_Chi_Minh")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
if DEBUG:
    STORAGES["staticfiles"] = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}

# Video lưu trên ổ đĩa máy chủ; chỉ phát qua view có kiểm tra quyền, không public.
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

if not DEBUG:
    SESSION_COOKIE_SECURE = APP_URL.startswith("https://")
    CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
    # Chạy sau Cloudflare Tunnel / reverse proxy: tin header X-Forwarded-Proto.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- Nghiệp vụ -------------------------------------------------------------

# Google Drive: đường dẫn tới file JSON của service account, hoặc nội dung JSON.
GOOGLE_SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")

# Worker: chu kỳ quét Drive (giây), số ngày xếp lịch trước, số ngày giữ file sau khi đăng.
DRIVE_SYNC_INTERVAL = int(os.environ.get("DRIVE_SYNC_INTERVAL", "300"))
SCHEDULE_DAYS_AHEAD = int(os.environ.get("SCHEDULE_DAYS_AHEAD", "2"))
MEDIA_RETENTION_DAYS = int(os.environ.get("MEDIA_RETENTION_DAYS", "7"))
CAPTION_MAX_ATTEMPTS = int(os.environ.get("CAPTION_MAX_ATTEMPTS", "3"))
# Bài chưa đăng quá số phút này sau giờ hẹn thì tính là trễ.
OVERDUE_GRACE_MINUTES = int(os.environ.get("OVERDUE_GRACE_MINUTES", "15"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
    # httpx ghi mọi request ở mức INFO, quá ồn cho worker.
    "loggers": {"httpx": {"level": "WARNING"}},
}
