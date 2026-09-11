"""
Reconciliation tests: pre-existing SIS/LMS data (created before the
Integration Service ever ran, or via direct DB seed) must be healed by a
reconciliation sweep without duplicating anything.
"""


def test_reconcile_creates_missing_mappings_for_preexisting_data(app_modules):
    c = app_modules
    # tenant reset already seeded some students/sections directly in SIS/LMS
    # with ZERO mappings known to the (freshly created) Integration Service DB
    before = c.db.stats()
    assert before["mappings"] == 0

    result = c.reconcile.reconcile_all(include_memberships=True)

    assert result["students"]["errors"] == 0
    assert result["sections"]["errors"] == 0
    assert result["enrollments"]["errors"] == 0
    assert result["students"]["checked"] > 0

    after = c.db.stats()
    assert after["mappings"] == result["students"]["checked"] + result["sections"]["checked"]


def test_reconcile_is_idempotent_second_pass_is_all_noop(app_modules):
    c = app_modules
    c.reconcile.reconcile_all(include_memberships=True)
    second = c.reconcile.reconcile_all(include_memberships=True)

    assert second["students"]["created_or_updated"] == 0
    assert second["sections"]["created_or_updated"] == 0
    assert second["students"]["noop"] == second["students"]["checked"]


def test_reconcile_repairs_drifted_enabled_flag(app_modules):
    """If a student was suspended in SIS while the Integration Service was
    down, the next reconciliation pass must catch and fix the drift."""
    c = app_modules
    c.reconcile.reconcile_all(include_memberships=False)

    students = c.clients.sis_client.list_students()
    sid = students[0]["studentId"]
    c.clients.sis_client.patch(f"/api/v1/students/{sid}", json_body={"status": "SUSPENDED"})

    user_before = c.clients.lms_client.find_user_by_external_ref(sid)
    assert user_before["enabled"] is True  # LMS not yet aware

    result = c.reconcile.reconcile_students()
    assert result["created_or_updated"] >= 1

    user_after = c.clients.lms_client.find_user_by_external_ref(sid)
    assert user_after["enabled"] is False
