"""
Thin REST clients for UniSIS and UniLearn LMS.

Responsibilities kept here (and only here):
  * JWT token fetch + cache + refresh on 401
  * X-Tenant-ID header / tenant isolation (NFR-08)
  * Classifying HTTP responses into
      - success                -> parsed JSON
      - RetryableError         -> 429 (Retry-After respected) / 500 / 502 / 503 / 504 / network error
      - PermanentError         -> other 4xx (validation / not-found / forbidden)
  * NEVER logging the token or client secret (NFR-07) - see logging_utils.redact
"""
from __future__ import annotations
import time
import httpx
from typing import Optional, Any

from .config import settings


class RetryableError(Exception):
    def __init__(self, message: str, retry_after: Optional[float] = None, status_code: Optional[int] = None):
        super().__init__(message)
        self.retry_after = retry_after
        self.status_code = status_code


class PermanentError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None, error_code: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code


class DependencyPendingError(Exception):
    """Raised when a handler needs a mapping/dependency that doesn't exist yet
    (e.g. enrollment.created arriving before the Student/Section has been
    synced). The event is kept PENDING and retried; NOT counted as an error."""
    pass


class _BaseClient:
    system_name = "SYSTEM"

    def __init__(self, base_url: str, client_id: str, client_secret: str, tenant: str):
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant = tenant
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._http = httpx.Client(timeout=settings.HTTP_TIMEOUT_SECONDS)

    # -- auth -----------------------------------------------------------
    def _fetch_token(self) -> str:
        resp = self._http.post(
            f"{self.base_url}/api/v1/auth/token",
            json={"clientId": self.client_id, "clientSecret": self.client_secret, "tenantId": self.tenant},
        )
        if resp.status_code >= 400:
            raise PermanentError(
                f"{self.system_name} auth failed ({resp.status_code})", status_code=resp.status_code
            )
        data = resp.json()
        self._token = data["accessToken"]
        # refresh a little early
        self._token_expires_at = time.time() + max(60, int(data.get("expiresIn", 3600)) - 60)
        return self._token

    def _auth_headers(self) -> dict:
        if not self._token or time.time() >= self._token_expires_at:
            self._fetch_token()
        return {"Authorization": f"Bearer {self._token}", "X-Tenant-ID": self.tenant}

    # -- core request with classification --------------------------------
    def request(self, method: str, path: str, *, params: dict | None = None,
                json_body: dict | None = None, _retried_auth: bool = False) -> Any:
        url = f"{self.base_url}{path}"
        try:
            resp = self._http.request(method, url, params=params, json=json_body, headers=self._auth_headers())
        except httpx.RequestError as exc:
            raise RetryableError(f"{self.system_name} network error: {exc}") from exc

        if resp.status_code == 401 and not _retried_auth:
            # token might have expired server-side or be otherwise invalid: refresh once
            self._token = None
            return self.request(method, path, params=params, json_body=json_body, _retried_auth=True)

        if resp.status_code == 429:
            retry_after = float(resp.headers.get("Retry-After", "5"))
            raise RetryableError(f"{self.system_name} rate limited", retry_after=retry_after, status_code=429)

        if resp.status_code in (500, 502, 503, 504):
            raise RetryableError(
                f"{self.system_name} server error {resp.status_code}", status_code=resp.status_code
            )

        if resp.status_code >= 400:
            body_code = None
            try:
                body_code = resp.json().get("detail")
            except Exception:
                pass
            raise PermanentError(
                f"{self.system_name} {method} {path} -> {resp.status_code} {body_code}",
                status_code=resp.status_code,
                error_code=str(body_code),
            )

        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def get(self, path: str, params: dict | None = None):
        return self.request("GET", path, params=params)

    def post(self, path: str, json_body: dict | None = None):
        return self.request("POST", path, json_body=json_body)

    def patch(self, path: str, json_body: dict | None = None):
        return self.request("PATCH", path, json_body=json_body)

    def put(self, path: str, json_body: dict | None = None):
        return self.request("PUT", path, json_body=json_body)

    def delete(self, path: str, params: dict | None = None):
        return self.request("DELETE", path, params=params)


class SISClient(_BaseClient):
    system_name = "UniSIS"

    def get_events(self, since: Optional[str] = None, event_type: Optional[str] = None):
        params = {}
        if since:
            params["since"] = since
        if event_type:
            params["eventType"] = event_type
        return self.get("/api/v1/events", params=params)

    def get_student(self, student_id: str):
        return self.get(f"/api/v1/students/{student_id}")

    def list_students(self):
        return self.get("/api/v1/students")

    def list_sections(self):
        return self.get("/api/v1/sections")

    def list_lecturers(self):
        return self.get("/api/v1/lecturers")

    def list_courses(self):
        return self.get("/api/v1/courses")

    def put_grade(self, student_id: str, section_id: str, final_score: float,
                   letter_grade: Optional[str], source: str = "LMS"):
        body = {"finalScore": final_score, "source": source}
        if letter_grade:
            body["letterGrade"] = letter_grade
        return self.put(f"/api/v1/grades/{student_id}/{section_id}", json_body=body)

    def post_advising_alert(self, student_id: str, section_id: str, risk_type: str, details: str):
        return self.post("/api/v1/advising/alerts", json_body={
            "studentId": student_id, "sectionId": section_id, "riskType": risk_type, "details": details,
        })

    def list_advising_alerts(self, student_id: Optional[str] = None):
        params = {"studentId": student_id} if student_id else None
        return self.get("/api/v1/advising/alerts", params=params)

    def register_webhook(self, url: str, events: list[str]):
        return self.post("/api/v1/webhooks", json_body={"url": url, "events": events})


class LMSClient(_BaseClient):
    system_name = "UniLearn"

    def get_events(self, since: Optional[str] = None, event_type: Optional[str] = None):
        params = {}
        if since:
            params["since"] = since
        if event_type:
            params["eventType"] = event_type
        return self.get("/api/v1/events", params=params)

    def find_user_by_external_ref(self, external_ref: str):
        rows = self.get("/api/v1/users", params={"externalRef": external_ref})
        return rows[0] if rows else None

    def create_user(self, username: str, display_name: str, email: str, user_type: str,
                     enabled: bool, external_ref: str):
        return self.post("/api/v1/users", json_body={
            "username": username, "displayName": display_name, "emailAddress": email,
            "userType": user_type, "enabled": enabled, "externalRef": external_ref,
        })

    def patch_user(self, user_id: int, **fields):
        return self.patch(f"/api/v1/users/{user_id}", json_body=fields)

    def find_course_by_external_code(self, external_code: str):
        rows = self.get("/api/v1/courses", params={"externalCode": external_code})
        return rows[0] if rows else None

    def create_course(self, external_code: str, title: str, term: str, state: str,
                       teacher_external_ref: Optional[str]):
        return self.post("/api/v1/courses", json_body={
            "externalCode": external_code, "title": title, "term": term, "state": state,
            "teacherExternalRef": teacher_external_ref,
        })

    def patch_course(self, course_id: int, **fields):
        return self.patch(f"/api/v1/courses/{course_id}", json_body=fields)

    def get_members(self, course_id: int):
        return self.get(f"/api/v1/courses/{course_id}/members")

    def add_member(self, course_id: int, user_id: int, role: str = "STUDENT"):
        return self.post(f"/api/v1/courses/{course_id}/members", json_body={"userId": user_id, "role": role})

    def remove_member(self, course_id: int, user_id: int, role: str = "STUDENT"):
        return self.delete(f"/api/v1/courses/{course_id}/members/{user_id}", params={"role": role})

    def register_webhook(self, url: str, events: list[str]):
        return self.post("/api/v1/webhooks", json_body={"url": url, "events": events})


sis_client = SISClient(settings.SIS_URL, settings.SIS_CLIENT_ID, settings.SIS_CLIENT_SECRET, settings.TENANT_ID)
lms_client = LMSClient(settings.LMS_URL, settings.LMS_CLIENT_ID, settings.LMS_CLIENT_SECRET, settings.TENANT_ID)
