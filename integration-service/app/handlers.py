"""
INT-01 .. INT-08 business logic.

Every handler:
  * receives the *source event payload* (dict, already the `data` part of
    the event envelope)
  * resolves IDs through the local mapping store first, falls back to a
    live lookup by external reference/code (self-healing if the mapping
    row was lost, per spec 25.6)
  * returns a short human-readable action string used for the audit log
  * raises DependencyPendingError if a dependency (User/Course) is not
    synced yet -> the event is kept PENDING and retried automatically
  * raises PermanentError / RetryableError (via the HTTP clients) which
    the engine classifies (see app/engine.py)
"""
from __future__ import annotations
import time
from typing import Optional

from . import db
from .clients import sis_client, lms_client, PermanentError, DependencyPendingError
from .config import settings

ENTITY_STUDENT_USER = "STUDENT_USER"
ENTITY_SECTION_COURSE = "SECTION_COURSE"

TENANT = settings.TENANT_ID

# ---- small TTL cache for the SIS course catalog (courseCode -> courseName) --
_course_catalog: dict[str, str] = {}
_course_catalog_at: float = 0.0
_CATALOG_TTL = 30.0


def _course_name(course_code: str) -> Optional[str]:
    global _course_catalog, _course_catalog_at
    if time.time() - _course_catalog_at > _CATALOG_TTL:
        try:
            rows = sis_client.list_courses()
            _course_catalog = {c["courseCode"]: c["courseName"] for c in rows}
            _course_catalog_at = time.time()
        except Exception:
            pass  # keep stale cache rather than fail the whole handler
    return _course_catalog.get(course_code)


def status_to_enabled(status: str) -> bool:
    return status == "ACTIVE"


# =============================================================== INT-01/05
def sync_student_to_lms_user(data: dict) -> str:
    """student.created / student.updated -> LMS User (identity + enabled)."""
    student_id = data["studentId"]
    display_name = f'{data["lastName"]} {data["firstName"]}'.strip()
    email = data["email"]
    enabled = status_to_enabled(data.get("status", "ACTIVE"))

    lms_user = lms_client.find_user_by_external_ref(student_id)

    if lms_user:
        changes = {}
        if lms_user.get("displayName") != display_name:
            changes["displayName"] = display_name
        if lms_user.get("emailAddress") != email:
            changes["emailAddress"] = email
        if bool(lms_user.get("enabled")) != enabled:
            changes["enabled"] = enabled
        if changes:
            lms_client.patch_user(lms_user["id"], **changes)
            action = f"PATCH_USER fields={list(changes.keys())}"
        else:
            action = "NOOP_ALREADY_IN_SYNC"
        db.set_mapping(ENTITY_STUDENT_USER, TENANT, student_id, lms_user["id"])
        return action

    try:
        created = lms_client.create_user(
            username=student_id, display_name=display_name, email=email,
            user_type="LEARNER", enabled=enabled, external_ref=student_id,
        )
    except PermanentError as e:
        if e.status_code == 409:
            existing = lms_client.find_user_by_external_ref(student_id)
            if existing:
                db.set_mapping(ENTITY_STUDENT_USER, TENANT, student_id, existing["id"])
                return "RECOVERED_FROM_409_USER_EXISTS"
        raise
    db.set_mapping(ENTITY_STUDENT_USER, TENANT, student_id, created["id"])
    return "CREATE_USER"


# =============================================================== INT-02/07
def sync_section_to_lms_course(data: dict) -> str:
    """section.created / section.updated -> LMS Course (create-or-patch)."""
    section_id = data["sectionId"]
    course_code = data["courseCode"]
    lecturer_id = data.get("lecturerId")
    term = data.get("semesterCode", "2026-1")
    course_name = _course_name(course_code)
    title = f"{course_code} - {course_name}" if course_name else course_code

    course = lms_client.find_course_by_external_code(section_id)

    if course:
        changes = {}
        if lecturer_id and course.get("teacherExternalRef") != lecturer_id:
            changes["teacherExternalRef"] = lecturer_id
        if changes:
            lms_client.patch_course(course["id"], **changes)
            action = f"PATCH_COURSE fields={list(changes.keys())}"
        else:
            action = "NOOP_ALREADY_IN_SYNC"
        db.set_mapping(ENTITY_SECTION_COURSE, TENANT, section_id, course["id"])
        return action

    try:
        created = lms_client.create_course(
            external_code=section_id, title=title, term=term,
            state="PUBLISHED", teacher_external_ref=lecturer_id,
        )
    except PermanentError as e:
        if e.status_code == 409:
            existing = lms_client.find_course_by_external_code(section_id)
            if existing:
                db.set_mapping(ENTITY_SECTION_COURSE, TENANT, section_id, existing["id"])
                return "RECOVERED_FROM_409_COURSE_EXISTS"
        raise
    db.set_mapping(ENTITY_SECTION_COURSE, TENANT, section_id, created["id"])
    return "CREATE_COURSE"


# ------------------------------------------------------------- id resolvers
def _resolve_user_id(student_id: str) -> Optional[int]:
    mapped = db.get_mapping(ENTITY_STUDENT_USER, TENANT, student_id)
    if mapped:
        return int(mapped)
    u = lms_client.find_user_by_external_ref(student_id)
    if u:
        db.set_mapping(ENTITY_STUDENT_USER, TENANT, student_id, u["id"])
        return int(u["id"])
    return None


def _resolve_course_id(section_id: str) -> Optional[int]:
    mapped = db.get_mapping(ENTITY_SECTION_COURSE, TENANT, section_id)
    if mapped:
        return int(mapped)
    c = lms_client.find_course_by_external_code(section_id)
    if c:
        db.set_mapping(ENTITY_SECTION_COURSE, TENANT, section_id, c["id"])
        return int(c["id"])
    return None


# =================================================================== INT-03
def sync_enrollment_to_membership(data: dict) -> str:
    student_id = data["studentId"]
    section_id = data["sectionId"]
    user_id = _resolve_user_id(student_id)
    course_id = _resolve_course_id(section_id)
    missing = []
    if not user_id:
        missing.append("LMS User")
    if not course_id:
        missing.append("LMS Course")
    if missing:
        raise DependencyPendingError(f"waiting for: {', '.join(missing)}")
    try:
        lms_client.add_member(course_id, user_id, role="STUDENT")
        return "ADD_MEMBER"
    except PermanentError as e:
        if e.status_code == 409:
            return "NOOP_MEMBERSHIP_ALREADY_ACTIVE"
        raise


# =================================================================== INT-04
def sync_enrollment_drop(data: dict) -> str:
    student_id = data["studentId"]
    section_id = data["sectionId"]
    user_id = _resolve_user_id(student_id)
    course_id = _resolve_course_id(section_id)
    if not user_id or not course_id:
        # Nothing to remove if either side never existed - final state is
        # already correct (no membership), so treat as idempotent success.
        return "NOOP_NOTHING_TO_REMOVE"
    try:
        lms_client.remove_member(course_id, user_id, role="STUDENT")
        return "REMOVE_MEMBER"
    except PermanentError as e:
        if e.status_code == 404:
            return "NOOP_MEMBERSHIP_ALREADY_REMOVED"
        raise


# =================================================================== INT-06
def sync_grade_to_sis(data: dict) -> str:
    student_id = data.get("userExternalRef")
    section_id = data.get("courseExternalCode")
    final_grade = data.get("finalGrade")
    if not student_id or not section_id or final_grade is None:
        raise PermanentError("grade.published missing external references or finalGrade")
    score10 = round(float(final_grade) / 10.0, 2)
    sis_client.put_grade(student_id, section_id, score10, letter_grade=None, source="LMS")
    return f"PUT_GRADE finalScore={score10}"


# =================================================================== INT-08
def sync_risk_to_alert(data: dict) -> str:
    student_id = data.get("userExternalRef")
    section_id = data.get("courseExternalCode")
    if not student_id or not section_id:
        raise PermanentError("learner.at_risk missing external references")
    details = (
        f"completionPercent={data.get('completionPercent')}, "
        f"inactiveDays={data.get('inactiveDays')}"
    )
    sis_client.post_advising_alert(student_id, section_id, data.get("riskType", "AT_RISK"), details)
    return "CREATE_ALERT"


# eventType -> (INT code, handler, source system, target system)
EVENT_ROUTES = {
    "student.created": ("INT-01", sync_student_to_lms_user, "SIS", "LMS"),
    "student.updated": ("INT-01/05", sync_student_to_lms_user, "SIS", "LMS"),
    "section.created": ("INT-02", sync_section_to_lms_course, "SIS", "LMS"),
    "section.updated": ("INT-07", sync_section_to_lms_course, "SIS", "LMS"),
    "enrollment.created": ("INT-03", sync_enrollment_to_membership, "SIS", "LMS"),
    "enrollment.dropped": ("INT-04", sync_enrollment_drop, "SIS", "LMS"),
    "grade.published": ("INT-06", sync_grade_to_sis, "LMS", "SIS"),
    "learner.at_risk": ("INT-08", sync_risk_to_alert, "LMS", "SIS"),
}
