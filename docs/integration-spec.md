# Integration Spec — INT-01 .. INT-08

Tenant dùng trong tài liệu này: `TEAM01`. Mọi request đều kèm
`Authorization: Bearer <token>` + `X-Tenant-ID: TEAM01`.

| Mã | Trigger event | Nguồn → Đích | Hành động | Idempotency key | Lỗi phụ thuộc |
|---|---|---|---|---|---|
| **INT-01** | `student.created` | SIS → LMS | Tạo `User` (username=studentId, externalRef=studentId, userType=LEARNER) nếu chưa tồn tại | `eventId`; recovery qua `externalRef` nếu `409` | — |
| **INT-02** | `section.created` | SIS → LMS | Tạo `Course` (externalCode=sectionId, teacherExternalRef=lecturerId) nếu chưa tồn tại | `eventId`; recovery qua `externalCode` nếu `409` | — |
| **INT-03** | `enrollment.created` | SIS → LMS | Thêm `Member` (courseId, userId, role=STUDENT) | `eventId` | Chờ mapping Student→User **và** Section→Course (DependencyPendingError nếu thiếu) |
| **INT-04** | `enrollment.dropped` | SIS → LMS | Xoá `Member` | `eventId` | Nếu mapping không tồn tại → coi như đã ở trạng thái đích (NOOP) |
| **INT-05** | `student.updated` (status) | SIS → LMS | PATCH `User.enabled` = (status == ACTIVE) | `eventId` | Dùng chung handler với INT-01 (idempotent, chỉ PATCH field khác biệt) |
| **INT-06** | `grade.published` | LMS → SIS | `PUT /grades/{studentId}/{sectionId}` (finalScore = finalGrade/10, source=LMS) | `eventId` | Yêu cầu `userExternalRef`+`courseExternalCode`+`finalGrade` hợp lệ, nếu thiếu → PermanentError |
| **INT-07** | `section.updated` (lecturerId đổi) | SIS → LMS | PATCH `Course.teacherExternalRef`; nếu Course chưa tồn tại → tạo mới (fallback về INT-02) | `eventId` | — |
| **INT-08** | `learner.at_risk` | LMS → SIS | `POST /advising/alerts` (riskType, details) | `eventId` (chống trùng vì endpoint SIS không tự dedup theo riskId) | Yêu cầu `userExternalRef`+`courseExternalCode` hợp lệ |

## Quy tắc chung áp dụng cho mọi INT-0x

1. **Idempotency**: khoá theo `(eventId, source)`; xử lý lại (poll trùng
   khoảng, webhook gửi lại, người vận hành gọi `/internal/events/.../retry`)
   không bao giờ tạo hiệu ứng phụ trùng lặp.
2. **Không log secret**: request/response log chỉ ghi method, path,
   status code.
3. **Audit**: mỗi lần thử xử lý (thành công, retry, thất bại, bỏ qua vì
   trùng) đều có một dòng `audit_log` gắn `int_code` tương ứng.
4. **Rate-limit awareness**: tôn trọng header `Retry-After` khi gặp `429`.
