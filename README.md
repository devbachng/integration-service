# Đồ án kết thúc môn — Kiến trúc và Tích hợp Hệ thống
## Integration Service: UniSIS ↔ UniLearn LMS

Đồ án môn: Kiến trúc và Tích hợp Hệ thống  Sinh viên: Nguyễn Ngọc Bách — MSSV: 2300741 — Lớp: D101A1K15 (Tenant: TEAM01)

##Tổng quan dự án
Dự án này là tầng tích hợp trung gian (Integration Service) được xây dựng bằng Python / FastAPI nhằm tự động hóa việc đồng bộ dữ liệu giữa hai hệ thống Quản lý Đào tạo (UniSIS) và Quản lý Học tập (UniLearn LMS).
- Xử lý toàn bộ các luồng tích hợp: Hiện thực đầy đủ từ INT-01 đến INT-08 (bao gồm các luồng bắt buộc và luồng nâng cao)
- Đáp ứng các tiêu chí Phi chức năng (NFR): Chống trùng dữ liệu (Idempotency), cơ chế Thử lại (Retry/Backoff) có giới hạn, lưu nhật ký kiểm vết (Audit log), tự khôi phục bảng Ánh xạ ID (ID mapping self-healing), Đối soát dữ liệu (Reconciliation), Bảo mật Token/Secret, Giới hạn tần suất (Rate-limit awareness) và Đóng gói Container với Docker.
- Kiểm thử & Độ tin cậy: Đã vượt qua 18/18 Automated Tests (PyTest) trong ~26 giây. Đã thực hiện kiểm thử thực tế (Live Smoke & Reliability Tests) tương tác trực tiếp với các instance đang hoạt động của UniSIS và UniLearn LMS.
## Cấu trúc thư mục

├── integration-service/   # Mã nguồn chính (FastAPI), Dockerfile, môi trường & bộ Test

└── docs/                  # Tài liệu kiến trúc, spec tích hợp, sơ đồ luồng và báo cáo

## 🚀 Hướng dẫn đọc tài liệu & Kiểm tra dự án

Để nắm nhanh toàn bộ kiến trúc và kết quả thực hiện đồ án, bạn nên tham khảo tài liệu theo thứ tự sau:

1. **`docs/final-report.md` (Nên đọc đầu tiên):** Báo cáo tổng quan dự án và lời giải chi tiết cho 10 câu hỏi bắt buộc trong Phụ lục C.
2. **`docs/architecture.md`:** Thiết kế kiến trúc tổng thể (Context diagram, Container/Component diagram) kèm lý do lựa chọn giải pháp kỹ thuật.
3. **`docs/integration-spec.md` & `docs/data-mapping.md`:** Chi tiết các luồng `INT-01` $\rightarrow$ `INT-08` và quy tắc ánh xạ trường dữ liệu giữa các bên.
4. **`docs/sequence-diagrams.md`:** 5 sơ đồ tuần tự thể hiện các kịch bản: Happy path, Dependency-pending, Retry/Backoff, Idempotency và Reconciliation.
5. **`docs/test-report.md`:** Báo cáo kiểm thử chi tiết kèm bằng chứng chạy live (bao gồm log dữ liệu trước/sau khi đồng bộ cho `INT-05` $\rightarrow$ `INT-08`).
6. **`docs/rubric-self-assessment.md`:** Bảng tự đánh giá kết quả theo các tiêu chí trong Phiếu chấm điểm của giảng viên.
7. **`integration-service/README.md`:** Hướng dẫn chi tiết cách thiết lập môi trường local, chạy mã nguồn, khởi chạy container bằng Docker và thực thi bộ test.

## Bắt đầu từ đâu

1. Đọc `docs/final-report.md` trước — trả lời 10 câu hỏi bắt buộc của
   đề bài (Phụ lục C) và tóm tắt toàn bộ đồ án.
2. `docs/architecture.md` — kiến trúc tổng thể (Context diagram +
   Container/Component diagram) + quyết định thiết kế.
3. `docs/integration-spec.md`, `docs/data-mapping.md` — chi tiết
   INT-01→08 và bảng mapping trường dữ liệu.
4. `docs/sequence-diagrams.md` — 5 sequence diagram (happy path,
   dependency-pending, retry/backoff, idempotency, reconciliation).
5. `docs/test-report.md` + `docs/pytest_output.txt` +
   `docs/live_smoke_evidence.txt` — kết quả test (18/18 automated test
   PASS + bằng chứng chạy thật, có trạng thái trước/sau cho INT-05→08).
6. `docs/rubric-self-assessment.md` — tự chấm điểm theo đúng "Phiếu chấm
   điểm" của giảng viên, nêu rõ phần nào đã đạt và phần nào cần chuẩn bị
   thêm trước khi bảo vệ.
7. `integration-service/README.md` — hướng dẫn chạy source code, Docker,
   test.

## Tóm tắt nhanh

* Ngôn ngữ: Python 3 / FastAPI (đề bài không chấm theo ngôn ngữ).
* Đã hiện thực đầy đủ INT-01 → INT-08 (bắt buộc + nâng cao).
* NFR đã đáp ứng: idempotency, retry/backoff có giới hạn, audit log,
  ID mapping store tự phục hồi, reconciliation, không log secret,
  tenant isolation, health endpoint, rate-limit awareness, Docker.
* 18 automated test (pytest) PASS trong ~26s + 2 kịch bản kiểm thử thật
  (live smoke, live reliability) chạy trực tiếp với UniSIS/UniLearn
  đang sống.
