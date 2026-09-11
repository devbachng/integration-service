# Đồ án kết thúc môn — Kiến trúc và Tích hợp Hệ thống
## Integration Service: UniSIS ↔ UniLearn LMS

**Sinh viên:** Nguyễn Ngọc Bách — MSSV 2300741 — Lớp D101A1K15 — Tenant: TEAM01

## Cấu trúc thư mục

```
integration-service/   mã nguồn Integration Service (Python/FastAPI) + Dockerfile + test
docs/                  toàn bộ tài liệu (kiến trúc, spec, mapping, sequence diagram, test report, báo cáo cuối kỳ)
```

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
