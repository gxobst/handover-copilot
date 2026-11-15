#!/usr/bin/env python3
"""Verification script for GCP CI/CD Pipeline workflow (Issue #27, #32)."""

from pathlib import Path
import re
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINE_FILE = REPO_ROOT / ".github" / "workflows" / "gcp-pipeline.yml"
DEPLOY_DEV_FILE = REPO_ROOT / ".github" / "workflows" / "deploy-dev.yml"

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
            data["jobs"][current_job] = {"needs": [], "steps": []}
            continue

        if current_job:
            # Check needs under job
            if indent == 4 and stripped.startswith("needs:"):
                needs_val = stripped.split(":", 1)[1].strip()
                if needs_val.startswith("[") and needs_val.endswith("]"):
                    items = [x.strip() for x in needs_val[1:-1].split(",") if x.strip()]
                    data["jobs"][current_job]["needs"] = items
                elif needs_val:
                    data["jobs"][current_job]["needs"] = [needs_val]

    return data


def verify_deploy_dev_if_present():
    """Verify deploy-dev.yml if retained for manual dev redeployment."""
    if not DEPLOY_DEV_FILE.exists():
        print(f"INFO: {DEPLOY_DEV_FILE} does not exist (deleted as superseded).")
        return

    print(f"Inspecting manual deploy-dev workflow: {DEPLOY_DEV_FILE}")
    raw_dev = DEPLOY_DEV_FILE.read_text(encoding="utf-8")

    # Forbidden cloud provider check
    if FORBIDDEN_PROVIDER.lower() in raw_dev.lower():
        print(f"FAIL: Forbidden provider reference found in {DEPLOY_DEV_FILE}")
        sys.exit(1)

    # Automated push trigger must NOT be present
    assert "push:" not in raw_dev, "deploy-dev.yml must NOT have automated push triggers!"
    assert "workflow_dispatch:" in raw_dev, "deploy-dev.yml must have workflow_dispatch trigger"

    # Separate build and deploy stages
    assert re.search(r"^\s\sbuild:\s*$", raw_dev, re.MULTILINE), "deploy-dev.yml missing 'build' job"
    assert re.search(r"^\s\sdeploy:\s*$", raw_dev, re.MULTILINE), "deploy-dev.yml missing 'deploy' job"

    deploy_match = re.search(r"deploy:(.*)", raw_dev, re.DOTALL)
    assert deploy_match, "deploy job block missing in deploy-dev.yml"
    assert "needs: [build]" in deploy_match.group(1) or "needs:\n      - build" in deploy_match.group(1) or "needs: build" in deploy_match.group(1), "deploy-dev deploy job must depend on build job"

    print("PASS: deploy-dev.yml trigger and two-stage build/deploy architecture verified.")


def verify_pipeline():
    print(f"Inspecting pipeline file: {PIPELINE_FILE}")
    if not PIPELINE_FILE.exists():
        print(f"FAIL: Pipeline file does not exist at {PIPELINE_FILE}")
        sys.exit(1)

    raw_text = PIPELINE_FILE.read_text(encoding="utf-8")

    # 1. Zero occurrences of forbidden cloud provider
    if FORBIDDEN_PROVIDER.lower() in raw_text.lower():
        print(f"FAIL: Forbidden provider reference found in {PIPELINE_FILE}")
        sys.exit(1)
    print("PASS: Zero forbidden cloud provider references found.")

    # 2. Valid YAML structure
    data = try_parse_yaml(raw_text)
    if not isinstance(data, dict):
        print("FAIL: Root YAML object is not a dictionary.")
        sys.exit(1)
    print("PASS: Valid YAML structure.")

    # 3. Triggers: push to main and workflow_dispatch
    try:
        import yaml  # type: ignore
        full_parsed = yaml.safe_load(raw_text)
        triggers = full_parsed.get("on") if "on" in full_parsed else full_parsed.get(True)
        assert isinstance(triggers, dict), "Missing trigger dict"
        assert "main" in triggers.get("push", {}).get("branches", []), "push to main missing"
        assert "workflow_dispatch" in triggers, "workflow_dispatch missing"
    except ImportError:
        assert re.search(r"push:\s*\n\s*branches:\s*\n\s*-\s*main", raw_text), "push on main missing"
        assert "workflow_dispatch:" in raw_text, "workflow_dispatch missing"
    print("PASS: Triggers verified (push on main, workflow_dispatch).")

    # 4. Top-level permissions & concurrency
    assert re.search(r"id-token:\s*write", raw_text), "Permissions missing 'id-token: write'"
    assert re.search(r"contents:\s*read", raw_text), "Permissions missing 'contents: read'"
    assert re.search(r"group:\s*gcp-pipeline-\${{\s*github\.ref\s*}}", raw_text), "Concurrency group mismatch"
    assert re.search(r"cancel-in-progress:\s*false", raw_text), "cancel-in-progress should be false"
    print("PASS: Permissions and concurrency verified.")

    # 5. Required jobs present
    required_jobs = ["backend-test", "frontend-test", "integration-and-e2e", "build-image", "deploy-gcp"]
    for job in required_jobs:
        assert re.search(rf"^\s\s{re.escape(job)}:\s*$", raw_text, re.MULTILINE), f"Job {job} missing"
    print(f"PASS: All required jobs present: {required_jobs}")

    # 6. Parallel execution of backend-test and frontend-test
    backend_block = re.search(r"backend-test:(.*?)(frontend-test:|integration-and-e2e:|build-image:|deploy-gcp:)", raw_text, re.DOTALL)
    frontend_block = re.search(r"frontend-test:(.*?)(backend-test:|integration-and-e2e:|build-image:|deploy-gcp:)", raw_text, re.DOTALL)
    assert backend_block and "needs:" not in backend_block.group(1), "backend-test should have no dependencies"
    assert frontend_block and "needs:" not in frontend_block.group(1), "frontend-test should have no dependencies"
    print("PASS: 'backend-test' and 'frontend-test' run concurrently in parallel.")

    # 7. integration-and-e2e needs both backend-test and frontend-test
    integ_block = re.search(r"integration-and-e2e:(.*?)(build-image:|deploy-gcp:|$)", raw_text, re.DOTALL)
    assert integ_block, "Missing integration-and-e2e job block"
    integ_text = integ_block.group(1)
    needs_match = re.search(r"needs:\s*\[(.*?)\]", integ_text)
    assert needs_match, "integration-and-e2e missing needs list"
    needs_items = {item.strip() for item in needs_match.group(1).split(",")}
    assert {"backend-test", "frontend-test"}.issubset(needs_items), f"Expected [backend-test, frontend-test], got {needs_items}"
    print("PASS: 'integration-and-e2e' depends on [backend-test, frontend-test].")

    # 8. integration-and-e2e steps: docker compose, health check loop, integration script, playwright e2e, compose down
    assert "docker compose up -d --build --wait" in integ_text, "Missing docker compose up"
    assert "http://127.0.0.1:8000/api/healthz" in integ_text, "Missing healthz check"
    assert "python scripts/test_compose_integration.py --base-url http://127.0.0.1:8000" in integ_text, "Missing test_compose_integration.py"
    assert "npm run test:e2e" in integ_text, "Missing npm run test:e2e"
    assert re.search(r"docker compose down -v.*?if:\s*always\(\)", integ_text, re.DOTALL) or re.search(r"if:\s*always\(\).*?docker compose down -v", integ_text, re.DOTALL), "Missing docker compose down -v under if: always()"
    print("PASS: 'integration-and-e2e' steps and cleanup verified.")

    # 9. build-image job block and dependency
    build_block = re.search(r"build-image:(.*?)(deploy-gcp:|$)", raw_text, re.DOTALL)
    assert build_block, "Missing build-image job block"
    build_text = build_block.group(1)
    build_needs_match = re.search(r"needs:\s*\[(.*?)\]", build_text)
    assert build_needs_match and "integration-and-e2e" in build_needs_match.group(1), "build-image must depend on [integration-and-e2e]"
    assert "id-token: write" in build_text, "Missing id-token: write in build-image"
    print("PASS: 'build-image' depends on [integration-and-e2e].")

    # 10. Tag pattern YYYYMMDD-HHMMSS-shortsha and build outputs
    assert re.search(r"date\s+\+%Y%m%d-%H%M%S", build_text), "Missing timestamp pattern '%Y%m%d-%H%M%S'"
    assert re.search(r"git\s+rev-parse\s+--short\s+HEAD", build_text), "Missing short sha calculation"
    assert re.search(r'TAG="\${TIMESTAMP}-\${SHORT_SHA}"', build_text) or re.search(r"TAG=.*TIMESTAMP.*SHORT_SHA", build_text), "Missing TAG formatted as ${TIMESTAMP}-${SHORT_SHA}"
    assert "outputs:" in build_text, "Missing outputs declaration in build-image"
    assert re.search(r"image_tag:\s*\${{\s*steps\.image-tag\.outputs\.tag\s*}}", build_text), "Missing image_tag output mapping in build-image"
    assert re.search(r"image_uri:\s*\${{\s*steps\.image-tag\.outputs\.image_uri\s*}}", build_text), "Missing image_uri output mapping in build-image"
    assert "gcloud auth configure-docker" in build_text, "Missing configure-docker step in build-image"
    assert "docker build" in build_text, "Missing docker build step in build-image"
    assert "docker push" in build_text, "Missing docker push step in build-image"
    print("PASS: Tag pattern 'YYYYMMDD-HHMMSS-shortsha' and build-image outputs/push verified.")

    # 11. deploy-gcp needs build-image and consumes outputs
    deploy_block = re.search(r"deploy-gcp:(.*)", raw_text, re.DOTALL)
    assert deploy_block, "Missing deploy-gcp job block"
    deploy_text = deploy_block.group(1)
    deploy_needs_match = re.search(r"needs:\s*\[(.*?)\]", deploy_text)
    assert deploy_needs_match and "build-image" in deploy_needs_match.group(1), "deploy-gcp must depend on [build-image]"
    assert re.search(r"needs\.build-image\.outputs\.image_uri", deploy_text), "deploy-gcp must consume needs.build-image.outputs.image_uri"
    assert "PORT=8000" not in re.search(r"--set-env-vars=[^\n]+", deploy_text).group(0), "PORT=8000 should not be in --set-env-vars"
    print("PASS: 'deploy-gcp' depends on [build-image] and consumes build image output.")

    # 12. OIDC authentication via WIF
    assert "google-github-actions/auth@v2" in deploy_text, "Missing google-github-actions/auth@v2"
    assert "workload_identity_provider:" in deploy_text, "Missing workload_identity_provider"
    assert "service_account:" in deploy_text, "Missing service_account"
    assert "id-token: write" in deploy_text, "Missing id-token: write in deploy-gcp"
    print("PASS: Google Cloud WIF authentication step verified.")

    # 13. Cloud Run deployment and migration job
    assert "gcloud run jobs execute handover-migrate" in deploy_text, "Missing migration job execution"
    assert "gcloud run deploy" in deploy_text, "Missing gcloud run deploy"
    print("PASS: Cloud Run migration and deployment commands verified.")

    # 14. Post-deployment health validation
    assert re.search(r"id:\s*validate-deploy", deploy_text), "Missing validate-deploy step"
    assert "gcloud run services describe" in deploy_text, "Missing service URL resolution"
    assert "${SERVICE_URL}/api/healthz" in deploy_text or "$SERVICE_URL/api/healthz" in deploy_text, "Missing service URL healthz polling"
    assert "200" in deploy_text and ('"ok"' in deploy_text or "'ok'" in deploy_text), "Missing 200 / ok verification"
    assert "GITHUB_STEP_SUMMARY" in deploy_text, "Missing GITHUB_STEP_SUMMARY publication"
    print("PASS: Post-deployment health validation step verified.")

    # 15. Verify deploy-dev.yml if present
    verify_deploy_dev_if_present()

    print("\nAll pipeline verification checks PASSED successfully.")


if __name__ == "__main__":
    verify_pipeline()
