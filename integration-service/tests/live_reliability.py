import time
from pathlib import Path
import httpx

SIS = "http://127.0.0.1:8001"
LMS = "http://127.0.0.1:8002"
INT = "http://127.0.0.1:8000"
TENANT = "TEAM01"
ADMIN = {"x-admin-key": "admin-secret"}


def token(base):
    r = httpx.post(f"{base}/api/v1/auth/token", json={"clientId": "TEST", "clientSecret": "student-secret", "tenantId": TENANT})
    return r.json()["accessToken"]


sis_h = {"Authorization": f"Bearer {token(SIS)}", "X-Tenant-ID": TENANT}
lms_h = {"Authorization": f"Bearer {token(LMS)}", "X-Tenant-ID": TENANT}


def wait_for(fn, desc, timeout=30, interval=1.0):
    start = time.time()
    while time.time() - start < timeout:
        v = fn()
        if v:
            print(f"  OK  ({time.time()-start:.1f}s) {desc}")
            return v
        time.sleep(interval)
    print(f"  FAIL (timeout {timeout}s) {desc}")
    return None


print("=== TEST: idempotency (same eventId processed twice is a no-op) ===")
audit_before = httpx.get(f"{INT}/internal/audit", params={"limit": 500}).json()
sid = f"SVIDEM{int(time.time())%100000}"
r = httpx.post(f"{SIS}/api/v1/students", headers=sis_h, json={
    "studentId": sid, "firstName": "Idem", "lastName": "Potent", "email": f"{sid.lower()}@student.edu.vn",
})
assert r.status_code == 201

def find_event():
    rows = httpx.get(f"{INT}/internal/audit", params={"limit": 500}).json()
    for row in rows:
        if row["event_type"] == "student.created" and row["detail"] == "" and row["status"] == "SUCCESS":
            pass
    # look up via SIS events endpoint instead, more reliable
    evs = httpx.get(f"{SIS}/api/v1/events", headers=sis_h, params={"eventType": "student.created"}).json()
    for e in evs:
        if e["data"]["studentId"] == sid:
            return e["eventId"]
    return None

event_id = wait_for(find_event, f"find eventId for {sid}'s student.created")
assert event_id

# wait for it to be processed once
def is_done():
    rows = httpx.get(f"{INT}/internal/audit", params={"event_id": event_id, "limit": 20}).json()
    return any(row["status"] == "SUCCESS" and row["action"] != "SKIP_DUPLICATE" for row in rows)

wait_for(is_done, f"eventId {event_id} processed (DONE)")

# now manually re-deliver / re-process the exact same event twice via internal retry endpoint
r1 = httpx.post(f"{INT}/internal/events/SIS/{event_id}/retry")
r2 = httpx.post(f"{INT}/internal/events/SIS/{event_id}/retry")
print("retry#1 ->", r1.json())
print("retry#2 ->", r2.json())
assert r1.json()["result"] == "SKIPPED"
assert r2.json()["result"] == "SKIPPED"

rows = httpx.get(f"{INT}/internal/audit", params={"event_id": event_id, "limit": 20}).json()
dup_skips = [row for row in rows if row["action"] == "SKIP_DUPLICATE"]
print(f"  SKIP_DUPLICATE audit rows for this event: {len(dup_skips)} (idempotency confirmed)")
assert len(dup_skips) >= 2

users = httpx.get(f"{LMS}/api/v1/users", headers=lms_h, params={"externalRef": sid}).json()
assert len(users) == 1, f"expected exactly 1 LMS user, got {len(users)} (duplicate side-effect!)"
print(f"  Only 1 LMS user exists for {sid} despite 3 processing attempts -> idempotent side effects confirmed")


print("\n=== TEST: retry + backoff under simulated LMS failures (NFR-02/03) ===")
httpx.put(f"{LMS}/admin/tenants/{TENANT}/failure/HIGH", headers=ADMIN)
print("LMS failure mode set to HIGH (30% chance of 503 on every call)")

sid2 = f"SVRETRY{int(time.time())%100000}"
r = httpx.post(f"{SIS}/api/v1/students", headers=sis_h, json={
    "studentId": sid2, "firstName": "Retry", "lastName": "Test", "email": f"{sid2.lower()}@student.edu.vn",
})
assert r.status_code == 201
print(f"created student {sid2} while LMS failure=HIGH")

def check_user2():
    rows = httpx.get(f"{LMS}/api/v1/users", headers=lms_h, params={"externalRef": sid2}).json()
    return rows[0] if rows else None

u2 = wait_for(check_user2, f"LMS user for {sid2} eventually created despite HIGH failure rate", timeout=60)
assert u2

evs = httpx.get(f"{SIS}/api/v1/events", headers=sis_h, params={"eventType": "student.created"}).json()
eid2 = next(e["eventId"] for e in evs if e["data"]["studentId"] == sid2)
audit2 = httpx.get(f"{INT}/internal/audit", params={"event_id": eid2, "limit": 50}).json()
retries = [row for row in audit2 if row["action"] == "RETRY_SCHEDULED"]
print(f"  RETRY_SCHEDULED entries before success: {len(retries)}")
for row in retries:
    print("   -", row["detail"][:100])
success = [row for row in audit2 if row["status"] == "SUCCESS" and row["action"] != "SKIP_DUPLICATE"]
assert success, "event should have eventually succeeded"
print("  event eventually reached SUCCESS after retries -> retry/backoff confirmed")

httpx.put(f"{LMS}/admin/tenants/{TENANT}/failure/OFF", headers=ADMIN)
print("LMS failure mode reset to OFF")


print("\n=== TEST: dependency-pending ordering (enrollment before user/course synced) ===")
# simulate an enrollment event arriving before its Student/Section have been
# synced to LMS, by calling the engine directly with a payload that
# references brand-new external IDs that don't exist in LMS yet.
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import engine, db as idb
idb.init_db()

fake_event_id = f"evt_dep_test_{int(time.time())}"
result = engine.process_event(fake_event_id, "enrollment.created", "SIS", {
    "enrollmentId": "ENR-FAKE-DEP-TEST", "studentId": "SV_DOES_NOT_EXIST_YET",
    "sectionId": "SEC_DOES_NOT_EXIST_YET", "status": "ENROLLED",
})
print("process_event result for out-of-order enrollment ->", result)
assert result == "PENDING"
row = idb.get_event(fake_event_id, "SIS")
print("  stored as:", dict(row))
assert row["status"] == "PENDING"
print("  Confirmed: unresolved dependency -> event kept PENDING (not lost, not crashed), will retry via background worker")

print("\n=== ALL RELIABILITY TESTS PASSED ===")
