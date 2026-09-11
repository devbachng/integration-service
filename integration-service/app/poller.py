"""
Polling mode (default): GET /api/v1/events?since=<checkpoint> on both
systems, feed every event into the shared engine, advance the checkpoint.

Idempotency (NFR-01) does not depend on the checkpoint - even if the same
event is polled twice (e.g. after a restart before the checkpoint was
saved), engine.process_event() will see it is already DONE and skip it.
"""
from __future__ import annotations
import logging
import threading

from . import db, engine
from .clients import sis_client, lms_client

log = logging.getLogger("integration")


def poll_source(client, source_name: str) -> int:
    since = db.get_checkpoint(source_name)
    try:
        events = client.get_events(since=since)
    except Exception:
        log.exception("poll failed for source=%s", source_name)
        return 0

    max_ts = since
    count = 0
    for ev in events:
        engine.process_event(ev["eventId"], ev["eventType"], source_name, ev["data"])
        count += 1
        occurred = ev.get("occurredAt")
        if occurred and (not max_ts or occurred > max_ts):
            max_ts = occurred
    if max_ts and max_ts != since:
        db.set_checkpoint(source_name, max_ts)
    return count


def poll_once() -> dict:
    sis_n = poll_source(sis_client, "SIS")
    lms_n = poll_source(lms_client, "LMS")
    return {"sis_events": sis_n, "lms_events": lms_n}


def poll_loop(stop_event: threading.Event, interval: float):
    while not stop_event.is_set():
        try:
            poll_once()
        except Exception:
            log.exception("poll_loop iteration failed")
        stop_event.wait(interval)


def retry_loop(stop_event: threading.Event, interval: float):
    while not stop_event.is_set():
        try:
            engine.retry_pending()
        except Exception:
            log.exception("retry_loop iteration failed")
        stop_event.wait(interval)
