#!/usr/bin/env bash
# Cài đặt / cập nhật Lên Lịch trên máy chủ bằng Docker.
#
#   ./scripts/cai-dat.sh                      # tên miền mặc định lenlich.tiepdi.com
#   ./scripts/cai-dat.sh --domain abc.vn      # tên miền khác
#   DJANGO_SUPERUSER_USERNAME=quanly DJANGO_SUPERUSER_PASSWORD=... ./scripts/cai-dat.sh   # không hỏi tài khoản
#
# Chạy lại bất cứ lúc nào để cập nhật: .env đã có thì giữ nguyên.
set -euo pipefail

DOMAIN="lenlich.tiepdi.com"
while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "Tham số không hợp lệ: $1"; exit 1 ;;
  esac
done

cd "$(dirname "$0")/.."

say() { printf '\n\033[1;33m==> %s\033[0m\n' "$1"; }
die() { printf '\033[1;31mLỖI: %s\033[0m\n' "$1"; exit 1; }
random() { head -c 48 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
# Đặt KEY=VALUE trong .env (thay dòng cũ nếu có), không phụ thuộc sed của Linux/macOS.
set_env() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp)"
  awk -v k="$key" -v v="$value" 'BEGIN{done=0} $0 ~ "^"k"=" {print k"="v; done=1; next} {print} END{if(!done) print k"="v}' .env > "$tmp"
  mv "$tmp" .env
}
env_value() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }

say "Kiểm tra Docker"
command -v docker >/dev/null || die "Chưa cài Docker. Xem https://docs.docker.com/engine/install/"
docker compose version >/dev/null 2>&1 || die "Chưa có Docker Compose (lệnh 'docker compose')."
docker info >/dev/null 2>&1 || die "Docker chưa chạy hoặc user hiện tại không có quyền (thử thêm sudo)."

if [ ! -f .env ]; then
  say "Tạo .env với khóa ngẫu nhiên cho $DOMAIN"
  cp .env.example .env
  set_env SECRET_KEY "$(random)"
  set_env FIELD_ENCRYPTION_KEY "$(random)"
  set_env POSTGRES_PASSWORD "$(random | cut -c1-32)"
  set_env APP_URL "https://$DOMAIN"
  set_env ALLOWED_HOSTS "$DOMAIN,localhost,127.0.0.1"
  set_env CSRF_TRUSTED_ORIGINS "https://$DOMAIN"
  echo "Đã tạo .env. Hãy sao lưu file này: mất FIELD_ENCRYPTION_KEY thì phải nhập lại API key AI."
else
  echo ".env đã có, giữ nguyên."
fi

mkdir -p secrets
if [ -f secrets/google-service-account.json ]; then
  echo "Đã có secrets/google-service-account.json (Google Drive)."
else
  echo "Chưa có secrets/google-service-account.json: kênh chưa đọc được Google Drive (xem README mục 3)."
fi

PROFILE=()
if [ -n "$(env_value CLOUDFLARE_TUNNEL_TOKEN)" ]; then
  PROFILE=(--profile tunnel)
  echo "Có CLOUDFLARE_TUNNEL_TOKEN: chạy kèm Cloudflare Tunnel cho https://$DOMAIN"
else
  echo "Chưa có CLOUDFLARE_TUNNEL_TOKEN: app chỉ mở ở cổng 8000 trong mạng nội bộ / Tailscale (xem README mục 2)."
fi

say "Build và khởi động (lần đầu mất vài phút)"
docker compose ${PROFILE[@]+"${PROFILE[@]}"} up -d --build

say "Chờ web sẵn sàng"
for _ in $(seq 1 60); do
  if docker compose exec -T web python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/dang-nhap/').status==200 else 1)" >/dev/null 2>&1; then
    echo "Web đã chạy."
    break
  fi
  sleep 3
done

if ! docker compose exec -T web python manage.py shell -c "from studio.models import User; import sys; sys.exit(0 if User.objects.filter(is_superuser=True).exists() else 1)" >/dev/null 2>&1; then
  say "Tạo tài khoản quản lý đầu tiên"
  if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
    # Không hỏi: lấy tên + mật khẩu từ biến môi trường.
    docker compose exec -T -e DJANGO_SUPERUSER_USERNAME -e DJANGO_SUPERUSER_PASSWORD \
      -e DJANGO_SUPERUSER_EMAIL="${DJANGO_SUPERUSER_EMAIL:-}" web python manage.py createsuperuser --noinput
  else
    docker compose exec web python manage.py createsuperuser
  fi
fi

say "Kiểm tra cài đặt"
docker compose exec -T web python manage.py kiem_tra --bo-qua-ai || true

cat <<MSG

Xong. Mở:  https://$DOMAIN
  Chưa có tên miền? Thử trong mạng nội bộ / Tailscale: trong .env đặt APP_URL=http://<ip-máy-chủ>:8000,
  thêm IP đó vào ALLOWED_HOSTS và CSRF_TRUSTED_ORIGINS, rồi chạy lại script này. (Nút Chia sẻ / Copy trên
  điện thoại chỉ chạy khi có HTTPS, nên nhân viên cần dùng tên miền.)
- Cài đặt → Thêm dịch vụ AI (API key OpenAI) → bấm "Thử".
- Kênh → Thêm kênh (TikTok / Facebook / Instagram), dán link thư mục Drive, đặt giờ đăng, giao nhân viên.
- Kiểm tra lại bất cứ lúc nào:  docker compose exec web python manage.py kiem_tra
- Xem log:                      docker compose logs -f web worker
MSG
