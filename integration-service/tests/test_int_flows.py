"""
Happy-path tests for every mandatory/optional integration requirement.
Each test creates real data on the (test-instance) SIS/LMS, drives it
through app.engine.process_event exactly like the poller would, and
asserts the resulting state on the *other* system.
"""
import time


def _create_student(c, student_id, **overrides):
    body = {"studentId": student_id, "firstName": "An", "lastName": "Nguyen Van",
             "email": f"{student_id.lower()}@student.edu.vn", "status": "ACTIVE"}
    body.update(overrides)
    return c.clients.sis_client.post("/api/v1/students", json_body=body)


def _create_section(c, section_id, course_code="INT402", lecturer_id="GV0001"):
    return c.clients.sis_client.post("/api/v1/sections", json_body={
        "sectionId": section_id, "courseCode": course_code, "semesterCode": "2026-1",
        "lecturerId": lecturer_id,
    })


def _events(c, source, event_type):
    client = c.clients.sis_client if source == "SIS" else c.clients.lms_client
    return client.get_events(event_type=event_type)


def _process_all_new(c, source, event_type):
    """Fetch and process every event of a type that hasn't been processed yet."""
    results = []
    for ev in _events(c, source, event_type):
        results.append(c.engine.process_event(ev["eventId"], ev["eventType"], source, ev["data"]))
    return results


def test_int01_student_created_creates_lms_user(app_modules):
    c = app_modules
    sid = "SVX0001"
    _create_student(c, sid)
    results = _process_all_new(c, "SIS", "student.created")
    assert "DONE" in results

    user = c.clients.lms_client.find_user_by_external_ref(sid)
    assert user is not None
    assert user["username"] == sid
    assert user["enabled"] is True
    assert c.db.get_mapping("STUDENT_USER", "TEST01", sid) == str(user["id"])


def test_int02_section_created_creates_lms_course(app_modules):
    c = app_modules
    secid = "SECX0001"
    _create_section(c, secid, lecturer_id="GV0002")
    results = _process_all_new(c, "SIS", "section.created")
    assert "DONE" in results

    course = c.clients.lms_client.find_course_by_external_code(secid)
    assert course is not None
    assert course["teacherExternalRef"] == "GV0002"


def test_int03_enrollment_created_adds_membership(app_modules):
    c = app_modules
    sid, secid = "SVX0002", "SECX0002"
    _create_student(c, sid)
    _create_section(c, secid)
    _process_all_new(c, "SIS", "student.created")
    _process_all_new(c, "SIS", "section.created")

    c.clients.sis_client.post("/api/v1/enrollments", json_body={"studentId": sid, "sectionId": secid})
    results = _process_all_new(c, "SIS", "enrollment.created")
    assert results == ["DONE"]

    user = c.clients.lms_client.find_user_by_external_ref(sid)
    course = c.clients.lms_client.find_course_by_external_code(secid)
    members = c.clients.lms_client.get_members(course["id"])
    assert any(m["userId"] == user["id"] for m in members)


def test_int04_enrollment_dropped_removes_membership(app_modules):
    c = app_modules
    sid, secid = "SVX0003", "SECX0003"
    _create_student(c, sid)
    _create_section(c, secid)
    _process_all_new(c, "SIS", "student.created")
    _process_all_new(c, "SIS", "section.created")
    enr = c.clients.sis_client.post("/api/v1/enrollments", json_body={"studentId": sid, "sectionId": secid})
    _process_all_new(c, "SIS", "enrollment.created")

    c.clients.sis_client.delete(f"/api/v1/enrollments/{enr['enrollmentId']}")
    results = _process_all_new(c, "SIS", "enrollment.dropped")
    assert results == ["DONE"]

    user = c.clients.lms_client.find_user_by_external_ref(sid)
    course = c.clients.lms_client.find_course_by_external_code(secid)
    members = c.clients.lms_client.get_members(course["id"])
    assert not any(m["userId"] == user["id"] for m in members)


def test_int05_student_status_disables_lms_user(app_modules):
    c = app_modules
    sid = "SVX0004"
    _create_student(c, sid)
    _process_all_new(c, "SIS", "student.created")

    c.clients.sis_client.patch(f"/api/v1/students/{sid}", json_body={"status": "SUSPENDED"})
    results = _process_all_new(c, "SIS", "student.updated")
    assert results == ["DONE"]

    user = c.clients.lms_client.find_user_by_external_ref(sid)
    assert user["enabled"] is False


def test_int06_grade_published_reverse_syncs_to_sis(app_modules):
    c = app_modules
    sid, secid = "SVX0005", "SECX0005"
    _create_student(c, sid)
    _create_section(c, secid)
    _process_all_new(c, "SIS", "student.created")
    _process_all_new(c, "SIS", "section.created")
    c.clients.sis_client.post("/api/v1/enrollments", json_body={"studentId": sid, "sectionId": secid})
    _process_all_new(c, "SIS", "enrollment.created")

    user = c.clients.lms_client.find_user_by_external_ref(sid)
    course = c.clients.lms_client.find_course_by_external_code(secid)
    g = c.clients.lms_client.put(f"/api/v1/courses/{course['id']}/grades", json_body={"userId": user["id"], "finalGrade": 92})
    c.clients.lms_client.post(f"/api/v1/grades/{g['gradeId']}/publish")

    results = _process_all_new(c, "LMS", "grade.published")
    assert results == ["DONE"]

    grades = c.clients.sis_client.get("/api/v1/grades")
    match = [x for x in grades if x["studentId"] == sid and x["sectionId"] == secid]
    assert match and abs(match[0]["finalScore"] - 9.2) < 0.01


def test_int07_lecturer_change_patches_course(app_modules):
    c = app_modules
    secid = "SECX0007"
    _create_section(c, secid, lecturer_id="GV0001")
    _process_all_new(c, "SIS", "section.created")

    c.clients.sis_client.patch(f"/api/v1/sections/{secid}", json_body={"lecturerId": "GV0009"})
    results = _process_all_new(c, "SIS", "section.updated")
    assert results == ["DONE"]

    course = c.clients.lms_client.find_course_by_external_code(secid)
    assert course["teacherExternalRef"] == "GV0009"


def test_int08_learning_risk_creates_advising_alert(app_modules):
    c = app_modules
    sid, secid = "SVX0008", "SECX0008"
    _create_student(c, sid)
    _create_section(c, secid)
    _process_all_new(c, "SIS", "student.created")
    _process_all_new(c, "SIS", "section.created")

    user = c.clients.lms_client.find_user_by_external_ref(sid)
    course = c.clients.lms_client.find_course_by_external_code(secid)
    c.clients.lms_client.post(f"/api/v1/courses/{course['id']}/risk", json_body={
        "userId": user["id"], "completionPercent": 5, "inactiveDays": 30,
    })
    results = _process_all_new(c, "LMS", "learner.at_risk")
    assert results == ["DONE"]

    alerts = c.clients.sis_client.get("/api/v1/advising/alerts", params={"studentId": sid})
    assert len(alerts) == 1
    assert alerts[0]["sectionId"] == secid


def test_int08_normal_risk_does_not_emit_event_or_alert(app_modules):
    """completionPercent/inactiveDays below the AT_RISK threshold -> LMS does
    not even emit learner.at_risk, so nothing should be created in SIS."""
    c = app_modules
    sid, secid = "SVX0009", "SECX0009"
    _create_student(c, sid)
    _create_section(c, secid)
    _process_all_new(c, "SIS", "student.created")
    _process_all_new(c, "SIS", "section.created")

    user = c.clients.lms_client.find_user_by_external_ref(sid)
    course = c.clients.lms_client.find_course_by_external_code(secid)
    c.clients.lms_client.post(f"/api/v1/courses/{course['id']}/risk", json_body={
        "userId": user["id"], "completionPercent": 80, "inactiveDays": 1,
    })
    results = _process_all_new(c, "LMS", "learner.at_risk")
    assert results == []  # no learner.at_risk event was emitted at all

    alerts = c.clients.sis_client.get("/api/v1/advising/alerts", params={"studentId": sid})
    assert alerts == []
