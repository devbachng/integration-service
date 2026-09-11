from __future__ import annotations
import logging
import threading
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from . import db, engine, poller, reconcile
from .config import settings
from .clients import sis_client, lms_client

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("integration")

app = FastAPI(
    title="University Integration Service",
    version="1.0.0",
    description="UniSIS <-> UniLearn LMS Integration Service (INT-01..INT-08)",
)

_stop_event = threading.Event()
_threads: list[threading.Thread] = []


class WebhookEnvelope(BaseModel):
    eventId: str
    eventType: str
    occurredAt: Optional[str] = None
    data: dict


# ---------------------------------------------------------------- startup --
@app.on_event("startup")
def on_startup():
    db.init_db()
    log.info("Integration Service starting | tenant=%s | mode=%s | SIS=%s | LMS=%s",
              settings.TENANT_ID, settings.INTEGRATION_MODE, settings.SIS_URL, settings.LMS_URL)

    if settings.AUTO_RESET_ON_START:
        _admin_reset()

    if settings.AUTO_BOOTSTRAP_ON_START:
        threading.Thread(target=_bootstrap_once, daemon=True).start()

    if settings.INTEGRATION_MODE == "webhook":
        threading.Thread(target=_register_webhooks, daemon=True).start()

    t1 = threading.Thread(target=poller.poll_loop, args=(_stop_event, settings.POLL_INTERVAL_SECONDS), daemon=True)
    t2 = threading.Thread(target=poller.retry_loop, args=(_stop_event, settings.RETRY_WORKER_INTERVAL_SECONDS), daemon=True)
    t1.start(); t2.start()
    _threads.extend([t1, t2])


@app.on_event("shutdown")
def on_shutdown():
    _stop_event.set()


def _bootstrap_once():
    try:
        result = reconcile.reconcile_all(include_memberships=True)
        log.info("startup reconciliation done: %s", result)
    except Exception:
        log.exception("startup reconciliation failed (will retry via /internal/reconcile or next poll)")


def _register_webhooks():
    base = settings.PUBLIC_CALLBACK_BASE_URL.rstrip("/")
    try:
        sis_client.register_webhook(f"{base}/webhooks/sis", [
            "student.created", "student.updated", "section.created", "section.updated",
            "enrollment.created", "enrollment.dropped",
        ])
        lms_client.register_webhook(f"{base}/webhooks/lms", ["grade.published", "learner.at_risk"])
        log.info("webhooks registered with SIS and LMS -> %s", base)
    except Exception:
        log.exception("webhook registration failed (falling back to polling only)")


def _admin_reset():
    import httpx
    try:
        httpx.post(f"{settings.SIS_URL}/admin/tenants/{settings.TENANT_ID}/reset",
                    headers={"x-admin-key": settings.ADMIN_KEY}, timeout=10)
        httpx.post(f"{settings.LMS_URL}/admin/tenants/{settings.TENANT_ID}/reset",
                    headers={"x-admin-key": settings.ADMIN_KEY}, timeout=10)
        log.info("AUTO_RESET_ON_START: SIS/LMS tenant data reset")
    except Exception:
        log.exception("AUTO_RESET_ON_START failed")


# ------------------------------------------------------------------ health --
@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "integration-service",
        "tenant": settings.TENANT_ID,
        "mode": settings.INTEGRATION_MODE,
        "stats": db.stats(),
    }


# --------------------------------------------------------- webhook receivers
@app.post("/webhooks/sis", status_code=202)
def webhook_sis(envelope: WebhookEnvelope, bg: BackgroundTasks):
    # ACK fast; process async. Safe on duplicate deliveries (idempotency, NFR-01).
    bg.add_task(engine.process_event, envelope.eventId, envelope.eventType, "SIS", envelope.data)
    return {"accepted": True}


@app.post("/webhooks/lms", status_code=202)
def webhook_lms(envelope: WebhookEnvelope, bg: BackgroundTasks):
    bg.add_task(engine.process_event, envelope.eventId, envelope.eventType, "LMS", envelope.data)
    return {"accepted": True}


# ------------------------------------------------------------- internal API
@app.post("/internal/poll")
def internal_poll():
    return poller.poll_once()


@app.post("/internal/reconcile")
def internal_reconcile(include_memberships: bool = True):
    return reconcile.reconcile_all(include_memberships=include_memberships)


@app.get("/internal/audit")
def internal_audit(limit: int = Query(200, le=2000), event_id: Optional[str] = None, int_code: Optional[str] = None):
    return db.list_audit(limit=limit, event_id=event_id, int_code=int_code)


@app.get("/internal/mappings")
def internal_mappings(entity_type: Optional[str] = None):
    return db.all_mappings(entity_type=entity_type)


@app.get("/internal/stats")
def internal_stats():
    return db.stats()


@app.post("/internal/events/{source}/{event_id}/retry")
def internal_retry_one(source: str, event_id: str):
    row = db.get_event(event_id, source)
    if not row:
        raise HTTPException(404, "EVENT_NOT_FOUND")
    import json
    payload = json.loads(row["payload"]) if row["payload"] else {}
    status = engine.process_event(event_id, row["event_type"], source, payload)
    return {"eventId": event_id, "source": source, "result": status}
