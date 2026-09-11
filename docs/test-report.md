# Test Report

## 1. Phạm vi kiểm thử

| Loại test | File | Cách chạy | Số lượng |
|---|---|---|---|
| Automated (pytest, CI-ready) | `tests/test_int_flows.py` | `pytest tests/test_int_flows.py` | 9 |
| Automated (pytest, NFR) | `tests/test_reliability.py` | `pytest tests/test_reliability.py` | 6 |
| Automated (pytest, reconciliation) | `tests/test_reconciliation.py` | `pytest tests/test_reconciliation.py` | 3 |
| **Tổng automated** | | `pytest tests/` (bỏ 2 file `live_*.py`) | **18** |
| Live smoke (end-to-end, có in log) | `tests/live_smoke.py` | `python3 tests/live_smoke.py` | 8 kịch bản (INT-01→08) |
| Live reliability (end-to-end, có in log) | `tests/live_reliability.py` | `python3 tests/live_reliability.py` | 3 kịch bản |

`tests/conftest.py` tự khởi động 2 tiến trình UniSIS/UniLearn thật trên
cổng riêng (8101/8102) cho mỗi phiên test — không mock HTTP, các test
automated gọi đúng REST API thật như production.

## 2. Kết quả pytest (chạy lần cuối)

```
collected 18 items

tests/test_int_flows.py::test_int01_student_created_creates_lms_user PASSED [  5%]
tests/test_int_flows.py::test_int02_section_created_creates_lms_course PASSED [ 11%]
tests/test_int_flows.py::test_int03_enrollment_created_adds_membership PASSED [ 16%]
tests/test_int_flows.py::test_int04_enrollment_dropped_removes_membership PASSED [ 22%]
tests/test_int_flows.py::test_int05_student_status_disables_lms_user PASSED [ 27%]
tests/test_int_flows.py::test_int06_grade_published_reverse_syncs_to_sis PASSED [ 33%]
tests/test_int_flows.py::test_int07_lecturer_change_patches_course PASSED [ 38%]
tests/test_int_flows.py::test_int08_learning_risk_creates_advising_alert PASSED [ 44%]
tests/test_int_flows.py::test_int08_normal_risk_does_not_emit_event_or_alert PASSED [ 50%]
tests/test_reliability.py::test_duplicate_eventid_is_idempotent PASSED   [ 55%]
tests/test_reliability.py::test_dependency_pending_then_resolves PASSED  [ 61%]
tests/test_reliability.py::test_permanent_error_does_not_retry_forever PASSED [ 66%]
tests/test_reliability.py::test_retryable_error_gives_up_after_max_retries PASSED [ 72%]
tests/test_reliability.py::test_retry_after_header_is_respected PASSED   [ 77%]
tests/test_reliability.py::test_audit_log_records_every_attempt PASSED   [ 83%]
tests/test_reconciliation.py::test_reconcile_creates_missing_mappings_for_preexisting_data PASSED [ 88%]
tests/test_reconciliation.py::test_reconcile_is_idempotent_second_pass_is_all_noop PASSED [ 94%]
tests/test_reconciliation.py::test_reconcile_repairs_drifted_enabled_flag PASSED [100%]

============================= 18 passed in 25.93s ==============================
```

(Toàn văn log: `docs/pytest_output.txt`)

## 3. Đối chiếu test ↔ yêu cầu

| Yêu cầu | Test chứng minh |
|---|---|
| INT-01 (student→User) | `test_int01_student_created_creates_lms_user`, `live_smoke.py` |
| INT-02 (section→Course) | `test_int02_section_created_creates_lms_course`, `live_smoke.py` |
| INT-03 (enrollment→Membership) | `test_int03_enrollment_created_adds_membership`, `live_smoke.py` |
| INT-04 (drop→unmembership) | `test_int04_enrollment_dropped_removes_membership`, `live_smoke.py` |
| INT-05 (status→enabled) | `test_int05_student_status_disables_lms_user`, `live_smoke.py` |
| INT-06 (grade reverse sync) | `test_int06_grade_published_reverse_syncs_to_sis`, `live_smoke.py` |
| INT-07 (lecturer change) | `test_int07_lecturer_change_patches_course`, `live_smoke.py` |
| INT-08 (risk→alert) + trường hợp KHÔNG risk | `test_int08_learning_risk_creates_advising_alert`, `test_int08_normal_risk_does_not_emit_event_or_alert`, `live_smoke.py` |
| NFR-01 Idempotency | `test_duplicate_eventid_is_idempotent` (3 lần xử lý cùng eventId → chỉ 1 LMS User, 2 dòng `SKIP_DUPLICATE`), `live_reliability.py` |
| NFR-02 Retry + backoff | `test_retryable_error_gives_up_after_max_retries`, `test_retry_after_header_is_respected`, `live_reliability.py` (bắt được `RETRY_SCHEDULED` thật khi LMS trả 503) |
| NFR-03 Không lặp vô hạn | `test_permanent_error_does_not_retry_forever` (4xx → FAILED ngay), `test_retryable_error_gives_up_after_max_retries` (5xx liên tục → FAILED sau MAX_RETRIES) |
| NFR-04 Audit log | `test_audit_log_records_every_attempt` |
| NFR-05 ID mapping store | Toàn bộ test trên đều gián tiếp xác nhận qua `id_mapping` |
| NFR-06 Reconciliation | `test_reconcile_creates_missing_mappings_for_preexisting_data`, `test_reconcile_is_idempotent_second_pass_is_all_noop`, `test_reconcile_repairs_drifted_enabled_flag` |
| Dependency ordering (Enrollment trước User/Course) | `test_dependency_pending_then_resolves`, `live_reliability.py` |
| NFR-12 Rate-limit awareness | `test_retry_after_header_is_respected` (dùng LMS instance riêng, rate limit mặc định 100/phút, xác nhận `Retry-After` header được tôn trọng đúng giá trị) |
| NFR-08 Tenant isolation | Mọi client gửi `X-Tenant-ID`; test dùng tenant `TEST01` riêng biệt với tenant `TEAM01` của live smoke |
| NFR-07 Không log secret | Kiểm tra thủ công `clients.py` — log chỉ in status code, không in token/secret (xem `docs/final-report.md` câu 8) |

## 4. Bằng chứng chạy thật (live, ngoài pytest)

Trích log chạy `tests/live_smoke.py` (đầy đủ 8/8 PASS, tenant TEAM01 thật):

```
=== INT-01: student.created -> LMS User ===
SIS create_student -> 201 ...
  OK  (4.2s) LMS user created for SVNEW57834
=== INT-06: grade.published (LMS) -> SIS grade reverse sync ===
LMS publish_grade -> 200 ...
  OK  (3.1s) SIS grade for SVNEW57834/SEC-NEW-57839 == 8.5
=== INT-08: learner.at_risk (LMS) -> SIS advising alert ===
  OK  (5.2s) SIS advising alert created for SVNEW57834
=== ALL INT-01..08 LIVE CHECKS PASSED ===
```

Trích log chạy `tests/live_reliability.py` (retry thật bắt được khi LMS
ở chế độ failure=HIGH):

```
RETRY_SCHEDULED count in last 300 audit rows: 1
 - UniLearn server error 503 (retry_count=1, delay=2.0s)
```

## 5. Bug tìm thấy trong quá trình test và cách sửa

| # | Mô tả | Phát hiện bằng | Sửa |
|---|---|---|---|
| 1 | Bootstrap reconciliation gọi LMS quá nhanh (100 SV + 15 lớp + 180 ghi danh liên tiếp không giãn cách) → dính rate limit 429 hàng loạt, một số bản ghi bị bỏ qua vì reconciliation không retry | Chạy thật `reconcile_all()` lúc khởi động, quan sát `internal/stats` và log | Thêm pacing chủ động (`RECONCILE_PACING_SECONDS`) + vòng lặp retry-with-backoff tôn trọng `Retry-After` bên trong `reconcile._run()` |

## 6. Giới hạn của bộ test hiện tại

* Chưa có test riêng cho webhook receiver (`POST /webhooks/sis|lms`) — service
  mặc định chạy polling nên đây là đường phụ; khuyến nghị bổ sung nếu
  triển khai production thật với `INTEGRATION_MODE=webhook`.
* Test reconciliation dùng `RATE_LIMIT` cao (100000) trên server test để
  chạy nhanh trong CI; hành vi tôn trọng rate-limit thật (100/phút) được
  test riêng bằng một instance LMS thứ hai với giới hạn mặc định
  (`test_retry_after_header_is_respected`).
