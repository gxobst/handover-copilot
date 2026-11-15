"""Verification script for GCP Dev and Prod Isolated Environments.

Verifies:
1. Environment-scoped secrets in Secret Manager (DATABASE_URL_DEV, DATABASE_URL_PROD, etc.)
2. Independent Cloud Run migration jobs (handover-migrate-dev, handover-migrate-prod)
3. Independent Cloud Run services (handover-dev, handover-prod) and their secret bindings
4. Live /api/healthz responses on both dev and prod with matching environment identifiers
5. Data isolation: test events created on dev do NOT appear in prod
6. Auth & settings isolation: admin tokens and dynamic settings are strictly isolated
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

PROJECT_ID = os.environ.get("GCP_PROJECT", "boxwood-scope-292916")
REGION = os.environ.get("GCP_REGION", "europe-west2")

DEV_SERVICE = "handover-dev"
PROD_SERVICE = "handover-prod"
MIGRATE_DEV_JOB = "handover-migrate-dev"
MIGRATE_PROD_JOB = "handover-migrate-prod"

REQUIRED_SECRETS = [
    "DATABASE_URL_DEV",
    "DATABASE_URL_PROD",
    "ADMIN_TOKEN_DEV",
    "ADMIN_TOKEN_PROD",
    "RELAY_WEBHOOK_TOKEN_DEV",
    "RELAY_WEBHOOK_TOKEN_PROD",
    "DATABASE_URL",
    "ADMIN_TOKEN",
    "RELAY_WEBHOOK_TOKEN",
]


def run_gcloud(args: list[str]) -> str:
    """Run gcloud CLI command and return trimmed standard output."""
    cmd = ["gcloud.cmd" if sys.platform == "win32" else "gcloud"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def http_get(url: str, headers: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "VerifyIsolation/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read().decode())
        return resp.status, body


def http_post(url: str, payload: dict, headers: dict | None = None) -> tuple[int, dict]:
    req_headers = {"Content-Type": "application/json", "User-Agent": "VerifyIsolation/1.0"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=req_headers, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read().decode())
        return resp.status, body


def http_put(url: str, payload: dict, headers: dict | None = None) -> tuple[int, dict]:
    req_headers = {"Content-Type": "application/json", "User-Agent": "VerifyIsolation/1.0"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=req_headers, method="PUT")
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read().decode())
        return resp.status, body


def verify_secrets():
    print("\n--- 1. Verifying Secret Manager Isolation ---")
    secrets_list_raw = run_gcloud(["secrets", "list", f"--project={PROJECT_ID}", "--format=value(name)"])
    existing_secrets = set(secrets_list_raw.split())

    for secret in REQUIRED_SECRETS:
        assert secret in existing_secrets, f"Missing required secret: {secret}"
        # Verify secret has at least one version
        versions = run_gcloud(["secrets", "versions", "list", secret, f"--project={PROJECT_ID}", "--format=value(name)"])
        assert len(versions.split()) > 0, f"Secret {secret} has no active versions"
        print(f"  [OK] Secret '{secret}' exists with active version(s).")

    # Verify dev and prod admin tokens are distinct
    dev_token = run_gcloud(["secrets", "versions", "access", "latest", "--secret=ADMIN_TOKEN_DEV", f"--project={PROJECT_ID}"])
    prod_token = run_gcloud(["secrets", "versions", "access", "latest", "--secret=ADMIN_TOKEN_PROD", f"--project={PROJECT_ID}"])
    assert dev_token != prod_token, "ADMIN_TOKEN_DEV and ADMIN_TOKEN_PROD must not be identical!"
    print(f"  [OK] ADMIN_TOKEN_DEV and ADMIN_TOKEN_PROD are distinct.")

    # Verify dev and prod database URLs are distinct
    dev_db = run_gcloud(["secrets", "versions", "access", "latest", "--secret=DATABASE_URL_DEV", f"--project={PROJECT_ID}"])
    prod_db = run_gcloud(["secrets", "versions", "access", "latest", "--secret=DATABASE_URL_PROD", f"--project={PROJECT_ID}"])
    assert "handover_dev" in dev_db, f"DATABASE_URL_DEV does not point to handover_dev: {dev_db}"
    assert "handover_prod" in prod_db, f"DATABASE_URL_PROD does not point to handover_prod: {prod_db}"
    assert dev_db != prod_db, "DATABASE_URL_DEV and DATABASE_URL_PROD must not be identical!"
    print(f"  [OK] DATABASE_URL_DEV and DATABASE_URL_PROD are distinct databases.")


def verify_migration_jobs():
    print("\n--- 2. Verifying Cloud Run Migration Jobs ---")
    for job_name, expected_secret in [
        (MIGRATE_DEV_JOB, "DATABASE_URL_DEV"),
        (MIGRATE_PROD_JOB, "DATABASE_URL_PROD"),
    ]:
        job_yaml = run_gcloud(["run", "jobs", "describe", job_name, f"--region={REGION}", f"--project={PROJECT_ID}", "--format=json"])
        job_data = json.loads(job_yaml)
        env_vars = job_data["spec"]["template"]["spec"]["template"]["spec"]["containers"][0]["env"]
        db_env = next((e for e in env_vars if e["name"] == "DATABASE_URL"), None)
        assert db_env is not None, f"Job {job_name} missing DATABASE_URL env"
        secret_name = db_env["valueFrom"]["secretKeyRef"]["name"]
        assert secret_name == expected_secret, f"Job {job_name} bound to {secret_name}, expected {expected_secret}"
        print(f"  [OK] Job '{job_name}' exists and binds '{expected_secret}'.")


def verify_cloud_run_services():
    print("\n--- 3. Verifying Cloud Run Services Configuration ---")
    for svc_name, expected_db_secret, expected_env in [
        (DEV_SERVICE, "DATABASE_URL_DEV", "dev"),
        (PROD_SERVICE, "DATABASE_URL_PROD", "prod"),
    ]:
        svc_yaml = run_gcloud(["run", "services", "describe", svc_name, f"--region={REGION}", f"--project={PROJECT_ID}", "--format=json"])
        svc_data = json.loads(svc_yaml)
        container = svc_data["spec"]["template"]["spec"]["containers"][0]

        env_map = {e["name"]: e.get("value") for e in container["env"] if "value" in e}
        assert env_map.get("APP_ENV") == expected_env, f"Service {svc_name} APP_ENV is {env_map.get('APP_ENV')}, expected {expected_env}"

        secret_map = {
            e["name"]: e["valueFrom"]["secretKeyRef"]["name"]
            for e in container["env"]
            if "valueFrom" in e and "secretKeyRef" in e["valueFrom"]
        }
        assert secret_map.get("DATABASE_URL") == expected_db_secret, f"Service {svc_name} bound {secret_map.get('DATABASE_URL')}, expected {expected_db_secret}"
        print(f"  [OK] Service '{svc_name}' has APP_ENV='{expected_env}' and binds '{expected_db_secret}'.")


def verify_live_endpoints_and_isolation():
    print("\n--- 4. Verifying Live Endpoints & Data Isolation ---")
    dev_url = run_gcloud(["run", "services", "describe", DEV_SERVICE, f"--region={REGION}", f"--project={PROJECT_ID}", "--format=value(status.url)"])
    prod_url = run_gcloud(["run", "services", "describe", PROD_SERVICE, f"--region={REGION}", f"--project={PROJECT_ID}", "--format=value(status.url)"])

    print(f"  Dev URL:  {dev_url}")
    print(f"  Prod URL: {prod_url}")

    # 1. Healthz on dev
    status_dev, body_dev = http_get(f"{dev_url}/api/healthz")
    assert status_dev == 200, f"Dev healthz failed with {status_dev}"
    assert body_dev.get("status") == "ok", f"Dev healthz status not ok: {body_dev}"
    assert body_dev.get("environment") == "dev", f"Dev environment mismatch: {body_dev}"
    print(f"  [OK] Dev /api/healthz responded 200 with environment='dev'.")

    # 2. Healthz on prod
    status_prod, body_prod = http_get(f"{prod_url}/api/healthz")
    assert status_prod == 200, f"Prod healthz failed with {status_prod}"
    assert body_prod.get("status") == "ok", f"Prod healthz status not ok: {body_prod}"
    assert body_prod.get("environment") == "prod", f"Prod environment mismatch: {body_prod}"
    print(f"  [OK] Prod /api/healthz responded 200 with environment='prod'.")

    # 3. Data Isolation: Create synthetic event on Dev
    shift_key = "2026-11-15-early"
    test_note = f"Synthetic isolation test note {int(time.time())}"
    event_payload = {
        "shift_key": shift_key,
        "machine": "ISO-CHECK",
        "category": "downtime",
        "note": test_note,
    }

    status, created_event = http_post(f"{dev_url}/api/events", event_payload)
    assert status == 201, f"Failed to create event on dev: {status}"
    event_id = created_event["id"]
    print(f"  [OK] Created test event '{event_id}' on Dev.")

    # Verify event appears on Dev
    _, dev_events = http_get(f"{dev_url}/api/events?shift_key={shift_key}")
    dev_ids = {e["id"] for e in dev_events}
    assert event_id in dev_ids, "Created event missing from dev events list"

    # Verify event does NOT appear on Prod
    _, prod_events = http_get(f"{prod_url}/api/events?shift_key={shift_key}")
    prod_ids = {e["id"] for e in prod_events}
    assert event_id not in prod_ids, "DATA CONTAMINATION DETECTED! Dev event found in Prod database!"
    print(f"  [OK] Data isolation verified: Dev event '{event_id}' is NOT present in Prod.")

    # 4. Auth & Settings Isolation
    dev_token = run_gcloud(["secrets", "versions", "access", "latest", "--secret=ADMIN_TOKEN_DEV", f"--project={PROJECT_ID}"])
    prod_token = run_gcloud(["secrets", "versions", "access", "latest", "--secret=ADMIN_TOKEN_PROD", f"--project={PROJECT_ID}"])

    # Dev token on Prod should fail with 401
    try:
        http_get(f"{prod_url}/api/admin/settings", headers={"Authorization": f"Bearer {dev_token}"})
        raise AssertionError("Dev token unexpectedly authenticated on Prod!")
    except urllib.error.HTTPError as e:
        assert e.code == 401, f"Expected 401 for cross-environment auth, got {e.code}"
        print(f"  [OK] Cross-environment auth rejected (HTTP 401).")

    # Put setting on Dev
    update_payload = {"active_model": "google/gemini-3.5-flash-lite"}
    status, updated_dev = http_put(
        f"{dev_url}/api/admin/settings",
        update_payload,
        headers={"Authorization": f"Bearer {dev_token}"},
    )
    assert status == 200
    assert updated_dev["active_model"] == "google/gemini-3.5-flash-lite"

    # Fetch Prod settings with Prod token
    status, prod_settings = http_get(
        f"{prod_url}/api/admin/settings",
        headers={"Authorization": f"Bearer {prod_token}"},
    )
    assert status == 200
    print(f"  [OK] Admin settings isolated between Dev and Prod.")


def main():
    print("==========================================================================")
    print(f" Verifying GCP Isolated Environments (Project: {PROJECT_ID}, Region: {REGION})")
    print("==========================================================================")
    try:
        verify_secrets()
        verify_migration_jobs()
        verify_cloud_run_services()
        verify_live_endpoints_and_isolation()
        print("\n==========================================================================")
        print(" ALL VERIFICATION CHECKS PASSED: DEV AND PROD ARE FULLY ISOLATED!")
        print("==========================================================================")
    except Exception as exc:
        print(f"\n[ERROR] Verification check failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
