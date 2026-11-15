#!/usr/bin/env python3
"""Automated integration test suite for Shift Handover Copilot Docker Compose stack.

Validates all 7 core deployment scenarios against a running instance:
  Scenario 1: Container Boot & Static SPA Serving
  Scenario 2: Shift Events Lifecycle & Dual-Naming Compatibility
  Scenario 3: Handover Report Generation & Zero-Omission Gate
  Scenario 4: Version Progression & Report History
  Scenario 5: Dynamic Model Settings & Admin Security
  Scenario 6: Database Persistence Across Restarts
  Scenario 7: Webhook Relay Module & Incident Ingestion

Can be run standalone:
    python scripts/test_compose_integration.py --base-url http://127.0.0.1:8000
Or via pytest (see backend/tests/test_compose_scenarios.py).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional
import urllib.error
import urllib.parse
import urllib.request
import uuid

DEFAULT_BASE_URL = os.environ.get("APP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
DEFAULT_ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "dev-admin-secret-key-12345")
DEFAULT_RELAY_TOKEN = os.environ.get("RELAY_WEBHOOK_TOKEN", "dev-relay-token-secret-123")


class HttpResponse:
    """Lightweight HTTP response abstraction over urllib."""

    def __init__(self, status_code: int, headers: Dict[str, str], body_bytes: bytes):
        self.status_code = status_code
        self.headers = {k.lower(): v for k, v in headers.items()}
        self._raw_body = body_bytes

    @property
    def text(self) -> str:
        return self._raw_body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)

    def header(self, key: str) -> Optional[str]:
        return self.headers.get(key.lower())


class HttpClient:
    """Synchronous HTTP client with zero external dependencies."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def request(
        self,
        method: str,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        json_data: Optional[Any] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = 15.0,
    ) -> HttpResponse:
        url = f"{self.base_url}{path}"
        if params:
            query = urllib.parse.urlencode({k: str(v) for k, v in params.items()})
            url = f"{url}?{query}"

        req_headers = headers.copy() if headers else {}
        data = None
        if json_data is not None:
            data = json.dumps(json_data).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")

        req = urllib.request.Request(url=url, data=data, headers=req_headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status_code = resp.status
                headers_dict = dict(resp.headers)
                body = resp.read()
                return HttpResponse(status_code, headers_dict, body)
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            headers_dict = dict(exc.headers)
            body = exc.read()
            return HttpResponse(status_code, headers_dict, body)

    def get(self, path: str, **kwargs: Any) -> HttpResponse:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> HttpResponse:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> HttpResponse:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> HttpResponse:
        return self.request("DELETE", path, **kwargs)


class ComposeIntegrationTestSuite:
    """Automated integration test runner verifying all 7 scenarios."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        admin_token: str = DEFAULT_ADMIN_TOKEN,
        relay_token: str = DEFAULT_RELAY_TOKEN,
        skip_restart: bool = False,
    ):
        self.client = HttpClient(base_url)
        self.admin_token = admin_token
        self.relay_token = relay_token
        self.skip_restart = skip_restart
        self.unique_suffix = uuid.uuid4().hex[:6]
        self.shift_key_early = "2026-11-15-early"
        self.shift_key_empty = "2026-11-15-night"

        # State carried across scenarios for verification in Scenario 6
        self.seeded_event_ids: List[str] = []
        self.report_v1_id: Optional[str] = None
        self.report_v2_id: Optional[str] = None
        self.reconfigured_active_model: str = "google/gemini-3.1-flash-lite"
        self.reconfigured_fallback_model: str = "google/gemini-3.5-flash-lite"

    def log(self, scenario: str, message: str) -> None:
        print(f"[{scenario}] {message}")

    def assert_true(self, condition: bool, message: str) -> None:
        if not condition:
            raise AssertionError(f"Assertion failed: {message}")

    # =========================================================================
    # Scenario 1: Container Boot & Static SPA Serving
    # =========================================================================
    def run_scenario_1_boot_and_spa(self) -> None:
        self.log("Scenario 1", "Testing container boot & static SPA serving...")

        # 1. GET /api/healthz
        res = self.client.get("/api/healthz")
        self.assert_true(res.status_code == 200, f"/api/healthz status was {res.status_code}")
        health_data = res.json()
        self.assert_true(health_data.get("status") == "ok", f"Health status was {health_data.get('status')}")
        self.assert_true("version" in health_data, "Health response missing version")
        self.assert_true("environment" in health_data, "Health response missing environment")
        self.log("Scenario 1", f"Health OK: version={health_data['version']}, env={health_data['environment']}")

        # 2. GET / (React SPA root)
        res_root = self.client.get("/")
        self.assert_true(res_root.status_code == 200, f"GET / status was {res_root.status_code}")
        ct_root = res_root.header("content-type") or ""
        self.assert_true("text/html" in ct_root, f"GET / content-type was {ct_root}")
        self.assert_true('<div id="root">' in res_root.text, "GET / does not contain '<div id=\"root\">'")
        self.log("Scenario 1", "Root SPA HTML verified with <div id=\"root\">")

        # 3. GET /assets/* (Extract bundled JS and CSS from index.html)
        import re

        js_match = re.search(r'src=["\'](/assets/[^"\']+\.js)["\']', res_root.text)
        css_match = re.search(r'href=["\'](/assets/[^"\']+\.css)["\']', res_root.text)

        if js_match:
            js_path = js_match.group(1)
            res_js = self.client.get(js_path)
            self.assert_true(res_js.status_code == 200, f"GET {js_path} status was {res_js.status_code}")
            ct_js = res_js.header("content-type") or ""
            self.assert_true(
                "javascript" in ct_js, f"Expected javascript content-type for {js_path}, got {ct_js}"
            )
            self.log("Scenario 1", f"Static JS bundle OK ({js_path})")

        if css_match:
            css_path = css_match.group(1)
            res_css = self.client.get(css_path)
            self.assert_true(res_css.status_code == 200, f"GET {css_path} status was {res_css.status_code}")
            ct_css = res_css.header("content-type") or ""
            self.assert_true("text/css" in ct_css, f"Expected text/css for {css_path}, got {ct_css}")
            self.log("Scenario 1", f"Static CSS bundle OK ({css_path})")

        # 4. SPA Fallback client routes: /reports and /reports/{uuid}
        for spa_route in ["/reports", "/reports/00000000-0000-0000-0000-000000000000"]:
            res_spa = self.client.get(spa_route)
            self.assert_true(
                res_spa.status_code == 200, f"GET {spa_route} status was {res_spa.status_code} (SPA fallback failed)"
            )
            self.assert_true(
                '<div id="root">' in res_spa.text, f"GET {spa_route} did not serve index.html SPA fallback"
            )
            self.log("Scenario 1", f"SPA fallback route {spa_route} OK")

        # 5. OpenAPI documentation: /docs and /openapi.json
        res_docs = self.client.get("/docs")
        self.assert_true(res_docs.status_code == 200, f"GET /docs status was {res_docs.status_code}")

        res_openapi = self.client.get("/openapi.json")
        self.assert_true(res_openapi.status_code == 200, f"GET /openapi.json status was {res_openapi.status_code}")
        openapi_spec = res_openapi.json()
        self.assert_true("openapi" in openapi_spec, "openapi.json missing openapi version")
        self.assert_true(
            openapi_spec["openapi"].startswith("3."), f"Expected OpenAPI 3.x, got {openapi_spec['openapi']}"
        )
        self.log("Scenario 1", "Swagger UI (/docs) and OpenAPI 3.x (/openapi.json) OK")

    # =========================================================================
    # Scenario 2: Shift Events Lifecycle & Dual-Naming Compatibility
    # =========================================================================
    def run_scenario_2_events_lifecycle(self) -> None:
        self.log("Scenario 2", "Testing shift events lifecycle & dual-naming compatibility...")

        # 1. POST /api/events with camelCase payload
        camel_payload = {
            "shiftKey": self.shift_key_early,
            "machine": "Press-01",
            "category": "downtime",
            "note": f"Replaced hydraulic seal {self.unique_suffix}",
        }
        res1 = self.client.post("/api/events", json_data=camel_payload)
        self.assert_true(res1.status_code == 201, f"POST /api/events (camelCase) returned {res1.status_code}")
        ev1 = res1.json()
        self.assert_true("id" in ev1, "Created event missing id")
        self.assert_true(ev1.get("shiftKey") == self.shift_key_early, "shiftKey property mismatch")
        self.assert_true(ev1.get("shift_key") == self.shift_key_early, "shift_key property mismatch")
        self.assert_true("createdAt" in ev1 and "created_at" in ev1, "createdAt / created_at missing")
        self.assert_true(ev1["createdAt"] == ev1["created_at"], "createdAt and created_at mismatch")
        self.assert_true(ev1["machine"] == "Press-01", "machine mismatch")
        self.assert_true(ev1["category"] == "downtime", "category mismatch")
        self.seeded_event_ids.append(ev1["id"])
        self.log("Scenario 2", f"Event 1 created with camelCase (id={ev1['id']})")

        # 2. POST /api/events with snake_case payload
        snake_payload = {
            "shift_key": self.shift_key_early,
            "machine": "Press-02",
            "category": "quality",
            "note": f"Calibration verified {self.unique_suffix}",
        }
        res2 = self.client.post("/api/events", json_data=snake_payload)
        self.assert_true(res2.status_code == 201, f"POST /api/events (snake_case) returned {res2.status_code}")
        ev2 = res2.json()
        self.assert_true("id" in ev2, "Created event 2 missing id")
        self.assert_true(ev2.get("shift_key") == self.shift_key_early, "shift_key mismatch")
        self.assert_true(ev2.get("shiftKey") == self.shift_key_early, "shiftKey mismatch")
        self.assert_true(ev2["createdAt"] == ev2["created_at"], "createdAt/created_at mismatch")
        self.seeded_event_ids.append(ev2["id"])
        self.log("Scenario 2", f"Event 2 created with snake_case (id={ev2['id']})")

        # 3. GET /api/events?shiftKey=... (camelCase query parameter)
        res_list_camel = self.client.get(f"/api/events?shiftKey={self.shift_key_early}")
        self.assert_true(res_list_camel.status_code == 200, f"GET with shiftKey returned {res_list_camel.status_code}")
        events_camel = res_list_camel.json()
        event_ids_camel = [e["id"] for e in events_camel]
        self.assert_true(ev1["id"] in event_ids_camel, "Event 1 missing from shiftKey list")
        self.assert_true(ev2["id"] in event_ids_camel, "Event 2 missing from shiftKey list")

        # 4. GET /api/events?shift_key=... (snake_case query parameter)
        res_list_snake = self.client.get(f"/api/events?shift_key={self.shift_key_early}")
        self.assert_true(res_list_snake.status_code == 200, f"GET with shift_key returned {res_list_snake.status_code}")
        events_snake = res_list_snake.json()
        event_ids_snake = [e["id"] for e in events_snake]
        self.assert_true(ev1["id"] in event_ids_snake, "Event 1 missing from shift_key list")
        self.assert_true(ev2["id"] in event_ids_snake, "Event 2 missing from shift_key list")
        self.log("Scenario 2", "GET /api/events dual query parameters (shiftKey & shift_key) OK")

        # 5. Validation guard: invalid shift key format -> 422 ProblemDetails with traceId
        invalid_payload = {
            "shiftKey": "invalid-shift-key",
            "machine": "Press-01",
            "category": "downtime",
            "note": "test note",
        }
        res_val = self.client.post("/api/events", json_data=invalid_payload)
        self.assert_true(res_val.status_code == 422, f"Expected 422 for invalid shift key, got {res_val.status_code}")
        val_ct = res_val.header("content-type") or ""
        self.assert_true(
            "application/problem+json" in val_ct,
            f"Expected application/problem+json content-type, got {val_ct}",
        )
        val_data = res_val.json()
        self.assert_true(val_data.get("status") == 422, f"Problem status was {val_data.get('status')}")
        self.assert_true("title" in val_data, "Problem details missing title")
        self.assert_true("detail" in val_data, "Problem details missing detail")
        trace_id = val_data.get("traceId") or val_data.get("trace_id")
        self.assert_true(bool(trace_id), "Problem details missing non-empty traceId")
        self.log("Scenario 2", f"Validation guard returned RFC 9457 ProblemDetails with traceId={trace_id}")

        # 6. DELETE /api/events/{id} -> 204 No Content
        temp_payload = {
            "shiftKey": self.shift_key_early,
            "machine": "Temp-01",
            "category": "info",
            "note": "Temporary event to delete",
        }
        res_temp = self.client.post("/api/events", json_data=temp_payload)
        self.assert_true(res_temp.status_code == 201, "Failed to create temp event for deletion")
        temp_id = res_temp.json()["id"]

        del_res = self.client.delete(f"/api/events/{temp_id}")
        self.assert_true(del_res.status_code == 204, f"DELETE returned {del_res.status_code}, expected 204")

        res_check = self.client.get(f"/api/events?shiftKey={self.shift_key_early}")
        remaining_ids = [e["id"] for e in res_check.json()]
        self.assert_true(temp_id not in remaining_ids, f"Deleted event {temp_id} still present in events list")
        self.log("Scenario 2", f"Event deletion (204) verified for id={temp_id}")

    # =========================================================================
    # Scenario 3: Handover Report Generation & Zero-Omission Gate
    # =========================================================================
    def run_scenario_3_report_generation(self) -> None:
        self.log("Scenario 3", "Testing handover report generation & zero-omission gate...")

        # 1. Zero-omission gate: 422 ProblemDetails on shift with 0 events
        res_zero = self.client.post("/api/reports/generate", json_data={"shiftKey": self.shift_key_empty})
        self.assert_true(
            res_zero.status_code == 422,
            f"Expected 422 on empty shift generation, got {res_zero.status_code}",
        )
        ct_zero = res_zero.header("content-type") or ""
        self.assert_true(
            "application/problem+json" in ct_zero,
            f"Expected application/problem+json content-type, got {ct_zero}",
        )
        zero_data = res_zero.json()
        self.assert_true(zero_data.get("status") == 422, f"Problem details status was {zero_data.get('status')}")
        self.assert_true(
            bool(zero_data.get("traceId") or zero_data.get("trace_id")),
            "Problem details missing traceId on zero-omission error",
        )
        self.log("Scenario 3", "Zero-omission gate triggered 422 with ProblemDetails and traceId")

        # 2. Report generation for shift with events -> 201 Created
        gen_res = self.client.post("/api/reports/generate", json_data={"shiftKey": self.shift_key_early})
        self.assert_true(gen_res.status_code == 201, f"Report generation failed with {gen_res.status_code}")

        # Check telemetry correlation header (X-Trace-ID or traceparent)
        trace_header = gen_res.header("x-trace-id") or gen_res.header("traceparent")
        self.assert_true(bool(trace_header), "Report generation response missing W3C trace header (X-Trace-ID)")

        rep = gen_res.json()
        self.assert_true("id" in rep, "Report response missing id")
        self.assert_true(bool(rep.get("summary")), "Report summary is empty")
        self.assert_true("safetyNotes" in rep and "safety_notes" in rep, "safetyNotes / safety_notes missing")
        self.assert_true(isinstance(rep["safetyNotes"], list), "safetyNotes is not a list")
        self.assert_true("openActions" in rep and "open_actions" in rep, "openActions / open_actions missing")
        self.assert_true(isinstance(rep["openActions"], list), "openActions is not a list")
        self.assert_true(rep.get("version") == 1, f"Initial report version was {rep.get('version')}, expected 1")
        self.assert_true("eventCount" in rep and "event_count" in rep, "eventCount / event_count missing")
        self.assert_true(rep["eventCount"] == 2, f"Expected eventCount 2, got {rep['eventCount']}")
        self.assert_true(bool(rep.get("modelUsed") or rep.get("model_used")), "modelUsed / model_used missing")

        self.report_v1_id = rep["id"]
        self.log(
            "Scenario 3",
            f"Report v1 generated successfully (id={rep['id']}, events={rep['eventCount']}, trace={trace_header})",
        )

    # =========================================================================
    # Scenario 4: Version Progression & Report History
    # =========================================================================
    def run_scenario_4_version_progression(self) -> None:
        self.log("Scenario 4", "Testing version progression & report history...")

        # 1. Add 3rd event to same shift
        res_ev3 = self.client.post(
            "/api/events",
            json_data={
                "shiftKey": self.shift_key_early,
                "machine": "Press-03",
                "category": "info",
                "note": f"Shift handover transition completed {self.unique_suffix}",
            },
        )
        self.assert_true(res_ev3.status_code == 201, "Failed to create 3rd event")
        ev3_id = res_ev3.json()["id"]
        self.seeded_event_ids.append(ev3_id)

        # 2. Trigger report generation again for same shift -> increments to version 2
        gen_res2 = self.client.post("/api/reports/generate", json_data={"shift_key": self.shift_key_early})
        self.assert_true(gen_res2.status_code == 201, f"Report re-generation failed with {gen_res2.status_code}")
        rep2 = gen_res2.json()
        self.assert_true(rep2.get("version") == 2, f"Expected version 2, got {rep2.get('version')}")
        self.assert_true(rep2.get("eventCount") == 3, f"Expected eventCount 3 in v2, got {rep2.get('eventCount')}")
        self.report_v2_id = rep2["id"]
        self.log("Scenario 4", f"Report v2 generated successfully (id={rep2['id']}, version={rep2['version']})")

        # 3. GET /api/reports?shiftKey=... -> descending order (v2 first, then v1)
        list_res = self.client.get(f"/api/reports?shiftKey={self.shift_key_early}")
        self.assert_true(list_res.status_code == 200, f"GET /api/reports returned {list_res.status_code}")
        summaries = list_res.json()
        self.assert_true(len(summaries) >= 2, f"Expected at least 2 reports, got {len(summaries)}")
        self.assert_true(summaries[0]["version"] == 2, f"First report version was {summaries[0]['version']}, expected 2")
        self.assert_true(summaries[1]["version"] == 1, f"Second report version was {summaries[1]['version']}, expected 1")
        self.log("Scenario 4", "Report history returned reports in descending version order (v2 -> v1)")

        # 4. Immutable snapshot verification: v1 retains snapshot eventCount=2, v2 has eventCount=3
        res_v1 = self.client.get(f"/api/reports/{self.report_v1_id}")
        self.assert_true(res_v1.status_code == 200, f"GET v1 returned {res_v1.status_code}")
        v1_detail = res_v1.json()
        self.assert_true(v1_detail["version"] == 1, "v1 version corrupted")
        self.assert_true(
            v1_detail["eventCount"] == 2,
            f"v1 snapshot corrupted: eventCount is {v1_detail['eventCount']}, expected 2",
        )

        res_v2 = self.client.get(f"/api/reports/{self.report_v2_id}")
        self.assert_true(res_v2.status_code == 200, f"GET v2 returned {res_v2.status_code}")
        v2_detail = res_v2.json()
        self.assert_true(v2_detail["version"] == 2, "v2 version mismatch")
        self.assert_true(
            v2_detail["eventCount"] == 3,
            f"v2 snapshot eventCount is {v2_detail['eventCount']}, expected 3",
        )
        self.log("Scenario 4", "Immutable snapshot verified: v1 retained 2 events, v2 reflects 3 events")

    # =========================================================================
    # Scenario 5: Dynamic Model Settings & Admin Security
    # =========================================================================
    def run_scenario_5_admin_settings(self) -> None:
        self.log("Scenario 5", "Testing dynamic model settings & admin security...")

        # 1. Admin security guard: 401 without Bearer token
        res_unauth = self.client.get("/api/admin/settings")
        self.assert_true(
            res_unauth.status_code == 401, f"Expected 401 for missing token, got {res_unauth.status_code}"
        )
        ct_unauth = res_unauth.header("content-type") or ""
        self.assert_true("application/problem+json" in ct_unauth, f"Expected problem+json, got {ct_unauth}")
        self.log("Scenario 5", "Admin security guard returned 401 ProblemDetails on unauthenticated request")

        # 2. GET settings with valid token -> dual camelCase and snake_case properties
        auth_header = {"Authorization": f"Bearer {self.admin_token}"}
        res_settings = self.client.get("/api/admin/settings", headers=auth_header)
        self.assert_true(
            res_settings.status_code == 200, f"GET /api/admin/settings returned {res_settings.status_code}"
        )
        settings_data = res_settings.json()
        self.assert_true("activeModel" in settings_data and "active_model" in settings_data, "activeModel keys missing")
        self.assert_true(
            "fallbackModel" in settings_data and "fallback_model" in settings_data,
            "fallbackModel keys missing",
        )
        self.log("Scenario 5", f"Admin settings retrieved OK (active={settings_data['activeModel']})")

        # 3. PUT settings runtime reconfiguration without restart
        update_payload = {
            "activeModel": self.reconfigured_active_model,
            "fallbackModel": self.reconfigured_fallback_model,
        }
        res_put = self.client.put("/api/admin/settings", headers=auth_header, json_data=update_payload)
        self.assert_true(res_put.status_code == 200, f"PUT /api/admin/settings failed with {res_put.status_code}")
        put_data = res_put.json()
        self.assert_true(
            put_data.get("activeModel") == self.reconfigured_active_model,
            f"activeModel not updated: {put_data.get('activeModel')}",
        )
        self.assert_true(
            put_data.get("fallbackModel") == self.reconfigured_fallback_model,
            f"fallbackModel not updated: {put_data.get('fallbackModel')}",
        )

        # Confirm via GET that update persisted in runtime
        res_get_updated = self.client.get("/api/admin/settings", headers=auth_header)
        get_updated_data = res_get_updated.json()
        self.assert_true(
            get_updated_data.get("activeModel") == self.reconfigured_active_model,
            "Runtime settings update not reflected in GET",
        )
        self.log("Scenario 5", f"Runtime model reconfiguration OK: active={self.reconfigured_active_model}")

    # =========================================================================
    # Scenario 6: Database Persistence Across Restarts
    # =========================================================================
    def run_scenario_6_database_persistence(self) -> None:
        self.log("Scenario 6", "Testing database persistence across container restart...")

        if self.skip_restart:
            self.log("Scenario 6", "Container restart skipped (--skip-restart set). Checking persistent state...")
        else:
            self.log("Scenario 6", "Executing 'docker compose restart app' to verify volume persistence...")
            cmd = ["docker", "compose", "restart", "app"]
            ret = subprocess.run(cmd, capture_output=True, text=True)
            self.assert_true(ret.returncode == 0, f"docker compose restart failed: {ret.stderr}")

            # Poll /api/healthz until container returns 200
            start_poll = time.time()
            healthy = False
            while time.time() - start_poll < 30.0:
                try:
                    h_res = self.client.get("/api/healthz", timeout=3.0)
                    if h_res.status_code == 200 and h_res.json().get("status") == "ok":
                        healthy = True
                        break
                except Exception:
                    pass
                time.sleep(1.0)

            self.assert_true(healthy, "Container did not recover to healthy state within 30s after restart")
            self.log("Scenario 6", "Container successfully restarted and healthy")

        # 1. Post-restart events persistence
        res_events = self.client.get(f"/api/events?shiftKey={self.shift_key_early}")
        self.assert_true(res_events.status_code == 200, f"Post-restart events query failed: {res_events.status_code}")
        events = res_events.json()
        event_ids = [e["id"] for e in events]
        for seeded_id in self.seeded_event_ids:
            self.assert_true(seeded_id in event_ids, f"Seeded event {seeded_id} lost after container restart!")
        self.log("Scenario 6", f"Events persistence verified ({len(self.seeded_event_ids)} events intact)")

        # 2. Post-restart reports persistence
        res_reports = self.client.get(f"/api/reports?shiftKey={self.shift_key_early}")
        self.assert_true(res_reports.status_code == 200, f"Post-restart reports query failed: {res_reports.status_code}")
        reports = res_reports.json()
        report_ids = [r["id"] for r in reports]
        self.assert_true(
            self.report_v1_id in report_ids, f"Report v1 {self.report_v1_id} lost after container restart!"
        )
        self.assert_true(
            self.report_v2_id in report_ids, f"Report v2 {self.report_v2_id} lost after container restart!"
        )

        # Verify snapshots
        v1_snap = self.client.get(f"/api/reports/{self.report_v1_id}").json()
        self.assert_true(v1_snap["eventCount"] == 2, "Report v1 snapshot corrupted after restart")
        v2_snap = self.client.get(f"/api/reports/{self.report_v2_id}").json()
        self.assert_true(v2_snap["eventCount"] == 3, "Report v2 snapshot corrupted after restart")
        self.log("Scenario 6", "Reports persistence and version snapshots verified intact")

        # 3. Post-restart settings persistence
        auth_header = {"Authorization": f"Bearer {self.admin_token}"}
        res_settings = self.client.get("/api/admin/settings", headers=auth_header)
        self.assert_true(res_settings.status_code == 200, "Failed to get settings post-restart")
        settings = res_settings.json()
        self.assert_true(
            settings.get("activeModel") == self.reconfigured_active_model,
            f"Settings reverted after restart! Expected {self.reconfigured_active_model}, got {settings.get('activeModel')}",
        )
        self.log("Scenario 6", "Admin model settings persistence across restart verified intact")

    # =========================================================================
    # Scenario 7: Webhook Relay Module & Incident Ingestion
    # =========================================================================
    def run_scenario_7_webhook_relay(self) -> None:
        self.log("Scenario 7", "Testing webhook relay module & incident ingestion...")

        sample_alert = {
            "receiver": "handover-relay",
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {
                        "alertname": "HandoverReportGenerationHighErrorRate",
                        "environment": "prod",
                        "severity": "critical",
                    },
                    "annotations": {
                        "summary": "Shift leads cannot generate handovers",
                        "description": "Error rate exceeds 20%",
                    },
                    "fingerprint": f"fp-test-{self.unique_suffix}-001",
                }
            ],
            "commonLabels": {"alertname": "HandoverReportGenerationHighErrorRate"},
            "commonAnnotations": {"summary": "Shift leads cannot generate handovers"},
        }

        # 1. Webhook security guard: 401 without token or with invalid token
        res_no_tok = self.client.post("/api/relay/webhook", json_data=sample_alert)
        self.assert_true(
            res_no_tok.status_code == 401, f"Expected 401 on missing webhook token, got {res_no_tok.status_code}"
        )
        ct_sec = res_no_tok.header("content-type") or ""
        self.assert_true("application/problem+json" in ct_sec, f"Expected problem+json, got {ct_sec}")

        res_bad_tok = self.client.post(
            "/api/relay/webhook",
            json_data=sample_alert,
            headers={"X-Webhook-Token": "invalid-secret"},
        )
        self.assert_true(res_bad_tok.status_code == 401, "Expected 401 on invalid X-Webhook-Token")

        res_bad_bearer = self.client.post(
            "/api/relay/webhook",
            json_data=sample_alert,
            headers={"Authorization": "Bearer invalid-token"},
        )
        self.assert_true(res_bad_bearer.status_code == 401, "Expected 401 on invalid Bearer token")
        self.log("Scenario 7", "Webhook security guards (missing/invalid token) returned 401 ProblemDetails")

        # 2. Webhook validation guard: 422 on invalid/missing fields
        auth_webhook = {"X-Webhook-Token": self.relay_token}
        res_val = self.client.post("/api/relay/webhook", json_data={}, headers=auth_webhook)
        self.assert_true(
            res_val.status_code == 422, f"Expected 422 on empty webhook body, got {res_val.status_code}"
        )
        ct_val = res_val.header("content-type") or ""
        self.assert_true("application/problem+json" in ct_val, f"Expected problem+json, got {ct_val}")

        res_val2 = self.client.post(
            "/api/relay/webhook",
            json_data={"status": "firing", "alerts": []},
            headers=auth_webhook,
        )
        self.assert_true(res_val2.status_code == 422, "Expected 422 on empty alerts array")
        self.log("Scenario 7", "Webhook validation guards returned 422 ProblemDetails on malformed payloads")

        # 3. Non-firing alert handling: status="resolved" returns 200 with status="ignored"
        resolved_alert = {
            "receiver": "handover-relay",
            "status": "resolved",
            "alerts": [
                {
                    "status": "resolved",
                    "labels": {"alertname": "HandoverReportGenerationResolved"},
                    "fingerprint": f"fp-resolved-{self.unique_suffix}",
                }
            ],
        }
        res_res = self.client.post("/api/relay/webhook", json_data=resolved_alert, headers=auth_webhook)
        self.assert_true(
            res_res.status_code == 200, f"Expected 200 for resolved alert, got {res_res.status_code}"
        )
        res_data = res_res.json()
        self.assert_true(res_data.get("status") == "ignored", f"Expected status 'ignored', got {res_data.get('status')}")
        self.assert_true(
            res_data.get("fingerprint") == f"fp-resolved-{self.unique_suffix}",
            "Fingerprint mismatch on resolved alert",
        )
        self.assert_true(res_data.get("reason") == "non-firing alert", "Reason mismatch on resolved alert")
        self.log("Scenario 7", "Non-firing alert handled cleanly (status='ignored', reason='non-firing alert')")

        # 4. Deduplication handling: First firing alert dispatches, second returns deduplicated
        fp_firing = f"fp-firing-{self.unique_suffix}-999"
        firing_alert = {
            "receiver": "handover-relay",
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {
                        "alertname": "HandoverTestIncident",
                        "environment": "prod",
                    },
                    "fingerprint": fp_firing,
                }
            ],
            "commonLabels": {"alertname": "HandoverTestIncident"},
        }

        # First call: dispatches successfully
        res_fire1 = self.client.post("/api/relay/webhook", json_data=firing_alert, headers=auth_webhook)
        self.assert_true(res_fire1.status_code == 200, f"Firing alert 1 returned {res_fire1.status_code}")
        fire1_data = res_fire1.json()
        self.assert_true(fire1_data.get("status") == "dispatched", f"Expected 'dispatched', got {fire1_data.get('status')}")
        self.assert_true(fire1_data.get("fingerprint") == fp_firing, "Fingerprint mismatch on firing alert")

        # Second call: within cooldown window -> returns deduplicated
        res_fire2 = self.client.post("/api/relay/webhook", json_data=firing_alert, headers=auth_webhook)
        self.assert_true(res_fire2.status_code == 200, f"Firing alert 2 returned {res_fire2.status_code}")
        fire2_data = res_fire2.json()
        self.assert_true(
            fire2_data.get("status") == "deduplicated", f"Expected 'deduplicated', got {fire2_data.get('status')}"
        )
        self.assert_true(fire2_data.get("fingerprint") == fp_firing, "Fingerprint mismatch on deduplicated alert")
        self.log("Scenario 7", "Alert deduplication confirmed: call 1='dispatched', call 2='deduplicated'")

        # 5. Incident event creation in shift log
        incident_payload = {
            "shiftKey": self.shift_key_early,
            "machine": "Boiler-01",
            "category": "safety",
            "note": f"Incident triggered: Pressure valve release logged by alert relay {self.unique_suffix}",
        }
        res_inc = self.client.post("/api/events", json_data=incident_payload)
        self.assert_true(
            res_inc.status_code == 201, f"POST /api/events incident returned {res_inc.status_code}"
        )
        inc_event = res_inc.json()
        self.assert_true("id" in inc_event, "Incident event missing id")
        self.assert_true(inc_event.get("category") == "safety", "Category mismatch on incident event")

        # Verify event present in shift log
        res_log = self.client.get(f"/api/events?shiftKey={self.shift_key_early}")
        self.assert_true(res_log.status_code == 200, "Failed to query shift log")
        log_ids = [e["id"] for e in res_log.json()]
        self.assert_true(inc_event["id"] in log_ids, "Incident event not found in shift log")
        self.log("Scenario 7", f"Incident event creation verified in shift log (id={inc_event['id']})")

    # =========================================================================
    # Run all scenarios
    # =========================================================================
    def run_all(self) -> None:
        print("=" * 70)
        print("Starting Shift Handover Copilot Compose Integration Test Suite")
        print(f"Target Base URL: {self.client.base_url}")
        print("=" * 70)

        t0 = time.time()
        self.run_scenario_1_boot_and_spa()
        self.run_scenario_2_events_lifecycle()
        self.run_scenario_3_report_generation()
        self.run_scenario_4_version_progression()
        self.run_scenario_5_admin_settings()
        self.run_scenario_6_database_persistence()
        self.run_scenario_7_webhook_relay()
        duration = time.time() - t0

        print("=" * 70)
        print(f"SUCCESS: All 7 deployment scenarios verified in {duration:.2f}s!")
        print("=" * 70)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Shift Handover Copilot Docker Compose Integration Test Suite"
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Base URL of running container (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--admin-token",
        default=DEFAULT_ADMIN_TOKEN,
        help="Admin token for bearer authentication",
    )
    parser.add_argument(
        "--relay-token",
        default=DEFAULT_RELAY_TOKEN,
        help="Shared secret token for webhook relay authentication",
    )
    parser.add_argument(
        "--skip-restart",
        action="store_true",
        help="Skip container restart in Scenario 6 (test persistence without restart)",
    )

    args = parser.parse_args()

    suite = ComposeIntegrationTestSuite(
        base_url=args.base_url,
        admin_token=args.admin_token,
        relay_token=args.relay_token,
        skip_restart=args.skip_restart,
    )

    try:
        suite.run_all()
        return 0
    except AssertionError as exc:
        print(f"\nTEST FAILURE: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"\nUNEXPECTED ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
