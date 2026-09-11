# Báo cáo cuối kỳ — Integration Service (UniSIS ↔ UniLearn LMS)

**Môn học:** Kiến trúc và Tích hợp Hệ thống — Trường Đại học Thành Đô
**Sinh viên:** Bách — MSSV 2300741 — Lớp D101A1K15 — Khoa Công nghệ Thông tin
**Tenant:** TEAM01

## Phụ lục C — Trả lời 10 câu hỏi bắt buộc

### 1. Vì sao nhóm chọn webhook, polling, batch, queue hay hybrid? Trade-off là gì?

Nhóm chọn **polling làm cơ chế chính**, với endpoint webhook receiver có
sẵn nhưng không bật mặc định. Lý do:

* **Đơn giản, dễ chứng minh đúng đắn**: polling không phụ thuộc việc
  SIS/LMS phải gọi ngược lại được Integration Service (không cần public
  URL, không cần lo webhook registration thất bại âm thầm).
* **Tự phục hồi sau downtime**: nếu Integration Service tắt 10 phút, khi
  bật lại chỉ cần tiếp tục poll từ `checkpoint` cũ — không mất event như
  webhook có thể mất nếu bên gửi không có cơ chế retry riêng.
* **Trade-off phải đánh đổi**: độ trễ cao hơn webhook (tối đa
  `POLL_INTERVAL_SECONDS` = 3-5s thay vì tức thời), và tốn thêm request
  "rỗng" (`GET /events` dù không có gì mới) — chấp nhận được ở quy mô lab.
* Vì `engine.process_event()` idempotent tuyệt đối theo `eventId`, kiến
  trúc thực chất **có thể bật hybrid** (cả polling lẫn webhook cùng lúc)
  mà không rủi ro trùng dữ liệu — polling đóng vai trò lưới an toàn
  (safety net), webhook (nếu bật) chỉ giảm độ trễ.

### 2. Nhóm xác định source of truth cho từng miền dữ liệu như thế nào?

| Miền dữ liệu | Source of truth | Lý do |
|---|---|---|
| Danh tính sinh viên, lớp học phần, enrollment, trạng thái học vụ | **UniSIS** | Hệ thống quản lý đào tạo gốc, dữ liệu hành chính |
| ID nội bộ LMS (userId, courseId), trạng thái học tập (completion/inactive) | **UniLearn LMS** | Chỉ LMS biết hành vi học tập thực tế và ID nội bộ của nó |
| Điểm cuối kỳ sau khi publish | Ghi ngược về SIS, `source=LMS` để phân biệt nguồn | Điểm là dữ liệu học vụ chính thức phải nằm ở SIS |
| Mapping Student↔User, Section↔Course | **Integration Service tự quản lý** | Dữ liệu riêng của tầng tích hợp, không thuộc nghiệp vụ hai hệ thống |

### 3. Nếu cùng event được nhận 2-3 lần, service chứng minh không tạo dữ liệu trùng bằng cách nào?

Bảng `processed_events` (khoá `event_id + source`) lưu trạng thái xử lý.
Trước khi gọi handler, `engine.process_event()` luôn kiểm tra: nếu
`status == DONE` thì bỏ qua ngay (`SKIP_DUPLICATE`), không gọi lại
handler, do đó không có side-effect thứ hai. Với race condition hiếm
(hai tiến trình cùng xử lý event chưa kịp ghi DONE), lệnh tạo tài
nguyên (`POST /users`, `POST /courses`) khi gặp `409 Conflict` từ LMS
được bắt riêng và coi là phục hồi thành công (`RECOVERED_FROM_409_*`)
thay vì tạo bản ghi thứ hai.

Bằng chứng: `tests/test_reliability.py::test_duplicate_eventid_is_idempotent`
gọi xử lý cùng một `eventId` 3 lần, xác nhận LMS chỉ có đúng 1 User.

### 4. Nếu event Enrollment đến trước khi LMS User hoặc Course tồn tại, nhóm xử lý dependency ra sao?

Handler `sync_enrollment_to_membership` tra `id_mapping`; nếu thiếu, thử
live-lookup trực tiếp trên LMS qua `externalRef`/`externalCode` (tự phục
hồi nếu mapping local bị mất nhưng đích đã tồn tại — xem câu 6). Nếu vẫn
không tìm thấy, handler raise `DependencyPendingError`, và event được
lưu ở trạng thái `PENDING` với `next_retry_at`. Một worker nền quét
`PENDING` định kỳ và tái sử dụng chính pipeline `process_event` để thử
lại — khi Student/Section đã được đồng bộ, lần retry tiếp theo sẽ
thành công.

Bằng chứng: `tests/test_reliability.py::test_dependency_pending_then_resolves`.

### 5. Nếu LMS/SIS trả 503 trong 1 phút, dữ liệu có bị mất không? Sau khi service phục hồi, hệ thống đạt consistency bằng cách nào?

Không mất. Mọi lỗi 503/502/500/lỗi mạng được phân loại là
`RetryableError`; event chuyển `PENDING` với thời điểm retry theo backoff
mũ 2 (base 2s, trần 60s, tối đa `MAX_RETRIES=6` lần). Event gốc luôn
nằm trong `processed_events` với đầy đủ `payload`, không phụ thuộc bộ
nhớ tạm, nên kể cả khi Integration Service crash/restart giữa lúc
outage, sau khi khởi động lại, retry worker vẫn quét thấy các dòng
`PENDING` và tiếp tục xử lý — không cần nguồn phát lại event.

### 6. Nếu mapping database bị mất một bản ghi nhưng target vẫn tồn tại, service có tự khôi phục được không?

Có. Mọi hàm resolve mapping (`_resolve_user_id`, `_resolve_course_id`
trong `handlers.py`) đều làm theo thứ tự: tra local mapping trước → nếu
thiếu, live-lookup trên LMS bằng `externalRef`/`externalCode` → nếu tìm
thấy, ghi lại mapping local rồi tiếp tục xử lý bình thường. Vì vậy dù
bảng `id_mapping` bị xoá một phần hoặc toàn bộ, lần request tiếp theo
(event mới hoặc reconciliation) sẽ tự dựng lại mapping mà không tạo
trùng tài nguyên bên LMS.

### 7. Reconciliation của nhóm so sánh khóa nào và sửa những trường nào?

* **Khoá so sánh**: `studentId` ↔ `externalRef` (User), `sectionId` ↔
  `externalCode` (Course) — khoá nghiệp vụ ổn định, không phải ID nội
  bộ do hệ thống sinh ra.
* **Trường được sửa khi lệch**: `displayName`, `emailAddress`, `enabled`
  (User); `teacherExternalRef` (Course). Reconciliation tái sử dụng
  đúng handler của luồng event-driven nên logic so sánh/sửa hoàn toàn
  nhất quán giữa hai đường.
* Phạm vi quét: toàn bộ Student, Section, và Enrollment đang `ENROLLED`
  — đủ để bootstrap dữ liệu có sẵn trước khi Integration Service tồn
  tại (GAP-11) về trạng thái nhất quán trong một lần chạy.

### 8. Nhóm ngăn token/client secret xuất hiện trong log/Git như thế nào?

* Toàn bộ secret (`SIS_CLIENT_SECRET`, `LMS_CLIENT_SECRET`, `ADMIN_KEY`)
  chỉ đọc từ biến môi trường (`app/config.py`), không hard-code trong
  mã nguồn.
* `.env` (chứa giá trị thật) không được commit; chỉ `.env.example`
  (giá trị mẫu lab) được đưa vào bộ nộp bài.
* `app/clients.py::request()` chỉ log `method`, `path`, `status_code` —
  không log `headers` (nơi chứa `Authorization: Bearer <token>`) hay
  body của endpoint `/auth/token` (nơi chứa secret).
* Token JWT chỉ giữ trong biến instance bộ nhớ tiến trình, không ghi ra
  file, không log.

### 9. Các test nào chứng minh INT-01..INT-08 và NFR được đáp ứng?

Xem bảng đối chiếu đầy đủ trong `docs/test-report.md` mục 3. Tóm tắt:
18 automated test (pytest) + 2 kịch bản live smoke (chạy thật với
SIS/LMS đang sống, có log) bao phủ toàn bộ 8 INT-0x, cộng NFR-01
(idempotency), NFR-02/03 (retry, no-infinite-retry), NFR-04 (audit),
NFR-06 (reconciliation), NFR-12 (rate-limit/Retry-After).

### 10. Nếu triển khai production thật, nhóm sẽ cải tiến kiến trúc lab ở điểm nào?

* **Message queue thay vì polling thuần**: dùng Kafka/RabbitMQ để giảm
  độ trễ và tải polling, vẫn giữ đảm bảo at-least-once.
* **Mapping/audit store chuyển sang Postgres** (thay SQLite) để chịu
  được nhiều instance Integration Service chạy song song.
* **Secret quản lý qua Vault/Secrets Manager**, có xoay vòng tự động.
* **Observability**: xuất metrics (Prometheus) cho số event pending/
  failed, độ trễ xử lý trung bình, tỷ lệ lỗi theo INT-0x.
* **Dead-letter queue** cho các event `FAILED` để người vận hành có
  công cụ xử lý thủ công riêng.
* **Horizontal scaling**: cần cơ chế lock phân tán (vd. Redis lock) nếu
  chạy nhiều replica poller/retry worker.

## Kết luận

Integration Service đáp ứng đầy đủ INT-01 → INT-08 (bắt buộc lẫn nâng
cao), các NFR cốt lõi (idempotency, retry/backoff có giới hạn, audit
log, reconciliation, rate-limit awareness, tenant isolation, không log
secret), có Dockerfile + README để triển khai, và có bộ test tự động
(18 test, ~26s) cùng bằng chứng chạy thật (live smoke + live
reliability) chứng minh hệ thống hoạt động đúng cả ở happy path lẫn các
tình huống lỗi/mất trật tự dữ liệu.
