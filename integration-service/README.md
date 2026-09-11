# University Integration Service

Integration Service kết nối **UniSIS** (Student Information System) và
**UniLearn LMS**, hiện thực INT-01 → INT-08. Xem `../docs/` để biết kiến
trúc, sequence diagram, data mapping, test report, và báo cáo cuối kỳ.

## 1. Chạy nhanh (local, không Docker)

Yêu cầu: Python 3.11+, và gói `sis`/`lms` từ workshop instructor cấp
(giải nén `Integration_workshop.rar`).

```bash
# 1. cài dependency
pip install -r requirements.txt

# 2. chạy UniSIS và UniLearn (từ thư mục Integration_workshop)
cd /path/to/Integration_workshop
CLIENT_SECRET=student-secret ADMIN_KEY=admin-secret JWT_SECRET=dev-secret \
  python3 -m uvicorn sis.app.main:app --host 127.0.0.1 --port 8001 &
CLIENT_SECRET=student-secret ADMIN_KEY=admin-secret JWT_SECRET=dev-secret \
  python3 -m uvicorn lms.app.main:app --host 127.0.0.1 --port 8002 &

# 3. reset dữ liệu mẫu cho tenant của nhóm
curl -X POST http://127.0.0.1:8001/admin/tenants/TEAM01/reset -H "x-admin-key: admin-secret"
curl -X POST http://127.0.0.1:8002/admin/tenants/TEAM01/reset -H "x-admin-key: admin-secret"

# 4. chạy Integration Service (từ thư mục integration-service)
cp .env.example .env   # chỉnh nếu cần
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Khi khởi động, service tự chạy một lượt **reconciliation** (đồng bộ dữ
liệu Student/Section/Enrollment đã tồn tại sẵn trong SIS trước khi
Integration Service ra đời), sau đó bắt đầu polling định kỳ.

## 2. Chạy bằng Docker

```bash
docker build -t integration-service .
docker run --rm -p 8000:8000 \
  -e SIS_URL=http://host.docker.internal:8001 \
  -e LMS_URL=http://host.docker.internal:8002 \
  -e TENANT_ID=TEAM01 \
  -e SIS_CLIENT_SECRET=student-secret \
  -e LMS_CLIENT_SECRET=student-secret \
  -v $(pwd)/data:/app/data \
  integration-service
```

(Sandbox môi trường phát triển của repo này không có Docker daemon nên
Dockerfile được kiểm chứng bằng cách cài đúng `requirements.txt` trong
virtualenv sạch — xem `docs/test-report.md`. Trên máy có Docker, lệnh
trên chạy trực tiếp được.)

## 3. Kiểm thử

```bash
# bộ test tự động (spin up SIS/LMS test instance riêng, ~26s)
pip install -r requirements.txt
pytest tests/test_int_flows.py tests/test_reliability.py tests/test_reconciliation.py -v

# kiểm thử end-to-end thật (yêu cầu SIS/LMS/Integration Service đang chạy như mục 1)
python3 tests/live_smoke.py
python3 tests/live_reliability.py
```

## 4. Endpoint nội bộ hữu ích khi demo/bảo vệ

| Endpoint | Mô tả |
|---|---|
| `GET /health` | Trạng thái + số liệu tổng hợp |
| `POST /internal/poll` | Ép chạy 1 vòng poll ngay lập tức |
| `POST /internal/reconcile` | Ép chạy reconciliation ngay lập tức |
| `GET /internal/audit?limit=&event_id=&int_code=` | Xem audit log |
| `GET /internal/mappings?entity_type=` | Xem bảng mapping |
| `GET /internal/stats` | Đếm mapping / event theo trạng thái |
| `POST /internal/events/{source}/{event_id}/retry` | Thử lại 1 event cụ thể (cũng dùng để chứng minh idempotency) |
| `POST /webhooks/sis`, `POST /webhooks/lms` | Webhook receiver (dùng khi `INTEGRATION_MODE=webhook`) |

## 5. Biến môi trường

Xem đầy đủ trong `.env.example`. Quan trọng nhất:

* `SIS_URL`, `LMS_URL`, `TENANT_ID`, `*_CLIENT_SECRET`
* `INTEGRATION_MODE` — `poll` (mặc định) hoặc `webhook`
* `MAX_RETRIES`, `BACKOFF_BASE_SECONDS`, `BACKOFF_MAX_SECONDS`
* `AUTO_BOOTSTRAP_ON_START` — tự reconcile lúc khởi động (mặc định `true`)

## 6. Cấu trúc mã nguồn

```
app/
  config.py     cấu hình từ biến môi trường
  db.py         datastore SQLite riêng (mapping / idempotency / audit / checkpoint)
  clients.py    REST client cho SIS/LMS, phân loại lỗi Retryable/Permanent
  handlers.py   logic nghiệp vụ INT-01..INT-08
  engine.py     pipeline xử lý event dùng chung (idempotency, retry, audit)
  poller.py     polling scheduler + retry worker nền
  reconcile.py  reconciliation job (bootstrap + sửa lệch)
  main.py       FastAPI app, webhook receiver, endpoint nội bộ
tests/
  conftest.py            fixture: tự chạy SIS/LMS test instance
  test_int_flows.py      happy-path INT-01..INT-08
  test_reliability.py    idempotency, retry/backoff, dependency-pending, NFR
  test_reconciliation.py reconciliation
  live_smoke.py          kiểm thử thật, có log, chạy tay
  live_reliability.py    kiểm thử thật độ tin cậy, có log, chạy tay
```
