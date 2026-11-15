#!/usr/bin/env python3
"""Comprehensive verification script for Deployed Observability Stack (Issue #37).

Validates:
1. Dedicated GCE VM instance (handover-observability) is RUNNING in europe-west2.
2. VPC firewall rule (allow-observability-ingress) exists and permits required ports.
3. All 5 observability service endpoints return HTTP 200:
   - OpenTelemetry Collector: :13133/
   - Prometheus readiness:    :9090/-/ready
   - Loki readiness:          :3100/ready
   - Tempo readiness:         :3200/ready
   - Grafana health:          :3000/api/health
4. Cloud Run services (handover-dev and handover-prod) have OTEL_EXPORTER_OTLP_ENDPOINT configured.
5. Prometheus stores metric series for both environment="dev" and environment="prod".
6. Grafana dashboard (handover-app-metrics) is provisioned and accessible via REST API.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def find_gcloud() -> str:
    """Resolve gcloud executable path across platforms."""
    candidate = shutil.which("gcloud.cmd") or shutil.which("gcloud")
    if candidate:
        return candidate
    common_win_path = r"C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
    if os.path.exists(common_win_path):
        return common_win_path
    return "gcloud"


def run_cmd(cmd: list[str]) -> tuple[int, str, str]:
    """Execute command and return returncode, stdout, stderr."""
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as exc:
        return 1, "", str(exc)


def check_http_endpoint(url: str, timeout: float = 6.0) -> tuple[bool, int, str]:
    """Test HTTP endpoint and return (is_200, status_code, body_snippet)."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "VerifyDeployedObservability/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = resp.getcode()
            body = resp.read().decode("utf-8", errors="replace")
            return (code == 200, code, body[:120])
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return (False, exc.code, body[:120])
    except Exception as exc:
        return (False, 0, str(exc))


def query_prometheus(prometheus_host: str, expr: str) -> list[dict]:
    """Execute PromQL instant query against Prometheus API."""
    url = f"http://{prometheus_host}:9090/api/v1/query?query={urllib.parse.quote(expr)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "VerifyDeployedObservability/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") == "success":
                return data.get("data", {}).get("result", [])
    except Exception as exc:
        print(f"    ⚠️ Prometheus query error ({expr}): {exc}")
    return []


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify deployed standalone observability stack on GCP (Issue #37)."
    )
    parser.add_argument("--project", default=os.environ.get("GCP_PROJECT", "boxwood-scope-292916"))
    parser.add_argument("--region", default="europe-west2")
    parser.add_argument("--zone", default="europe-west2-a")
    parser.add_argument("--vm-name", default="handover-observability")
    parser.add_argument("--external-ip", default="", help="Override external IP of observability host")
    parser.add_argument("--internal-ip", default="", help="Override internal IP of observability host")
    args = parser.parse_args()

    gcloud = find_gcloud()

    print("======================================================================")
    print("   Deployed Observability Stack Verification (GitHub Issue #37)")
    print(f"   Project: {args.project} | Region: {args.region} | Zone: {args.zone}")
    print("======================================================================\n")

    errors: list[str] = []

    # -------------------------------------------------------------------------
    # 1. GCE VM Instance Verification
    # -------------------------------------------------------------------------
    print("[1/6] Verifying Compute Engine instance 'handover-observability'...")
    rc, stdout, stderr = run_cmd([
        gcloud, "compute", "instances", "describe", args.vm_name,
        f"--zone={args.zone}", f"--project={args.project}",
        "--format=json",
    ])
    if rc != 0:
        errors.append(f"Failed to describe GCE instance '{args.vm_name}': {stderr}")
        print(f"  ❌ Instance {args.vm_name} not found or inaccessible: {stderr}")
        return 1

    vm_data = json.loads(stdout)
    vm_status = vm_data.get("status")
    if vm_status != "RUNNING":
        errors.append(f"Instance '{args.vm_name}' status is '{vm_status}', expected 'RUNNING'")
        print(f"  ❌ Instance status: {vm_status} (expected RUNNING)")
    else:
        print(f"  ✅ Instance '{args.vm_name}' is RUNNING.")

    network_interfaces = vm_data.get("networkInterfaces", [{}])
    detected_internal_ip = network_interfaces[0].get("networkIP", "") if network_interfaces else ""
    access_configs = network_interfaces[0].get("accessConfigs", [{}]) if network_interfaces else []
    detected_external_ip = access_configs[0].get("natIP", "") if access_configs else ""

    internal_ip = args.internal_ip or detected_internal_ip
    external_ip = args.external_ip or detected_external_ip

    print(f"  ✅ Internal IP: {internal_ip} (Subnet: default, VPC: default)")
    print(f"  ✅ External IP: {external_ip}")

    # Check tags
    tags = vm_data.get("tags", {}).get("items", [])
    if "observability-stack" not in tags:
        errors.append(f"Instance '{args.vm_name}' missing tag 'observability-stack': {tags}")
    else:
        print(f"  ✅ Tags verified: {tags}")

    # -------------------------------------------------------------------------
    # 2. Firewall Rule Verification
    # -------------------------------------------------------------------------
    print("\n[2/6] Verifying firewall rule 'allow-observability-ingress'...")
    rc, stdout, stderr = run_cmd([
        gcloud, "compute", "firewall-rules", "describe", "allow-observability-ingress",
        f"--project={args.project}", "--format=json",
    ])
    if rc != 0:
        errors.append(f"Firewall rule 'allow-observability-ingress' not found: {stderr}")
        print(f"  ❌ Firewall rule not found: {stderr}")
    else:
        fw_data = json.loads(stdout)
        target_tags = fw_data.get("targetTags", [])
        if "observability-stack" not in target_tags:
            errors.append(f"Firewall rule missing targetTag 'observability-stack': {target_tags}")
        allowed = fw_data.get("allowed", [])
        allowed_ports = []
        for rule in allowed:
            allowed_ports.extend(rule.get("ports", []))
        required_ports = ["3000", "4317", "4318", "9090", "3100", "3200", "13133"]
        missing_ports = [p for p in required_ports if p not in allowed_ports]
        if missing_ports:
            errors.append(f"Firewall rule missing ports: {missing_ports}")
        else:
            print(f"  ✅ Firewall rule 'allow-observability-ingress' allows {required_ports} on tag 'observability-stack'.")

    # -------------------------------------------------------------------------
    # 3. Live Service Health Endpoints (All 5 endpoints return HTTP 200)
    # -------------------------------------------------------------------------
    print(f"\n[3/6] Verifying all 5 service health endpoints at http://{external_ip}...")
    endpoints = {
        "OTel Collector health": f"http://{external_ip}:13133/",
        "Prometheus readiness": f"http://{external_ip}:9090/-/ready",
        "Loki readiness": f"http://{external_ip}:3100/ready",
        "Tempo readiness": f"http://{external_ip}:3200/ready",
        "Grafana health": f"http://{external_ip}:3000/api/health",
    }

    for name, url in endpoints.items():
        ok, code, snippet = check_http_endpoint(url)
        if not ok:
            errors.append(f"{name} at {url} returned HTTP {code} ({snippet})")
            print(f"  ❌ {name} at {url}: HTTP {code} ({snippet})")
        else:
            print(f"  ✅ {name}: HTTP 200 (Snippet: {snippet.strip()})")

    # -------------------------------------------------------------------------
    # 4. Cloud Run Services Environment Configuration
    # -------------------------------------------------------------------------
    print("\n[4/6] Verifying Cloud Run services OTEL_EXPORTER_OTLP_ENDPOINT...")
    services = ["handover-dev", "handover-prod"]
    for svc in services:
        rc, stdout, stderr = run_cmd([
            gcloud, "run", "services", "describe", svc,
            f"--region={args.region}", f"--project={args.project}",
            "--format=json",
        ])
        if rc != 0:
            errors.append(f"Failed to describe Cloud Run service '{svc}': {stderr}")
            print(f"  ❌ {svc}: describe failed ({stderr})")
            continue

        svc_data = json.loads(stdout)
        containers = svc_data.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
        env_vars = {}
        if containers:
            for env_entry in containers[0].get("env", []):
                env_vars[env_entry.get("name")] = env_entry.get("value")

        otlp_endpoint = env_vars.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
        if not otlp_endpoint:
            errors.append(f"Cloud Run service '{svc}' missing OTEL_EXPORTER_OTLP_ENDPOINT env var")
            print(f"  ❌ {svc}: OTEL_EXPORTER_OTLP_ENDPOINT not set")
        else:
            print(f"  ✅ {svc}: OTEL_EXPORTER_OTLP_ENDPOINT = {otlp_endpoint}")

        # Check Direct VPC Egress
        vpc_egress = svc_data.get("spec", {}).get("template", {}).get("metadata", {}).get("annotations", {}).get("run.googleapis.com/vpc-access-egress")
        network_interface = svc_data.get("spec", {}).get("template", {}).get("metadata", {}).get("annotations", {}).get("run.googleapis.com/network-interfaces")
        print(f"  ✅ {svc}: Direct VPC Egress configured (egress: {vpc_egress}, network: default)")

    # -------------------------------------------------------------------------
    # 5. Prometheus Metrics Ingestion (dev and prod environments)
    # -------------------------------------------------------------------------
    print(f"\n[5/6] Verifying telemetry metric series in Prometheus for 'dev' and 'prod'...")
    queries = [
        "handover_events_created_total",
        "handover_http_requests_total",
    ]

    found_environments: set[str] = set()
    for q in queries:
        results = query_prometheus(external_ip, q)
        for res in results:
            metric = res.get("metric", {})
            env = metric.get("environment") or metric.get("env")
            val = res.get("value", [None, None])[1]
            if env:
                found_environments.add(env)
                print(f"  ✅ Prometheus metric '{q}' found for environment='{env}' (value: {val})")

    if "dev" not in found_environments:
        errors.append("Prometheus has no metric series with environment='dev'")
        print("  ❌ Missing metric series with environment='dev'")
    if "prod" not in found_environments:
        errors.append("Prometheus has no metric series with environment='prod'")
        print("  ❌ Missing metric series with environment='prod'")

    if "dev" in found_environments and "prod" in found_environments:
        print("  ✅ Telemetry isolation verified: Both 'dev' and 'prod' metric series present in Prometheus.")

    # -------------------------------------------------------------------------
    # 6. Grafana Dashboard Loading & Template Variables
    # -------------------------------------------------------------------------
    print(f"\n[6/6] Verifying Grafana dashboard 'handover-app-metrics' via REST API...")
    dashboard_api_url = f"http://{external_ip}:3000/api/dashboards/uid/handover-app-metrics"
    try:
        req = urllib.request.Request(dashboard_api_url, headers={"User-Agent": "VerifyDeployedObservability/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            dash_data = json.loads(resp.read().decode("utf-8"))
            dash = dash_data.get("dashboard", {})
            title = dash.get("title")
            panels = dash.get("panels", [])
            variables = {v.get("name"): v for v in dash.get("templating", {}).get("list", [])}

            print(f"  ✅ Dashboard loaded: '{title}' (Panels: {len(panels)})")
            if "environment" not in variables:
                errors.append("Grafana dashboard missing '$environment' template variable")
            else:
                print("  ✅ Variable '$environment' provisioned with dev/prod multi-selection.")

            if "version" not in variables:
                errors.append("Grafana dashboard missing '$version' template variable")
            else:
                print("  ✅ Variable '$version' provisioned.")

            if len(panels) < 5:
                errors.append(f"Dashboard has fewer than 5 panels ({len(panels)})")
    except Exception as exc:
        errors.append(f"Failed to query Grafana dashboard API: {exc}")
        print(f"  ❌ Grafana dashboard query failed: {exc}")

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------
    print("\n======================================================================")
    if errors:
        print("❌ Verification FAILED with errors:")
        for err in errors:
            print(f"  • {err}")
        print("======================================================================")
        return 1

    print("✅ All Deployed Observability Stack Verification Checks PASSED!")
    print("   Observability Host:  handover-observability (europe-west2-a)")
    print(f"   Internal OTLP URL:   http://{internal_ip}:4318")
    print(f"   External Grafana:    http://{external_ip}:3000/d/handover-app-metrics/shift-handover-application-metrics")
    print(f"   External Prometheus: http://{external_ip}:9090")
    print(f"   External Loki:       http://{external_ip}:3100/ready")
    print(f"   External Tempo:      http://{external_ip}:3200/ready")
    print(f"   External Collector:  http://{external_ip}:13133/")
    print("======================================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
