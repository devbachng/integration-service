"""
Ad-hoc smoke test against the LIVE running services (SIS:8001, LMS:8002,
Integration Service:8000). Not the formal pytest suite (that comes next) -
this is a quick end-to-end walk-through with printed evidence, used to
generate the test report / catch integration bugs early.
"""
import time
import httpx

SIS = "http://127.0.0.1:8001"
LMS = "http://127.0.0.1:8002"
INT = "http://127.0.0.1:8000"
TENANT = "TEAM01"


def token(base, secret="student-secret"):
    r = httpx.post(f"{base}/api/v1/auth/token", json={"clientId": "TEST", "clientSecret": secret, "tenantId": TENANT})
    r.raise_for_status()
    return r.json()["accessToken"]


sis_tok = token(SIS)
lms_tok = token(LMS)
sis_h = {"Authorization": f"Bearer {sis_tok}", "X-Tenant-ID": TENANT}
lms_h = {"Authorization": f"Bearer {lms_tok}", "X-Tenant-ID": TENANT}


def wait_for(fn, desc, timeout=20, interval=1.0):
    start = time.time()
    while time.time() - start < timeout:
        v = fn()
        if v:
            print(f"  OK  ({time.time()-start:.1f}s) {desc}")
            return v
        time.sleep(interval)
    print(f"  FAIL (timeout {timeout}s) {desc}")
    return None


print("=== INT-01: student.created -> LMS User ===")
sid = f"SVNEW{int(time.time())%100000}"
r = httpx.post(f"{SIS}/api/v1/students", headers=sis_h, json={
    "studentId": sid, "firstName": "Test01", "lastName": "Nguyen", "email": f"{sid.lower()}@student.edu.vn",
})
print("SIS create_student ->", r.status_code, r.json())

def check_user():
    rows = httpx.get(f"{LMS}/api/v1/users", headers=lms_h, params={"externalRef": sid}).json()
    return rows[0] if rows else None

u = wait_for(check_user, f"LMS user created for {sid}")
assert u and u["username"] == sid and u["enabled"] is True
print("  LMS user:", u)


print("\n=== INT-02: section.created -> LMS Course ===")
secid = f"SEC-NEW-{int(time.time())%100000}"
r = httpx.post(f"{SIS}/api/v1/sections", headers=sis_h, json={
    "sectionId": secid, "courseCode": "INT402", "semesterCode": "2026-1", "lecturerId": "GV0001",
})
print("SIS create_section ->", r.status_code, r.json())

def check_course():
    rows = httpx.get(f"{LMS}/api/v1/courses", headers=lms_h, params={"externalCode": secid}).json()
    return rows[0] if rows else None

c = wait_for(check_course, f"LMS course created for {secid}")
assert c and c["teacherExternalRef"] == "GV0001"
print("  LMS course:", c)


print("\n=== INT-03: enrollment.created -> Membership ===")
r = httpx.post(f"{SIS}/api/v1/enrollments", headers=sis_h, json={"studentId": sid, "sectionId": secid})
print("SIS create_enrollment ->", r.status_code, r.json())

def check_member():
    rows = httpx.get(f"{LMS}/api/v1/courses/{c['id']}/members", headers=lms_h).json()
    return any(m["userId"] == u["id"] for m in rows)

ok = wait_for(check_member, f"membership {sid}->{secid} active")
assert ok


print("\n=== INT-04: enrollment.dropped -> Membership removed ===")
enrs = httpx.get(f"{SIS}/api/v1/enrollments", headers=sis_h, params={"studentId": sid, "sectionId": secid}).json()
enr_id = enrs[0]["enrollmentId"]
r = httpx.delete(f"{SIS}/api/v1/enrollments/{enr_id}", headers=sis_h)
print("SIS drop_enrollment ->", r.status_code, r.json())

def check_member_gone():
    rows = httpx.get(f"{LMS}/api/v1/courses/{c['id']}/members", headers=lms_h).json()
    return not any(m["userId"] == u["id"] for m in rows)

ok = wait_for(check_member_gone, f"membership {sid}->{secid} removed")
assert ok


print("\n=== INT-05: student.updated (status) -> LMS user enabled/disabled ===")
before = check_user()
print("  BEFORE: LMS user enabled =", before["enabled"])
r = httpx.patch(f"{SIS}/api/v1/students/{sid}", headers=sis_h, json={"status": "SUSPENDED"})
print("SIS patch_student ->", r.status_code, r.json())

def check_disabled():
    row = check_user()
    return row if (row and row["enabled"] is False) else None

ok = wait_for(check_disabled, f"LMS user {sid} disabled after SUSPENDED")
assert ok
print("  AFTER:  LMS user enabled =", ok["enabled"])


print("\n=== INT-07: section.updated (lecturer change) -> Course patched ===")
before = check_course()
print("  BEFORE: teacherExternalRef =", before["teacherExternalRef"])
r = httpx.patch(f"{SIS}/api/v1/sections/{secid}", headers=sis_h, json={"lecturerId": "GV0007"})
print("SIS patch_section ->", r.status_code, r.json())

def check_lecturer():
    row = check_course()
    return row if (row and row["teacherExternalRef"] == "GV0007") else None

ok = wait_for(check_lecturer, f"LMS course teacherExternalRef updated to GV0007")
assert ok
print("  AFTER:  teacherExternalRef =", ok["teacherExternalRef"])


print("\n=== INT-06: grade.published (LMS) -> SIS grade reverse sync ===")
before = httpx.get(f"{SIS}/api/v1/grades", headers=sis_h).json()
before_match = [row for row in before if row["studentId"] == sid and row["sectionId"] == secid]
print("  BEFORE: SIS grade row exists? ->", bool(before_match))
# re-enroll first (needed for SIS grade upsert, which requires an active enrollment)
r = httpx.patch(f"{SIS}/api/v1/students/{sid}", headers=sis_h, json={"status": "ACTIVE"})
r = httpx.post(f"{SIS}/api/v1/enrollments", headers=sis_h, json={"studentId": sid, "sectionId": secid})
print("re-enroll ->", r.status_code)
time.sleep(2)
g = httpx.put(f"{LMS}/api/v1/courses/{c['id']}/grades", headers=lms_h, json={"userId": u["id"], "finalGrade": 85})
print("LMS upsert_grade ->", g.status_code, g.json())
grade_id = g.json()["gradeId"]
p = httpx.post(f"{LMS}/api/v1/grades/{grade_id}/publish", headers=lms_h)
print("LMS publish_grade ->", p.status_code, p.json())

def check_sis_grade():
    rows = httpx.get(f"{SIS}/api/v1/grades", headers=sis_h).json()
    for row in rows:
        if row["studentId"] == sid and row["sectionId"] == secid:
            return row
    return None

ok = wait_for(check_sis_grade, f"SIS grade for {sid}/{secid} == 8.5")
assert ok and abs(ok["finalScore"] - 8.5) < 0.01
print("  AFTER:  SIS grade:", ok)


print("\n=== INT-08: learner.at_risk (LMS) -> SIS advising alert ===")
before = httpx.get(f"{SIS}/api/v1/advising/alerts", headers=sis_h, params={"studentId": sid}).json()
print("  BEFORE: existing advising alerts for", sid, "->", before)
risk = httpx.post(f"{LMS}/api/v1/courses/{c['id']}/risk", headers=lms_h, json={
    "userId": u["id"], "completionPercent": 10, "inactiveDays": 20,
})
print("LMS create_risk ->", risk.status_code, risk.json())

def check_alert():
    rows = httpx.get(f"{SIS}/api/v1/advising/alerts", headers=sis_h, params={"studentId": sid}).json()
    return rows[0] if rows else None

ok = wait_for(check_alert, f"SIS advising alert created for {sid}")
assert ok
print("  AFTER:  SIS alert:", ok)

print("\n=== ALL INT-01..08 LIVE CHECKS PASSED ===")
print("student_id =", sid, "| section_id =", secid)
