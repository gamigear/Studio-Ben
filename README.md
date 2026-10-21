# Lên Lịch (Studio-Ben)

Công cụ nội bộ để vận hành nhiều kênh TikTok (sau này thêm Facebook, Instagram, YouTube) theo cách **bán tự động**:
máy lo phần lặp lại, còn bước đăng cuối cùng vẫn do người làm trên app thật, để giữ hiệu quả phân phối của bài đăng.

```
Google Drive / tải lên / agent ──► Kho video ──► AI viết caption ──► Tự xếp lịch ──► Nhân viên đăng trên app ──► Đánh dấu đã đăng
```

- **Nhận video**: mỗi kênh một thư mục Google Drive; video mới tự vào kho (kèm file `.txt` cùng tên làm mô tả/kịch bản).
- **AI viết caption** theo hướng dẫn riêng từng kênh, dùng GPT hoặc bất kỳ dịch vụ tương thích OpenAI.
- **Tự xếp lịch** video vào các khung giờ đăng của từng kênh (2–5 bài/ngày…).
- **Việc của tôi** trên điện thoại: đến giờ, nhân viên bấm *Chia sẻ sang TikTok* → video mở thẳng trong app TikTok,
  caption đã được copy sẵn → chọn nhạc, dán caption, đăng → bấm *Đã đăng*.
- **Tổng quan** cho quản lý: ai đăng được bao nhiêu, bài nào trễ, kho mỗi kênh còn đủ cho mấy ngày.
- **API cho agent** để các quy trình tự động (AI, Douyin…) đẩy video kèm caption thẳng vào kho.

## 1. Cài đặt trên máy chủ

Yêu cầu: máy chạy Linux/macOS/Windows có **Docker** và **Docker Compose**.

```bash
git clone https://github.com/gamigear/Studio-Ben.git
cd Studio-Ben
cp .env.example .env
```

Mở `.env` và điền:

| Biến | Giá trị |
|---|---|
| `SECRET_KEY` | Chuỗi ngẫu nhiên: `python3 -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `FIELD_ENCRYPTION_KEY` | Một chuỗi ngẫu nhiên khác. **Đặt một lần, không đổi**, vì đổi thì không đọc được các API key AI đã lưu. |
| `POSTGRES_PASSWORD` | Mật khẩu database (tự đặt) |
| `APP_URL`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` | Đã điền sẵn cho `lenlich.tiepdi.com` |

Chạy:

```bash
docker compose up -d --build
docker compose exec web python manage.py createsuperuser   # tạo tài khoản quản lý đầu tiên
```

Mở `http://<ip-máy-chủ>:8000` để kiểm tra. Có 3 dịch vụ: `web` (giao diện + API), `worker` (quét Drive, tải video,
viết caption, xếp lịch, dọn file cũ) và `db` (PostgreSQL). Video lưu trong volume `media_data`; file đã đăng được tự xóa
sau `MEDIA_RETENTION_DAYS` ngày (mặc định 7) để không đầy ổ.

Cập nhật phiên bản mới: `git pull && docker compose up -d --build`.

## 2. Đưa lên tên miền lenlich.tiepdi.com

Nhân viên dùng điện thoại (4G/wifi bất kỳ) nên app cần địa chỉ công khai có **HTTPS**. Nút *Chia sẻ sang TikTok* và
*Copy caption* chỉ chạy trên HTTPS. Máy chủ đang ở sau Tailscale (không mở cổng ra internet), nên cách gọn nhất là
**Cloudflare Tunnel**: máy chủ chủ động kết nối ra Cloudflare, không cần mở cổng router.

1. Tên miền `tiepdi.com` cần dùng DNS của Cloudflare (nếu chưa: thêm site vào Cloudflare, đổi nameserver ở nhà cung cấp tên miền).
2. Cloudflare Zero Trust → **Networks → Tunnels → Create a tunnel** (loại *Cloudflared*), đặt tên `lenlich`, copy **token**.
3. Trong tunnel, thêm **Public Hostname**: `lenlich.tiepdi.com` → Service `HTTP` → `web:8000`.
4. Dán token vào `CLOUDFLARE_TUNNEL_TOKEN` trong `.env`, rồi chạy:
   ```bash
   docker compose --profile tunnel up -d --build
   ```

Lưu ý:
- Khi `APP_URL` là `https://...`, cookie đăng nhập chỉ gửi qua HTTPS. Hãy luôn dùng `https://lenlich.tiepdi.com`,
  kể cả trong mạng Tailscale.
- Cloudflare gói miễn phí giới hạn **100 MB mỗi lần tải lên** qua web/API. Video lớn hơn hãy đẩy vào thư mục Google Drive của kênh.

## 3. Kết nối Google Drive

App đọc Drive bằng một *service account* (tài khoản máy), chỉ có quyền đọc các thư mục bạn chia sẻ cho nó.

1. Vào [Google Cloud Console](https://console.cloud.google.com/) → tạo project (ví dụ `lenlich`).
2. **APIs & Services → Library** → bật **Google Drive API**.
3. **IAM & Admin → Service Accounts → Create service account** (không cần cấp role) → vào tab **Keys → Add key → JSON**.
4. Lưu file JSON tải về thành `secrets/google-service-account.json` trong thư mục dự án (thư mục `secrets/` không bị đưa lên git).
5. Khởi động lại: `docker compose restart web worker`. Trang **Cài đặt** sẽ hiện email của service account
   (dạng `...@....iam.gserviceaccount.com`).
6. Với mỗi kênh: trên Google Drive, **chia sẻ** thư mục của kênh cho email đó với quyền **Người xem**, rồi dán link
   thư mục vào ô *ID thư mục Google Drive* của kênh.

**Quy ước thư mục**

```
Kênh Mẹo vặt/
├── meo-tay-dau-mo.mp4
├── meo-tay-dau-mo.txt     ← (không bắt buộc) mô tả / kịch bản để AI viết caption
└── meo-xep-quan-ao.mp4
```

- Mỗi file video là một bài. Video được xếp lịch theo thứ tự thời gian đẩy lên Drive (cũ trước).
- Worker quét Drive mỗi 5 phút (`DRIVE_SYNC_INTERVAL`), hoặc bấm **Quét Drive** ở trang Kênh.
- Xóa video trong app không xóa trên Drive, và lần quét sau cũng không thêm lại.

## 4. AI viết caption

**Cài đặt → Thêm dịch vụ AI**: nhập API key, base URL và model. Dùng được OpenAI (GPT) và mọi dịch vụ tương thích
OpenAI Chat Completions (OpenRouter, DeepSeek, Gemini…). Bấm **Thử** để kiểm tra kết nối. API key được mã hóa
(AES-256-GCM) trước khi lưu vào database.

Tùy chỉnh nội dung theo hai lớp:
- **Hướng dẫn chung** của dịch vụ AI: áp dụng cho mọi kênh dùng dịch vụ đó (để trống thì dùng hướng dẫn mặc định).
- **Hướng dẫn viết caption** của từng kênh: giọng văn, độ dài, lời kêu gọi, caption mẫu… Mỗi kênh cũng có thể chọn
  một dịch vụ/model AI riêng.

AI nhận: tên kênh, chủ đề, hướng dẫn, hashtag mặc định, tên video và nội dung file `.txt` đi kèm. Nếu AI lỗi, video
được thử lại tối đa 3 lần rồi hiện ở **Tổng quan → Cần xử lý**. Kênh tắt *AI tự viết caption* thì video vào kho với
caption là hashtag mặc định, để người sửa tay.

## 5. API cho agent

Tạo khóa ở **Cài đặt → API key cho agent** (khóa chỉ hiện một lần). Tài liệu đầy đủ, có thể thử trực tiếp:
`https://lenlich.tiepdi.com/api/v1/docs`.

```bash
TOKEN="lenlich_..."
BASE="https://lenlich.tiepdi.com/api/v1"

# Danh sách kênh (kèm hướng dẫn nội dung, giờ đăng)
curl -H "Authorization: Bearer $TOKEN" $BASE/channels

# Đẩy video vào kho. Có caption thì dùng luôn; bỏ trống thì AI viết theo hướng dẫn của kênh.
curl -H "Authorization: Bearer $TOKEN" -X POST $BASE/videos \
  -F channel_id=1 -F file=@video.mp4 -F notes="Kịch bản: ..." -F caption=""

# Sửa caption (bài đang chờ đăng của video cũng được cập nhật)
curl -H "Authorization: Bearer $TOKEN" -X PATCH $BASE/videos/12 \
  -H "Content-Type: application/json" -d '{"caption": "Caption mới #fyp"}'

# Agent tinh chỉnh hướng dẫn viết caption của kênh
curl -H "Authorization: Bearer $TOKEN" -X PATCH $BASE/channels/1 \
  -H "Content-Type: application/json" -d '{"content_instructions": "Giọng hài hước, câu đầu là câu hỏi"}'

# Lịch đăng một ngày
curl -H "Authorization: Bearer $TOKEN" "$BASE/posts?day=2026-10-21&status=pending"
```

| Endpoint | Việc |
|---|---|
| `GET /channels`, `GET/PATCH /channels/{id}` | Đọc kênh; sửa chủ đề, hướng dẫn caption, hashtag |
| `GET /videos`, `POST /videos`, `GET/PATCH /videos/{id}` | Đọc/đẩy video, sửa tiêu đề, mô tả, caption |
| `POST /videos/{id}/regenerate-caption` | Cho AI viết lại caption ngay |
| `GET /posts`, `PATCH /posts/{id}` | Xem lịch theo ngày; đổi giờ hoặc caption của bài đang chờ |

## 6. Hằng ngày

**Quản lý**
1. **Kênh → Thêm kênh**: tên, @tài khoản, giờ đăng (ví dụ `08:00, 11:30, 19:00`), nhân viên phụ trách, điện thoại, thư mục Drive, hướng dẫn caption.
2. Thêm nhân viên ở **Cài đặt → trang quản trị** (`/quan-tri/`, đăng nhập bằng tài khoản tạo từ `createsuperuser`):
   chọn vai trò *Nhân viên*, hoặc *Quản lý* cho người được xem mọi thứ. Người quản lý nào cần tự thêm nhân viên thì
   tick thêm *Staff status* và cấp quyền quản lý người dùng.
3. Theo dõi **Tổng quan**: tiến độ từng người, bài trễ, kho mỗi kênh còn đủ mấy ngày (đỏ là sắp hết video).
4. **Lịch đăng**: xem/sửa bài theo ngày, đổi giờ hoặc người đăng, gỡ bài (video quay lại kho).

**Nhân viên (trên điện thoại)**
1. Mở `https://lenlich.tiepdi.com` → đăng nhập → *Thêm vào màn hình chính* để mở như app.
2. Trang **Việc của tôi** liệt kê bài hôm nay theo giờ; bài trễ có viền đỏ, bài đến giờ có viền vàng.
3. Đến giờ: bấm **Chia sẻ sang TikTok** (video được tải về máy) → bấm lần nữa **Mở TikTok** (caption được copy, bảng
   chia sẻ mở ra) → chọn **TikTok** → chọn nhạc, dán caption, đăng.
   Nếu máy không hỗ trợ chia sẻ: dùng **Tải video** + **Copy caption** rồi tự mở TikTok.
4. Bấm **Đã đăng** (có thể dán link bài). Bấm nhầm thì **Hoàn tác**. Video lỗi thì **Bỏ qua** kèm lý do.

## 7. Phát triển

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
DEBUG=1 python manage.py migrate
DEBUG=1 python manage.py createsuperuser
DEBUG=1 python manage.py runserver          # giao diện
DEBUG=1 python manage.py run_worker         # worker (cửa sổ khác); --once để chạy một vòng
pytest                                      # test
ruff check . && ruff format --check .       # lint
```

Cấu trúc:

```
config/                 cấu hình Django
studio/models.py        Kênh, Video, Bài đăng, Dịch vụ AI, API key
studio/services/        drive.py (Google Drive), ai.py (caption), scheduler.py (xếp lịch)
studio/views/           giao diện tiếng Việt
studio/api.py           REST API cho agent (django-ninja)
studio/management/commands/run_worker.py   worker nền
tests/                  pytest
```

## 8. Lộ trình

- [x] **Giai đoạn A**: Drive → kho → AI caption → xếp lịch → nhân viên đăng bằng app thật → theo dõi tiến độ.
- [ ] **Giai đoạn B**: kết nối TikTok API chính thức (Login Kit + Content Posting API, chế độ *Upload to Inbox*):
      video tự vào hộp nháp trong app TikTok của đúng tài khoản. Cần trang giới thiệu, chính sách quyền riêng tư,
      điều khoản, video demo để TikTok duyệt app. So sánh hiệu quả với cách đăng hiện tại trên vài tài khoản trước khi áp dụng rộng.
- [ ] Thống kê view/tương tác từng video (TikTok `video.list`), so sánh theo nguồn video, khung giờ, nhân viên.
- [ ] Facebook, Instagram, YouTube.
- [ ] Hỗ trợ dựng video tự quay: cắt khoảng lặng, phụ đề, tách nhiều phiên bản.
