"""
The processing pipeline shared by the poller and the webhook receiver.

    process_event(event_id, event_type, source, payload)

implements:
  NFR-01 Idempotency      - checks processed_events before calling the handler
  NFR-02 Retry             - RetryableError -> scheduled retry, honours Retry-After
  NFR-03 No infinite retry - PermanentError -> FAILED immediately (no retry loop);
                              RetryableError capped at MAX_RETRIES -> FAILED
  NFR-04 Audit log         - one audit_log row per attempt
"""
from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone

from . import db
from .clients import RetryableError, PermanentError, DependencyPendingError
from .handlers import EVENT_ROUTES
from .config import settings

log = logging.getLogger("integration")


def _iso_after(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _backoff_seconds(retry_count: int) -> float:
    return min(settings.BACKOFF_MAX_SECONDS, settings.BACKOFF_BASE_SECONDS * (2 ** retry_count))


def process_event(event_id: str, event_type: str, source: str, payload: dict) -> str:
    """Returns a short status string: DONE | SKIPPED | PENDING | FAILED | IGNORED."""
    route = EVENT_ROUTES.get(event_type)
    if not route:
        return "IGNORED"  # event type not relevant to this Integration Service
    int_code, handler, _src_sys, tgt_sys = route

    existing = db.get_event(event_id, source)
    if existing is not None and existing["status"] == "DONE":
        db.audit(event_id, event_type, source, tgt_sys, int_code, "SKIP_DUPLICATE", "SUCCESS",
                  "eventId already processed - idempotent no-op (NFR-01)")
        return "SKIPPED"

    retry_count = existing["retry_count"] if existing is not None else 0

    try:
        action = handler(payload)
        db.upsert_event(event_id, source, event_type, "DONE", payload, retry_count=retry_count)
        db.audit(event_id, event_type, source, tgt_sys, int_code, action, "SUCCESS")
        log.info("event=%s type=%s int=%s action=%s status=DONE", event_id, event_type, int_code, action)
        return "DONE"

    except DependencyPendingError as e:
        next_retry_count = retry_count + 1
        next_retry = _iso_after(_backoff_seconds(min(next_retry_count, 4)))  # dependency waits, cap growth
        db.upsert_event(event_id, source, event_type, "PENDING", payload,
                         retry_count=next_retry_count, last_error=str(e), next_retry_at=next_retry)
        db.audit(event_id, event_type, source, tgt_sys, int_code, "WAIT_DEPENDENCY", "RETRY", str(e))
        log.info("event=%s type=%s int=%s status=PENDING reason=dependency detail=%s",
                  event_id, event_type, int_code, e)
        return "PENDING"

    except RetryableError as e:
        next_retry_count = retry_count + 1
        if next_retry_count > settings.MAX_RETRIES:
            db.upsert_event(event_id, source, event_type, "FAILED", payload,
                             retry_count=next_retry_count, last_error=str(e))
            db.audit(event_id, event_type, source, tgt_sys, int_code, "GIVE_UP_MAX_RETRIES", "FAILED", str(e))
            log.warning("event=%s type=%s int=%s status=FAILED reason=max_retries detail=%s",
                        event_id, event_type, int_code, e)
            return "FAILED"
        delay = e.retry_after if e.retry_after else _backoff_seconds(retry_count)
        next_retry = _iso_after(delay)
        db.upsert_event(event_id, source, event_type, "PENDING", payload,
                         retry_count=next_retry_count, last_error=str(e), next_retry_at=next_retry)
        db.audit(event_id, event_type, source, tgt_sys, int_code, "RETRY_SCHEDULED", "RETRY",
                  f"{e} (retry_count={next_retry_count}, delay={delay}s)")
        log.info("event=%s type=%s int=%s status=PENDING retry_count=%s delay=%.1fs",
                  event_id, event_type, int_code, next_retry_count, delay)
        return "PENDING"

    except PermanentError as e:
        db.upsert_event(event_id, source, event_type, "FAILED", payload,
                         retry_count=retry_count, last_error=str(e))
        db.audit(event_id, event_type, source, tgt_sys, int_code, "PERMANENT_ERROR", "FAILED", str(e))
        log.warning("event=%s type=%s int=%s status=FAILED reason=permanent detail=%s",
                    event_id, event_type, int_code, e)
        return "FAILED"

    except Exception as e:  # noqa: BLE001 - last line of defence, never crash the worker
        next_retry_count = retry_count + 1
        if next_retry_count > settings.MAX_RETRIES:
            db.upsert_event(event_id, source, event_type, "FAILED", payload,
                             retry_count=next_retry_count, last_error=f"unexpected: {e}")
            db.audit(event_id, event_type, source, tgt_sys, int_code, "UNEXPECTED_ERROR_GIVE_UP", "FAILED", str(e))
            return "FAILED"
        next_retry = _iso_after(_backoff_seconds(retry_count))
        db.upsert_event(event_id, source, event_type, "PENDING", payload,
                         retry_count=next_retry_count, last_error=f"unexpected: {e}", next_retry_at=next_retry)
        db.audit(event_id, event_type, source, tgt_sys, int_code, "UNEXPECTED_ERROR_RETRY", "RETRY", str(e))
        log.exception("unexpected error processing event=%s type=%s", event_id, event_type)
        return "PENDING"


def retry_pending() -> int:
    """Re-drive every PENDING event whose next_retry_at has passed. Returns count processed."""
    rows = db.pending_events()
    import json
    n = 0
    for row in rows:
        payload = json.loads(row["payload"]) if row["payload"] else {}
        process_event(row["event_id"], row["event_type"], row["source"], payload)
        n += 1
    return n
