# Lên Lịch (Studio-Ben)

Công cụ nội bộ để vận hành nhiều kênh **TikTok, Facebook Fanpage, Instagram** (và YouTube Shorts) theo cách
**bán tự động**: máy lo phần lặp lại, còn bước đăng cuối cùng vẫn do người làm trên app thật, để giữ hiệu quả phân phối
của bài đăng.

```
Google Drive / tải lên / agent ──► Kho nội dung ──► AI viết caption ──► Tự xếp lịch ──► Nhân viên đăng trên app ──► Đánh dấu đã đăng
```

- **Nhận nội dung**: mỗi kênh một thư mục Google Drive; video, ảnh, album (thư mục con) mới tự vào kho, kèm file
  `.txt` cùng tên làm mô tả / kịch bản. Bài chỉ có chữ thì thêm trong app hoặc qua API.
- **AI viết caption** theo hướng dẫn riêng từng kênh và phong cách từng nền tảng, dùng GPT hoặc dịch vụ tương thích OpenAI.
- **Tự xếp lịch** vào các khung giờ đăng của từng kênh (2–5 bài/ngày…), kèm **dạng đăng** (Reels / Bài viết / Story).
- **Việc của tôi** trên điện thoại: đến giờ, nhân viên bấm *Chia sẻ sang TikTok / Facebook / Instagram* → video hoặc
  ảnh mở thẳng trong app, caption đã được copy sẵn → chọn nhạc, dán caption, đăng → bấm *Đã đăng*.
- **Tổng quan** cho quản lý: ai đăng được bao nhiêu, bài nào trễ, kho mỗi kênh còn đủ cho mấy ngày, worker có chạy không.
- **API cho agent** để các quy trình tự động (AI, Douyin…) đẩy video / ảnh kèm caption thẳng vào kho.

## 1. Cài đặt trên máy chủ

Yêu cầu: máy Linux hoặc macOS có **Docker** (kèm Docker Compose). Máy Windows: dùng Docker Desktop + WSL và chạy
các lệnh dưới trong cửa sổ WSL.

```bash
git clone https://github.com/gamigear/Studio-Ben.git
cd Studio-Ben
./scripts/cai-dat.sh
```

Script sẽ:
1. Kiểm tra Docker.
2. Tạo `.env` với các khóa ngẫu nhiên (`SECRET_KEY`, `FIELD_ENCRYPTION_KEY`, mật khẩu PostgreSQL) cho
   `lenlich.tiepdi.com` (tên miền khác: `./scripts/cai-dat.sh --domain abc.vn`). Nếu `.env` đã có thì giữ nguyên.
   **Sao lưu `.env`**: mất `FIELD_ENCRYPTION_KEY` thì phải nhập lại các API key AI.
3. Build và chạy `db` (PostgreSQL), `web` (giao diện + API, cổng 8000), `worker` (quét Drive, tải file, viết caption,
   xếp lịch, dọn file cũ) và Cloudflare Tunnel nếu `.env` có `CLOUDFLARE_TUNNEL_TOKEN`.
4. Hỏi tên đăng nhập + mật khẩu cho tài khoản quản lý đầu tiên.
5. Chạy `kiem_tra` và in ra những gì còn thiếu.

Chạy lại script bất cứ lúc nào để **cập nhật** sau khi `git pull`. Kiểm tra lại cấu hình:

```bash
docker compose exec web python manage.py kiem_tra      # database, worker, Google Drive từng kênh, dịch vụ AI, kênh
docker compose logs -f web worker                       # xem log
```

**Thử trong mạng nội bộ trước khi có tên miền**: trong `.env` đặt `APP_URL=http://<ip-máy-chủ>:8000`, thêm IP đó
vào `ALLOWED_HOSTS` và `CSRF_TRUSTED_ORIGINS`, rồi chạy lại script. Đăng nhập, thêm kênh, xem lịch đều dùng được; riêng
nút *Chia sẻ* / *Copy caption* trên điện thoại cần HTTPS nên phải chờ có tên miền (mục 2).

File video / ảnh lưu trong volume `media_data`; file đã đăng được tự xóa sau `MEDIA_RETENTION_DAYS` ngày (mặc định 7)
để không đầy ổ.

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
- Chạy `./scripts/cai-dat.sh` sau khi điền token: script tự bật Cloudflare Tunnel.

## 3. Kết nối Google Drive

App đọc Drive bằng một *service account* (tài khoản máy), chỉ có quyền đọc các thư mục bạn chia sẻ cho nó.

1. Vào [Google Cloud Console](https://console.cloud.google.com/) → tạo project (ví dụ `lenlich`).
2. **APIs & Services → Library** → bật **Google Drive API**.
3. **IAM & Admin → Service Accounts → Create service account** (không cần cấp role) → vào tab **Keys → Add key → JSON**.
4. Lưu file JSON tải về thành `secrets/google-service-account.json` trong thư mục dự án (thư mục `secrets/` không bị đưa lên git).
5. Chạy lại `./scripts/cai-dat.sh` (hoặc `docker compose restart web worker`). Trang **Cài đặt** sẽ hiện email của service account
   (dạng `...@....iam.gserviceaccount.com`).
6. Với mỗi kênh: trên Google Drive, **chia sẻ** thư mục của kênh cho email đó với quyền **Người xem**, rồi dán link
   thư mục vào ô *ID thư mục Google Drive* của kênh.

**Quy ước thư mục**

```
Kênh Bếp nhà Ben/
├── canh-chua-ca.mp4           ← 1 video = 1 bài (Reels / TikTok)
├── canh-chua-ca.txt           ← (không bắt buộc) mô tả / kịch bản để AI viết caption
├── thuc-don-tuan.jpg          ← 1 ảnh = 1 bài
├── thuc-don-tuan.txt
└── Album mon ngon cuoi tuan/  ← thư mục con = 1 album / carousel (ảnh xếp theo tên file)
    ├── 1.jpg
    ├── 2.jpg
    ├── 3.jpg
    └── mo-ta.txt              ← file .txt bất kỳ trong thư mục con = mô tả album
```

- Nội dung được xếp lịch theo thứ tự thời gian đẩy lên Drive (cũ trước).
- Album chỉ được nhận khi thư mục con đã **10 phút không có file mới**, để không lấy album đang tải lên dở.
- Worker quét Drive mỗi 5 phút (`DRIVE_SYNC_INTERVAL`), hoặc bấm **Quét Drive** ở trang Kênh.
- **Một thư mục dùng cho nhiều kênh**: dán cùng link thư mục vào kênh TikTok, Fanpage và Instagram, thì mỗi video sẽ
  được xếp lịch trên cả ba kênh, mỗi kênh một caption riêng theo phong cách nền tảng. File chỉ tải về máy chủ một lần.
- Xóa nội dung trong app không xóa trên Drive, và lần quét sau cũng không thêm lại.

## 4. AI viết caption

**Cài đặt → Thêm dịch vụ AI**: nhập API key, base URL và model. Dùng được OpenAI (GPT) và mọi dịch vụ tương thích
OpenAI Chat Completions (OpenRouter, DeepSeek, Gemini…). Bấm **Thử** để kiểm tra kết nối. API key được mã hóa
(AES-256-GCM) trước khi lưu vào database.

Tùy chỉnh nội dung theo hai lớp:
- **Hướng dẫn chung** của dịch vụ AI: áp dụng cho mọi kênh dùng dịch vụ đó (để trống thì dùng hướng dẫn mặc định).
- **Hướng dẫn viết caption** của từng kênh: giọng văn, độ dài, lời kêu gọi, caption mẫu… Mỗi kênh cũng có thể chọn
  một dịch vụ/model AI riêng.

AI nhận: tên kênh, nền tảng (TikTok ngắn, bắt trend; Facebook dài hơn, kể chuyện, ít hashtag; Instagram câu đầu thật
hấp dẫn, 5–15 hashtag), dạng đăng, loại nội dung (video / ảnh / album / chữ), chủ đề, hướng dẫn, hashtag mặc định, tên
nội dung và file `.txt` đi kèm. Nếu AI lỗi, video
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
  -F channel_id=1 -F files=@video.mp4 -F notes="Kịch bản: ..." -F caption=""

# Album nhiều ảnh (lặp lại files=), hoặc bài chỉ có chữ (không gửi files)
curl -H "Authorization: Bearer $TOKEN" -X POST $BASE/videos -F channel_id=2 -F files=@1.jpg -F files=@2.jpg
curl -H "Authorization: Bearer $TOKEN" -X POST $BASE/videos -F channel_id=2 -F caption="Chúc cả nhà tuần mới vui!"

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
| `GET /videos`, `POST /videos`, `GET/PATCH /videos/{id}` | Đọc/đẩy nội dung (video, ảnh, album, chữ), sửa tiêu đề, mô tả, caption |
| `POST /videos/{id}/regenerate-caption` | Cho AI viết lại caption ngay |
| `GET /posts`, `PATCH /posts/{id}` | Xem lịch theo ngày; đổi giờ hoặc caption của bài đang chờ |

## 6. Hằng ngày

**Quản lý**
1. **Kênh → Thêm kênh**: tên, nền tảng (TikTok / Facebook / Instagram / YouTube), @tài khoản, giờ đăng (ví dụ
   `08:00, 11:30, 19:00`), **dạng đăng mặc định** (Reels / Bài viết / Story; ảnh, album và bài chữ luôn là Bài viết),
   nhân viên phụ trách, điện thoại, thư mục Drive, hướng dẫn caption.
2. Thêm nhân viên ở **Cài đặt → trang quản trị** (`/quan-tri/`, đăng nhập bằng tài khoản tạo từ `createsuperuser`):
   chọn vai trò *Nhân viên*, hoặc *Quản lý* cho người được xem mọi thứ. Người quản lý nào cần tự thêm nhân viên thì
   tick thêm *Staff status* và cấp quyền quản lý người dùng.
3. Theo dõi **Tổng quan**: tiến độ từng người, bài trễ, kho mỗi kênh còn đủ mấy ngày (đỏ là sắp hết nội dung),
   và cảnh báo khi worker không chạy.
4. **Lịch đăng**: xem theo ngày / tuần / tháng, lọc theo kênh và nhân viên; mỗi bài là một thẻ màu theo trạng thái
   (xanh dương: chờ đăng, vàng: đến giờ, đỏ: trễ, xanh lá: đã đăng, xám: bỏ qua). Bấm vào bài để đổi giờ, người đăng,
   caption; gỡ bài thì video quay lại kho.

**Nhân viên (trên điện thoại)**
1. Mở `https://lenlich.tiepdi.com` → đăng nhập → *Thêm vào màn hình chính* để mở như app.
2. Trang **Việc của tôi** liệt kê bài hôm nay theo giờ; bài trễ có viền đỏ, bài đến giờ có viền vàng.
3. Đến giờ: bấm **Chia sẻ sang …** (video / ảnh được tải về máy) → bấm lần nữa **Mở app** (caption được copy, bảng
   chia sẻ mở ra) → chọn app:
   - **TikTok**: chọn nhạc, dán caption, đăng.
   - **Facebook**: chọn Facebook và đăng với tư cách **Trang**, hoặc chọn **Meta Business Suite**; dán caption, đăng.
     Có nút **Mở Meta Business Suite** để soạn bài trên trình duyệt / app Business Suite.
   - **Instagram**: chọn Instagram, chọn đúng dạng ghi trên thẻ (Reels / Bài viết / Story), dán caption, đăng.
   Album: các ảnh được chia sẻ cùng lúc theo thứ tự; có thể lướt ngang để xem trước. Nếu máy không hỗ trợ chia sẻ:
   dùng **Tải** + **Copy caption** rồi tự mở app. Bài chỉ có chữ: chia sẻ thẳng nội dung chữ.
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
studio/models.py        Kênh, Nội dung (Video) + File (MediaFile), Bài đăng, Dịch vụ AI, API key
studio/services/        drive.py (Google Drive), ai.py (caption), scheduler.py (xếp lịch), content.py (tạo / dọn file)
studio/views/           giao diện tiếng Việt
studio/static/studio/app.css   màu và bố cục; đổi màu thương hiệu ở các biến --brand-* đầu file
studio/api.py           REST API cho agent (django-ninja)
studio/management/commands/run_worker.py   worker nền
studio/management/commands/kiem_tra.py     kiểm tra cài đặt
scripts/cai-dat.sh      cài đặt / cập nhật bằng Docker
tests/                  pytest
```

## 8. Lộ trình

- [x] **Giai đoạn A**: Drive → kho → AI caption → xếp lịch → nhân viên đăng bằng app thật → theo dõi tiến độ.
- [x] Facebook Fanpage, Instagram: ảnh, album, bài chữ, dạng đăng Reels / Bài viết / Story, caption theo nền tảng,
      một thư mục Drive dùng cho nhiều kênh.
- [ ] **Giai đoạn B**: kết nối TikTok API chính thức (Login Kit + Content Posting API, chế độ *Upload to Inbox*):
      video tự vào hộp nháp trong app TikTok của đúng tài khoản. Cần trang giới thiệu, chính sách quyền riêng tư,
      điều khoản, video demo để TikTok duyệt app. So sánh hiệu quả với cách đăng hiện tại trên vài tài khoản trước khi áp dụng rộng.
- [ ] Thống kê view/tương tác từng video (TikTok `video.list`), so sánh theo nguồn video, khung giờ, nhân viên.
- [ ] Thống kê Facebook / Instagram (Meta Graph API, chỉ đọc số liệu, không đăng bài qua API).
- [ ] Hỗ trợ dựng video tự quay: cắt khoảng lặng, phụ đề, tách nhiều phiên bản.
