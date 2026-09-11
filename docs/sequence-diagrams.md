# Sequence Diagrams

## 1. INT-01 happy path (student.created → LMS User)

```mermaid
sequenceDiagram
    participant SIS as UniSIS
    participant P as Poller
    participant E as Engine
    participant H as Handler (INT-01)
    participant DB as Integration DB
    participant LMS as UniLearn LMS

    P->>SIS: GET /api/v1/events?since=checkpoint
    SIS-->>P: [student.created eventId=E1]
    P->>E: process_event(E1, student.created, SIS, data)
    E->>DB: get_event(E1, SIS) -> not found
    E->>H: sync_student_to_lms_user(data)
    H->>LMS: GET /users?externalRef=studentId
    LMS-->>H: [] (không tồn tại)
    H->>LMS: POST /users {username, displayName, enabled, externalRef}
    LMS-->>H: 201 {id: 101}
    H->>DB: set_mapping(STUDENT_USER, studentId, 101)
    H-->>E: "CREATE_USER"
    E->>DB: upsert_event(E1, DONE)
    E->>DB: audit(E1, INT-01, CREATE_USER, SUCCESS)
    E->>DB: set_checkpoint(SIS, occurredAt)
```

## 2. INT-03 với dependency chưa sẵn sàng (out-of-order) rồi tự phục hồi

```mermaid
sequenceDiagram
    participant SIS as UniSIS
    participant E as Engine
    participant H as Handler (INT-03)
    participant DB as Integration DB
    participant RW as Retry Worker (nền)

    Note over SIS,E: enrollment.created (E2) tới trước khi<br/>student.created/section.created được xử lý xong
    E->>H: sync_enrollment_to_membership(data)
    H->>DB: get_mapping(STUDENT_USER, studentId) -> None
    H->>H: live-lookup LMS User by externalRef -> None
    H-->>E: raise DependencyPendingError
    E->>DB: upsert_event(E2, PENDING, next_retry_at=+4s)
    E->>DB: audit(E2, INT-03, WAIT_DEPENDENCY, RETRY)

    Note over SIS,E: song song, student.created và section.created<br/>được xử lý xong, mapping đã tồn tại

    loop mỗi RETRY_WORKER_INTERVAL_SECONDS
        RW->>DB: pending_events() next_retry_at <= now
        DB-->>RW: [E2]
        RW->>E: process_event(E2, ...)
        E->>H: sync_enrollment_to_membership(data)
        H->>DB: get_mapping(...) -> tồn tại
        H->>LMS: POST /courses/id/members
        LMS-->>H: 201
        H-->>E: ADD_MEMBER
        E->>DB: upsert_event(E2, DONE)
    end
```

## 3. Retry/backoff khi UniLearn trả 503 rồi 429 (NFR-02/03/12)

```mermaid
sequenceDiagram
    participant E as Engine
    participant C as LMS Client
    participant LMS as UniLearn LMS
    participant DB as Integration DB

    E->>C: POST /users (lan 1)
    C->>LMS: POST /users
    LMS-->>C: 503 Service Unavailable
    C-->>E: RetryableError status=503
    E->>DB: PENDING retry_count=1 next_retry_at=+2s
    E->>DB: audit RETRY_SCHEDULED delay=2.0s

    Note over E: retry worker cho 2s roi thu lai

    E->>C: POST /users (lan 2)
    C->>LMS: POST /users
    LMS-->>C: 429 Too Many Requests Retry-After=10
    C-->>E: RetryableError status=429 retry_after=10
    E->>DB: PENDING retry_count=2 next_retry_at=+10s

    Note over E: retry worker cho dung 10s, khong phai backoff mac dinh

    E->>C: POST /users (lan 3)
    C->>LMS: POST /users
    LMS-->>C: 201 Created
    C-->>E: user
    E->>DB: DONE
    E->>DB: audit SUCCESS

    Note over E,DB: Neu van loi sau MAX_RETRIES lan -> FAILED,<br/>audit GIVE_UP_MAX_RETRIES, khong lap vo han
```

## 4. Idempotency khi cùng event được giao 3 lần

```mermaid
sequenceDiagram
    participant Caller as Poller / Webhook / Admin retry
    participant E as Engine
    participant DB as Integration DB
    participant LMS as UniLearn LMS

    Caller->>E: process_event(E1) lan 1
    E->>DB: get_event(E1) -> None
    E->>LMS: side effect tao User
    E->>DB: upsert_event(E1, DONE)

    Caller->>E: process_event(E1) lan 2 trung
    E->>DB: get_event(E1) -> DONE
    E->>DB: audit SKIP_DUPLICATE
    Note over E,LMS: KHONG goi LMS lan nua

    Caller->>E: process_event(E1) lan 3 trung
    E->>DB: get_event(E1) -> DONE
    E->>DB: audit SKIP_DUPLICATE
```

## 5. Reconciliation sweep (NFR-06, bootstrap dữ liệu có sẵn)

```mermaid
sequenceDiagram
    participant Start as Startup / Admin
    participant R as Reconciliation
    participant SIS as UniSIS
    participant H as Handlers dung chung INT-01/02/03
    participant LMS as UniLearn LMS

    Start->>R: reconcile_all()
    R->>SIS: GET /api/v1/students (toan bo)
    loop moi student
        R->>H: sync_student_to_lms_user
        H->>LMS: tim hoac tao/patch User
    end
    R->>SIS: GET /api/v1/sections (toan bo)
    loop moi section
        R->>H: sync_section_to_lms_course
        H->>LMS: tim hoac tao/patch Course
    end
    R->>SIS: GET /api/v1/enrollments (ENROLLED)
    loop moi enrollment
        R->>H: sync_enrollment_to_membership
        H->>LMS: tim hoac tao Membership, 409 -> NOOP
    end
    R-->>Start: ket qua tong hop
```
