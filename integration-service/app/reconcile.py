"""
Reconciliation (NFR-06).

Webhook/polling only reacts to *new* events. Data that already existed in
SIS before the Integration Service ever ran (GAP-11) needs a sweep that
compares full state and repairs it. This module re-uses the exact same
handler functions as the live event path, so "reconciled" and
"event-driven" data end up identical and idempotent with each other.

Covers (minimum required): Student -> LMS User, Section -> LMS Course.
Also included (recommended by spec 5.2/NFR-06): Enrollment -> Membership,
so a full reset can be healed in one call.
"""
from __future__ import annotations
import logging
import time

from . import db
from .clients import sis_client, RetryableError, PermanentError
from .handlers import (
    sync_student_to_lms_user, sync_section_to_lms_course,
    sync_enrollment_to_membership,
)
from .config import settings

log = logging.getLogger("integration")

# Reconciliation is a one-shot bulk sweep, so unlike the live event path it
# is allowed to simply *wait out* a 429/503 and retry in place (NFR-12)
# instead of re-queueing - there is no separate "event" to track.
_RECONCILE_MAX_ATTEMPTS = 5


def _run(items: list[dict], label: str, handler, int_code: str, id_field: str) -> dict:
    result = {"checked": 0, "created_or_updated": 0, "noop": 0, "errors": 0}
    for item in items:
        result["checked"] += 1
        entity_id = item.get(id_field, "?")
        # proactive pacing (NFR-12): stay well under the ~100 req/min lab
        # limit during a bulk sweep instead of relying purely on reactive
        # 429 handling, which would otherwise dominate reconciliation time.
        time.sleep(settings.RECONCILE_PACING_SECONDS)
        attempt = 0
        while True:
            attempt += 1
            try:
                action = handler(item)
                if action.startswith("NOOP"):
                    result["noop"] += 1
                else:
                    result["created_or_updated"] += 1
                db.audit(None, f"reconciliation.{label}", "SIS", "LMS", int_code,
                          f"RECONCILE:{action}", "SUCCESS", entity_id)
                break
            except RetryableError as e:
                if attempt >= _RECONCILE_MAX_ATTEMPTS:
                    result["errors"] += 1
                    db.audit(None, f"reconciliation.{label}", "SIS", "LMS", int_code,
                              "RECONCILE_GIVE_UP", "FAILED", f"{entity_id}: {e}")
                    break
                delay = e.retry_after or min(settings.BACKOFF_MAX_SECONDS,
                                              settings.BACKOFF_BASE_SECONDS * (2 ** attempt))
                db.audit(None, f"reconciliation.{label}", "SIS", "LMS", int_code,
                          "RECONCILE_RETRY", "RETRY", f"{entity_id}: {e} (waiting {delay}s)")
                time.sleep(delay)
            except PermanentError as e:
                result["errors"] += 1
                db.audit(None, f"reconciliation.{label}", "SIS", "LMS", int_code,
                          "RECONCILE_ERROR", "FAILED", f"{entity_id}: {e}")
                break
            except Exception as e:  # noqa: BLE001
                result["errors"] += 1
                db.audit(None, f"reconciliation.{label}", "SIS", "LMS", int_code,
                          "RECONCILE_UNEXPECTED_ERROR", "FAILED", f"{entity_id}: {e}")
                log.exception("reconciliation error on %s %s", label, entity_id)
                break
    return result


def reconcile_students() -> dict:
    students = sis_client.list_students()
    return _run(students, "student", sync_student_to_lms_user, "INT-01", "studentId")


def reconcile_sections() -> dict:
    sections = sis_client.list_sections()
    return _run(sections, "section", sync_section_to_lms_course, "INT-02", "sectionId")


def reconcile_enrollments() -> dict:
    all_enrollments = sis_client.get("/api/v1/enrollments")
    enrollments = [e for e in all_enrollments if e.get("status") == "ENROLLED"]
    return _run(enrollments, "enrollment", sync_enrollment_to_membership, "INT-03", "enrollmentId")


def reconcile_all(include_memberships: bool = True) -> dict:
    result = {
        "students": reconcile_students(),
        "sections": reconcile_sections(),
    }
    if include_memberships:
        result["enrollments"] = reconcile_enrollments()
    return result
