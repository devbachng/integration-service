# Data Mapping Table

## 1. Student (SIS) → User (LMS) — INT-01 / INT-05

| SIS field | LMS field | Ghi chú |
|---|---|---|
| `studentId` | `externalRef`, `username` | Khoá map trong `id_mapping` (entity_type=STUDENT_USER) |
| `lastName` + " " + `firstName` | `displayName` | Ghép theo thứ tự Họ trước Tên sau (chuẩn VN) |
| `email` | `emailAddress` | |
| `status == "ACTIVE"` | `enabled` (bool) | `INACTIVE`/`SUSPENDED`/khác → `enabled=false` |
| *(cố định)* `"LEARNER"` | `userType` | Sinh viên luôn map thành LEARNER |
| — | `id` (LMS sinh) | Lưu vào `id_mapping.target_id` |

## 2. Section (SIS) → Course (LMS) — INT-02 / INT-07

| SIS field | LMS field | Ghi chú |
|---|---|---|
| `sectionId` | `externalCode` | Khoá map (entity_type=SECTION_COURSE) |
| `courseCode` + tên môn (tra `GET /courses` của SIS) | `title` | Cache 30s để giảm số lần gọi SIS |
| `semesterCode` | `term` | |
| `lecturerId` | `teacherExternalRef` | Chỉ PATCH khi khác giá trị hiện tại (INT-07) |
| *(cố định)* `"PUBLISHED"` | `state` | |
| — | `id` (LMS sinh) | Lưu vào `id_mapping.target_id` |

## 3. Enrollment (SIS) → Membership (LMS) — INT-03 / INT-04

| SIS field | LMS field | Ghi chú |
|---|---|---|
| `studentId` → tra `id_mapping` (STUDENT_USER) | `userId` | Tự phục hồi bằng live-lookup `externalRef` nếu mapping local bị mất (câu 6, Phụ lục C) |
| `sectionId` → tra `id_mapping` (SECTION_COURSE) | `courseId` | Tương tự |
| *(cố định)* `"STUDENT"` | `role` | |
| `status=ENROLLED` → tạo | `POST /members` | `409` → NOOP (đã là member) |
| `status=DROPPED` → xoá | `DELETE /members/{userId}` | `404` → NOOP (đã bị xoá) |

## 4. Grade (LMS) → Grade (SIS) — INT-06

| LMS field | SIS field | Ghi chú |
|---|---|---|
| `userExternalRef` | `studentId` (path param) | |
| `courseExternalCode` | `sectionId` (path param) | |
| `finalGrade` (thang 0-100) | `finalScore` (thang 0-10) | `finalScore = finalGrade / 10`, làm tròn 2 chữ số |
| *(cố định)* `"LMS"` | `source` | Đánh dấu điểm này đến từ đồng bộ tự động |

## 5. Learning risk (LMS) → Advising alert (SIS) — INT-08

| LMS field | SIS field | Ghi chú |
|---|---|---|
| `userExternalRef` | `studentId` | |
| `courseExternalCode` | `sectionId` | |
| `riskType` | `riskType` | |
| `completionPercent`, `inactiveDays` | gộp vào `details` (chuỗi mô tả) | SIS không có field riêng cho 2 giá trị này |
| `riskId` | *(không map trực tiếp)* | Chống trùng dựa vào `eventId` ở tầng Integration Service, không dựa vào `riskId` |

## 6. Bảng `id_mapping` (datastore riêng của Integration Service)

| Cột | Kiểu | Mô tả |
|---|---|---|
| `entity_type` | TEXT | `STUDENT_USER` \| `SECTION_COURSE` |
| `tenant` | TEXT | Tenant hiện tại (TEAM01) |
| `source_id` | TEXT | ID bên SIS (studentId / sectionId) |
| `target_id` | TEXT | ID bên LMS (userId / courseId, dạng chuỗi) |
| `updated_at` | TEXT (ISO8601) | Lần cập nhật gần nhất |
