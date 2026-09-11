# Tự đánh giá theo Phiếu chấm điểm

Đối chiếu trung thực với "PHIẾU CHẤM ĐIỂM — Đề 01" do giảng viên cung
cấp. Mục tiêu tài liệu này là chỉ rõ phần nào **đã có bằng chứng đầy đủ**
và phần nào **sinh viên cần tự chuẩn bị thêm** trước buổi bảo vệ (vì có
những tiêu chí chỉ chấm được khi bảo vệ trực tiếp, không thể "làm sẵn"
thay được).

## Câu 1 (3.0đ) — Phân tích, thiết kế bài toán tích hợp

| Yêu cầu con | Trạng thái | Bằng chứng |
|---|---|---|
| Xác định phạm vi & ranh giới trách nhiệm giữa các hệ thống | ✅ Đạt | `docs/architecture.md` mục 2 (Context diagram) + `docs/final-report.md` câu 2 (bảng source of truth) |
| Mô tả dữ liệu cần đồng bộ, mapping ID | ✅ Đạt | `docs/data-mapping.md` (6 bảng mapping field-by-field) |
| Integration contract | ✅ Đạt | `docs/integration-spec.md` (bảng INT-01→08: trigger, nguồn/đích, hành động, idempotency key, lỗi phụ thuộc) |
| Sơ đồ kiến trúc (context + container/component) | ✅ Đạt (đã bổ sung) | `docs/architecture.md` mục 2 (Context) và mục 3 (Container/Component), có bảng map 1-1 component ↔ file mã nguồn |
| Sequence diagram | ✅ Đạt | `docs/sequence-diagrams.md` — 5 sequence diagram (happy path INT-01, dependency-pending INT-03, retry/backoff, idempotency, reconciliation) |
| Tài liệu phân tích, thiết kế hệ thống | ✅ Đạt | `docs/architecture.md`, `docs/integration-spec.md`, `docs/data-mapping.md` |

**Đánh giá: đủ điều kiện đạt điểm tối đa 3.0đ**, miễn là khi bảo vệ sinh
viên trình bày được logic đằng sau các quyết định (vì sao chọn polling,
vì sao SIS là source of truth cho Student...).

## Câu 2 (2.0đ) — INT-01 → INT-04

| Yêu cầu con | Trạng thái | Bằng chứng |
|---|---|---|
| INT-01 Student → LMS User | ✅ | `test_int01_...` (pytest) + `docs/live_smoke_evidence.txt` |
| INT-02 Section → LMS Course | ✅ | `test_int02_...` + live evidence |
| INT-03 Enrollment → Membership | ✅ | `test_int03_...` + live evidence |
| INT-04 Drop Enrollment → gỡ Membership | ✅ | `test_int04_...` + live evidence |
| Dữ liệu phát sinh từ hệ thống nguồn, Integration Service tự động cập nhật đích | ✅ | Toàn bộ test tạo dữ liệu qua API SIS/LMS thật, không thao tác thủ công lên đích |
| Mapping ID đúng, không hard-code | ✅ | `app/db.py` (bảng `id_mapping`), `app/handlers.py` tra cứu qua `externalRef`/`externalCode`, không có ID cứng trong code |

**Đánh giá: đủ điều kiện đạt điểm tối đa 2.0đ.**

## Câu 3 (2.0đ) — INT-05 → INT-08

| Yêu cầu con | Trạng thái | Bằng chứng |
|---|---|---|
| INT-05 status → enabled/disabled | ✅ | `test_int05_...` + live evidence có **BEFORE/AFTER** rõ ràng (`enabled: True` → `enabled: False`) |
| INT-06 grade.published → điểm chính thức SIS | ✅ | `test_int06_...` + live evidence có BEFORE (chưa có điểm) / AFTER (`finalScore: 8.5`) |
| INT-07 đổi giảng viên → Course | ✅ | `test_int07_...` + live evidence BEFORE (`GV0001`) / AFTER (`GV0007`) |
| INT-08 learner.at_risk → Advising Alert | ✅ | `test_int08_...` + live evidence BEFORE (`[]`) / AFTER (alert cụ thể) |
| Bằng chứng event, log và trạng thái trước/sau | ✅ (đã bổ sung) | `docs/live_smoke_evidence.txt` in rõ dòng `BEFORE:`/`AFTER:` cho cả 4 luồng; `internal/audit` lưu log từng bước xử lý |

**Đánh giá: đủ điều kiện đạt điểm tối đa 2.0đ.**

## Câu 4 (2.0đ) — Chất lượng code và kiến trúc code

| Yêu cầu con | Trạng thái | Bằng chứng |
|---|---|---|
| Tổ chức module/layer rõ ràng | ✅ | `config.py`/`db.py`/`clients.py`/`handlers.py`/`engine.py`/`poller.py`/`reconcile.py`/`main.py` — mỗi file 1 trách nhiệm, khớp với sơ đồ Container/Component |
| API client | ✅ | `app/clients.py` (SISClient/LMSClient, JWT cache, phân loại lỗi) |
| Webhook/polling | ✅ | `app/poller.py` (polling chính) + `app/main.py` (webhook receiver có sẵn) |
| Mapping | ✅ | `app/db.py::id_mapping` + tự phục hồi qua live-lookup |
| Idempotency | ✅ | `app/engine.py` + `processed_events` |
| Retry/backoff | ✅ | `app/engine.py` (backoff mũ 2, tôn trọng Retry-After) |
| Reconciliation | ✅ | `app/reconcile.py` |
| Logging/audit | ✅ | `app/db.py::audit_log` |
| Xử lý lỗi hợp lý | ✅ | 3 loại exception rõ ràng: `RetryableError`/`PermanentError`/`DependencyPendingError` |
| Code dễ đọc, có kiểm thử | ✅ | Docstring đầu mỗi file, 18 pytest PASS |
| **SV giải thích được luồng xử lý, trả lời câu hỏi trực tiếp trên source** | ⚠️ **Chỉ chấm được lúc bảo vệ trực tiếp** | Không thể "làm sẵn" — sinh viên cần tự ôn lại code trước khi bảo vệ (xem mục "Chuẩn bị bảo vệ" bên dưới) |

**Đánh giá: phần kỹ thuật đủ điều kiện đạt tối đa 2.0đ; phần còn lại
(0 đ trừ nếu chuẩn bị tốt) phụ thuộc hoàn toàn vào khả năng trình bày
trực tiếp của sinh viên khi bảo vệ — không phải thứ Claude có thể làm
thay.**

## Câu 5 (1.0đ) — Hoàn thiện sản phẩm

| Yêu cầu con | Trạng thái | Ghi chú |
|---|---|---|
| Build/deploy và demo tích hợp chạy thật | ⚠️ **Một phần** | Đã demo chạy thật (uvicorn trực tiếp, không qua Docker) — xem `docs/live_smoke_evidence.txt`. **Dockerfile chưa được build/run thật** vì máy môi trường này không có Docker daemon. **Sinh viên cần tự `docker build` + `docker run` trên máy có Docker trước khi bảo vệ để có bằng chứng build/deploy thật bằng container.** |
| Source code/Git | ⚠️ **Đã bổ sung git repo cục bộ** | Repo git đã được khởi tạo với lịch sử commit (xem bên dưới), nhưng **chưa đẩy lên GitHub/GitLab** — nếu đề bài yêu cầu link repo online, sinh viên cần tự tạo remote và push. |
| Dockerfile, .env.example, README | ✅ Đạt | Có đủ cả 3 |
| Tài liệu kiến trúc/tích hợp, Data Mapping, sequence diagram, Test Report, báo cáo cuối kỳ | ✅ Đạt | Đủ cả 5 loại tài liệu trong `docs/` |
| Không để lộ token/secret | ✅ Đạt | Secret chỉ đọc từ env var, `.env` không commit (có `.gitignore`), `.env.example` chỉ chứa giá trị mẫu của lab (`student-secret` — đây là giá trị mặc định công khai trong mã nguồn workshop do giảng viên cấp, không phải secret thật) |

**Đánh giá: 2/4 tiêu chí đạt trọn vẹn, 2/4 tiêu chí cần sinh viên tự
hoàn thiện thêm (Docker build thật + push Git remote) trước khi nộp/bảo
vệ để chắc chắn đạt tối đa 1.0đ.**

## Tổng kết

| Câu | Điểm tối đa | Đánh giá hiện tại |
|---|---|---|
| 1 | 3.0 | Đủ điều kiện đạt tối đa |
| 2 | 2.0 | Đủ điều kiện đạt tối đa |
| 3 | 2.0 | Đủ điều kiện đạt tối đa |
| 4 | 2.0 | Phần kỹ thuật đủ điều kiện đạt tối đa; phần trình bày trực tiếp phụ thuộc sinh viên lúc bảo vệ |
| 5 | 1.0 | Cần tự làm thêm 2 việc trước khi nộp: (a) `docker build && docker run` thật trên máy có Docker, (b) push git repo lên remote (GitHub/GitLab) nếu đề bài yêu cầu link |

**Về mặt kỹ thuật/tài liệu, dự án đã sẵn sàng cho thang điểm tối đa
10/10.** Hai việc còn lại (Docker build thật, push Git remote) là thao
tác sinh viên cần tự thực hiện trên máy cá nhân có Docker/tài khoản
Git, vì môi trường hiện tại không có Docker daemon và không có quyền
tạo remote Git thay sinh viên.

## Chuẩn bị bảo vệ (cho phần "SV giải thích được... trả lời câu hỏi trực tiếp trên source" của Câu 4)

Một số câu hỏi giảng viên có thể hỏi trực tiếp trên source, và nơi trả
lời trong code:

1. "Idempotency được đảm bảo ở đâu trong code?" → `app/engine.py::process_event`, dòng kiểm tra `existing.status == "DONE"`.
2. "Nếu enrollment đến trước khi Student/Section được đồng bộ thì sao?" → `app/handlers.py::sync_enrollment_to_membership` raise `DependencyPendingError`, xử lý ở `app/engine.py`.
3. "Retry bao nhiêu lần thì dừng, và dừng ở đâu trong code?" → `app/config.py::MAX_RETRIES`, kiểm tra ở `app/engine.py::process_event` nhánh `RetryableError`.
4. "Reconciliation so sánh và sửa cái gì?" → `app/reconcile.py`, tái sử dụng `app/handlers.py` — xem `docs/final-report.md` câu 7.
5. "Vì sao chọn polling thay vì webhook?" → `docs/final-report.md` câu 1, và `app/poller.py`.
6. "Mapping ID lưu ở đâu, khôi phục thế nào nếu mất?" → `app/db.py::id_mapping`, `app/handlers.py::_resolve_user_id/_resolve_course_id` (live-lookup fallback).
