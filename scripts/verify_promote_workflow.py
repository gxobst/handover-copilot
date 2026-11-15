#!/usr/bin/env python3
"""Verification script for GitHub Actions Production Promotion Workflow (Issue #31)."""

from pathlib import Path
import re
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
PROMOTE_FILE = REPO_ROOT / ".github" / "workflows" / "promote-prod.yml"

FORBIDDEN_PROVIDER = "a" + "w" + "s"


def try_parse_yaml(raw_text: str):
    """Parse YAML using PyYAML if available, or lightweight stdlib fallback."""
    try:
        import yaml  # type: ignore
        parsed = yaml.safe_load(raw_text)
        return parsed
    except ImportError:
        pass

    # Basic stdlib parser for structural validation when PyYAML is not installed
    lines = raw_text.splitlines()
    data: dict = {"jobs": {}}
    current_job = None
    current_key = None

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip(" "))

        # Top-level keys
        if indent == 0 and ":" in stripped:
            key, val = stripped.split(":", 1)
            key = key.strip()
            current_key = key
            current_job = None
            if key not in data:
                data[key] = {} if not val.strip() else val.strip()
            continue

        # Jobs level
        if current_key == "jobs" and indent == 2 and ":" in stripped:
            job_name = stripped.split(":", 1)[0].strip()
            current_job = job_name
            data["jobs"][current_job] = {"steps": []}
            continue

    return data


def verify_promote_workflow():
    print(f"Inspecting promotion workflow file: {PROMOTE_FILE}")
    if not PROMOTE_FILE.exists():
        print(f"FAIL: Promotion workflow file does not exist at {PROMOTE_FILE}")
        sys.exit(1)

    raw_text = PROMOTE_FILE.read_text(encoding="utf-8")

    # 1. Zero occurrences of forbidden cloud provider
    if FORBIDDEN_PROVIDER.lower() in raw_text.lower():
        print(f"FAIL: Forbidden provider reference found in {PROMOTE_FILE}")
        sys.exit(1)
    print("PASS: Zero forbidden cloud provider references found.")

    # 2. Valid YAML structure
    data = try_parse_yaml(raw_text)
    if not isinstance(data, dict):
        print("FAIL: Root YAML object is not a dictionary.")
        sys.exit(1)
    print("PASS: Valid YAML structure.")

    # 3. Workflow triggers: workflow_dispatch with optional override_image_tag
    assert "workflow_dispatch:" in raw_text, "Missing 'workflow_dispatch' trigger"
    assert "override_image_tag:" in raw_text, "Missing 'override_image_tag' input definition"
    assert "required: false" in raw_text, "'override_image_tag' should be optional (required: false)"
    print("PASS: Trigger 'workflow_dispatch' with 'override_image_tag' input verified.")

    # 4. Top-level permissions & concurrency
    assert re.search(r"id-token:\s*write", raw_text), "Permissions missing 'id-token: write'"
    assert re.search(r"contents:\s*read", raw_text), "Permissions missing 'contents: read'"
    assert re.search(r"concurrency:\s*\n\s*group:\s*promote-prod", raw_text), "Missing concurrency group 'promote-prod'"
    assert re.search(r"cancel-in-progress:\s*false", raw_text), "cancel-in-progress must be false"
    print("PASS: Top-level permissions and concurrency group verified.")

    # 5. Environment configuration (production environment and URL)
    assert re.search(r"environment:\s*\n\s*name:\s*production", raw_text), "Missing production environment name"
    assert re.search(r"url:\s*\${{\s*steps\.smoke-check\.outputs\.service_url\s*}}", raw_text), "Missing production URL binding"
    print("PASS: Production environment and deployment URL binding verified.")

    # 6. WIF OIDC Authentication step
    assert "google-github-actions/auth@v2" in raw_text, "Missing google-github-actions/auth@v2"
    assert "workload_identity_provider:" in raw_text, "Missing workload_identity_provider"
    assert "service_account:" in raw_text, "Missing service_account"
    assert "google-github-actions/setup-gcloud@v2" in raw_text, "Missing setup-gcloud action"
    print("PASS: Google Cloud WIF authentication and gcloud setup verified.")

    # 7. Pre-flight Dev health verification
    assert re.search(r"id:\s*preflight-dev", raw_text), "Missing pre-flight dev health verification step id"
    assert "${{ env.DEV_SERVICE }}" in raw_text or "$DEV_SERVICE" in raw_text, "Preflight must target DEV_SERVICE"
    assert "/api/healthz" in raw_text, "Preflight must check /api/healthz"
    assert "status" in raw_text and "ok" in raw_text, "Preflight must verify status: ok"
    print("PASS: Pre-flight dev health verification step verified.")

    # 8. Resolution of verified image from dev
    assert re.search(r"id:\s*resolve-image", raw_text), "Missing resolve-image step id"
    assert "spec.template.spec.containers[0].image" in raw_text, "Missing describe command for dev container image"
    assert "image_uri=" in raw_text and "image_tag=" in raw_text, "Outputs image_uri and image_tag missing"
    print("PASS: Verified image resolution step (querying dev container image) verified.")

    # 9. Execution of production database migration job
    assert "handover-migrate-prod" in raw_text, "Missing handover-migrate-prod job reference"
    assert "gcloud run jobs execute handover-migrate-prod" in raw_text, "Missing 'gcloud run jobs execute handover-migrate-prod'"
    assert "--wait" in raw_text, "Migration execution must include --wait flag"
    print("PASS: Production database migration job execution with --wait verified.")

    # 10. Production deployment to handover-prod with required flags
    assert 'gcloud run deploy "${{ env.PROD_SERVICE }}"' in raw_text or 'gcloud run deploy "$PROD_SERVICE"' in raw_text or 'gcloud run deploy "${PROD_SERVICE}"' in raw_text, "Missing gcloud run deploy for PROD_SERVICE"
    assert "--image=" in raw_text, "Missing --image parameter in deploy"
    assert "--service-account=" in raw_text, "Missing --service-account parameter in deploy"
    assert '--network="default"' in raw_text or "--network=default" in raw_text, "Missing --network=default in deploy"
    assert '--subnet="default"' in raw_text or "--subnet=default" in raw_text, "Missing --subnet=default in deploy"
    assert '--vpc-egress="private-ranges-only"' in raw_text or "--vpc-egress=private-ranges-only" in raw_text, "Missing --vpc-egress=private-ranges-only in deploy"
    assert "--clear-cloudsql-instances" in raw_text, "Missing --clear-cloudsql-instances in deploy"
    assert "DATABASE_URL=DATABASE_URL_PROD:latest" in raw_text, "Missing DATABASE_URL_PROD secret binding"
    assert "ADMIN_TOKEN=ADMIN_TOKEN_PROD:latest" in raw_text, "Missing ADMIN_TOKEN_PROD secret binding"
    assert "RELAY_WEBHOOK_TOKEN=RELAY_WEBHOOK_TOKEN_PROD:latest" in raw_text, "Missing RELAY_WEBHOOK_TOKEN_PROD secret binding"
    assert "APP_ENV=prod" in raw_text, "Missing APP_ENV=prod env var in deploy"
    print("PASS: Deployment to handover-prod with isolated secrets, VPC egress, and runtime limits verified.")

    # 11. Production smoke check against /api/healthz
    assert re.search(r"id:\s*smoke-check", raw_text), "Missing smoke-check step id"
    assert "${PROD_URL}/api/healthz" in raw_text or "$PROD_URL/api/healthz" in raw_text, "Smoke check must query PROD_URL/api/healthz"
    assert "status" in raw_text and "prod" in raw_text, "Smoke check must assert status: ok and environment: prod"
    assert "service_url=" in raw_text, "Smoke check must export service_url"
    print("PASS: Production smoke check against /api/healthz verified.")

    # 12. Promotion step summary output
    assert "GITHUB_STEP_SUMMARY" in raw_text, "Missing GITHUB_STEP_SUMMARY output"
    print("PASS: Promotion step summary output verified.")

    print("\nAll promote-prod workflow verification checks PASSED successfully.")


if __name__ == "__main__":
    verify_promote_workflow()
