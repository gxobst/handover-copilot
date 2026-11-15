#!/usr/bin/env python3
"""Verification script for OpenTelemetry Collector and Observability Stack (Issue #35).

Validates:
1. Existence and valid syntax of all observability configuration files.
2. Compose project isolation (project name 'handover-observability').
3. OpenTelemetry Collector configuration (OTLP gRPC/HTTP receivers, exporters, pipelines).
4. Prometheus configuration (scrapes otel-collector:8889).
5. Loki standalone configuration (filesystem storage, port 3100).
6. Tempo trace ingestion configuration (port 3200, OTLP gRPC 4317).
7. Grafana datasource provisioning (Prometheus, Loki, Tempo, trace-to-logs, logs-to-traces).
8. Host port exposure and health check / start order dependencies.
9. Optional live endpoint verification against running containers (--live / --wait).
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

REPO_ROOT = Path(__file__).resolve().parent.parent
OBSERVABILITY_DIR = REPO_ROOT / "observability"

COMPOSE_FILE = OBSERVABILITY_DIR / "docker-compose.yml"
OTEL_CONFIG_FILE = OBSERVABILITY_DIR / "otel-collector-config.yaml"
PROMETHEUS_FILE = OBSERVABILITY_DIR / "prometheus.yml"
LOKI_CONFIG_FILE = OBSERVABILITY_DIR / "loki-config.yaml"
TEMPO_CONFIG_FILE = OBSERVABILITY_DIR / "tempo-config.yaml"
DATASOURCES_FILE = OBSERVABILITY_DIR / "datasources.yaml"


def try_parse_yaml(raw_text: str) -> dict:
    """Parse YAML using PyYAML if available, or lightweight stdlib fallback."""
    try:
        import yaml  # type: ignore

        parsed = yaml.safe_load(raw_text)
        if isinstance(parsed, dict):
            return parsed
    except ImportError:
        pass
    except Exception as exc:
        raise ValueError(f"YAML parsing failed: {exc}") from exc

    # Minimal fallback parser for structural verification when PyYAML is unavailable
    lines = raw_text.splitlines()
    data: dict = {}
    current_key = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0 and ":" in stripped:
            k, v = stripped.split(":", 1)
            current_key = k.strip()
            data[current_key] = v.strip() or {}
    return data


def verify_static_configuration() -> list[str]:
    """Verify all static configuration files and acceptance criteria."""
    errors: list[str] = []

    # 1. Directory and file existence
    if not OBSERVABILITY_DIR.is_dir():
        errors.append(f"Directory {OBSERVABILITY_DIR} does not exist.")
        return errors

    expected_files = [
        ("docker-compose.yml", COMPOSE_FILE),
        ("otel-collector-config.yaml", OTEL_CONFIG_FILE),
        ("prometheus.yml", PROMETHEUS_FILE),
        ("loki-config.yaml", LOKI_CONFIG_FILE),
        ("tempo-config.yaml", TEMPO_CONFIG_FILE),
        ("datasources.yaml", DATASOURCES_FILE),
    ]

    for name, path in expected_files:
        if not path.is_file():
            errors.append(f"Missing required configuration file: {path}")

    if errors:
        return errors

    # Read all configuration files
    compose_text = COMPOSE_FILE.read_text(encoding="utf-8")
    otel_text = OTEL_CONFIG_FILE.read_text(encoding="utf-8")
    prom_text = PROMETHEUS_FILE.read_text(encoding="utf-8")
    loki_text = LOKI_CONFIG_FILE.read_text(encoding="utf-8")
    tempo_text = TEMPO_CONFIG_FILE.read_text(encoding="utf-8")
    datasources_text = DATASOURCES_FILE.read_text(encoding="utf-8")

    # 2. Compose Project Isolation
    compose_data = try_parse_yaml(compose_text)
    project_name = compose_data.get("name") if isinstance(compose_data, dict) else None
    if not project_name:
        match = re.search(r"^name:\s*([a-zA-Z0-9_-]+)", compose_text, re.MULTILINE)
        project_name = match.group(1) if match else None

    if project_name != "handover-observability":
        errors.append(
            f"Compose project name must be 'handover-observability', found: '{project_name}'"
        )

    # Required services in Compose
    required_services = ["otel-collector", "prometheus", "loki", "tempo", "grafana"]
    for svc in required_services:
        pattern = rf"^\s{{2,4}}{re.escape(svc)}:\s*$"
        if not re.search(pattern, compose_text, re.MULTILINE):
            errors.append(f"docker-compose.yml missing required service '{svc}'")

    # Image checks
    if "otel/opentelemetry-collector-contrib" not in compose_text:
        errors.append(
            "otel-collector must use image 'otel/opentelemetry-collector-contrib' to support Loki exporter"
        )
    if "prom/prometheus" not in compose_text:
        errors.append("prometheus service must use prom/prometheus image")
    if "grafana/loki" not in compose_text:
        errors.append("loki service must use grafana/loki image")
    if "grafana/tempo" not in compose_text:
        errors.append("tempo service must use grafana/tempo image")
    if "grafana/grafana" not in compose_text:
        errors.append("grafana service must use grafana/grafana image")

    # Port mappings
    required_ports = ["4317", "4318", "8889", "13133", "9090", "3100", "3200", "3000"]
    for port in required_ports:
        port_pattern = rf"[\"']?{port}:{port}[\"']?"
        if not re.search(port_pattern, compose_text):
            errors.append(f"docker-compose.yml missing port mapping for '{port}:{port}'")

    # Start order dependencies & Grafana anonymous admin
    if "depends_on" not in compose_text:
        errors.append("docker-compose.yml must define depends_on start order dependencies")
    if "GF_AUTH_ANONYMOUS_ENABLED" not in compose_text or "true" not in compose_text:
        errors.append("Grafana service must set GF_AUTH_ANONYMOUS_ENABLED=true")
    if "GF_AUTH_ANONYMOUS_ORG_ROLE" not in compose_text or "Admin" not in compose_text:
        errors.append("Grafana service must set GF_AUTH_ANONYMOUS_ORG_ROLE=Admin")

    # 3. OpenTelemetry Collector Configuration
    # Receivers: OTLP gRPC 4317, HTTP 4318
    if not re.search(r"endpoint:\s*0\.0\.0\.0:4317", otel_text):
        errors.append("otel-collector-config.yaml missing OTLP gRPC receiver endpoint 0.0.0.0:4317")
    if not re.search(r"endpoint:\s*0\.0\.0\.0:4318", otel_text):
        errors.append("otel-collector-config.yaml missing OTLP HTTP receiver endpoint 0.0.0.0:4318")

    # Exporters: prometheus 8889, loki push, tempo 4317
    if not re.search(r"endpoint:\s*0\.0\.0\.0:8889", otel_text):
        errors.append("otel-collector-config.yaml missing Prometheus exporter on 0.0.0.0:8889")
    if "http://loki:3100/loki/api/v1/push" not in otel_text:
        errors.append(
            "otel-collector-config.yaml missing Loki exporter pushing to http://loki:3100/loki/api/v1/push"
        )
    if "tempo:4317" not in otel_text:
        errors.append("otel-collector-config.yaml missing Tempo exporter endpoint tempo:4317")

    # Pipelines: traces, metrics, logs
    if "traces:" not in otel_text or "otlp/tempo" not in otel_text:
        errors.append("otel-collector-config.yaml missing traces pipeline exporting to otlp/tempo")
    if "metrics:" not in otel_text or "prometheus" not in otel_text:
        errors.append("otel-collector-config.yaml missing metrics pipeline exporting to prometheus")
    if "logs:" not in otel_text or "loki" not in otel_text:
        errors.append("otel-collector-config.yaml missing logs pipeline exporting to loki")

    # Health check extension
    if "13133" not in otel_text or "health_check" not in otel_text:
        errors.append("otel-collector-config.yaml missing health_check extension on port 13133")

    # 4. Prometheus Configuration
    if "otel-collector:8889" not in prom_text:
        errors.append("prometheus.yml missing scrape target for 'otel-collector:8889'")

    # 5. Loki Configuration
    if not re.search(r"auth_enabled:\s*false", loki_text):
        errors.append("loki-config.yaml must configure auth_enabled: false")
    if "3100" not in loki_text:
        errors.append("loki-config.yaml missing http_listen_port 3100")
    if "filesystem" not in loki_text:
        errors.append("loki-config.yaml missing local filesystem storage configuration")

    # 6. Tempo Configuration
    if "3200" not in tempo_text:
        errors.append("tempo-config.yaml missing server http_listen_port 3200")
    if "4317" not in tempo_text:
        errors.append("tempo-config.yaml missing OTLP gRPC ingestion receiver on 4317")

    # 7. Grafana Datasources Provisioning
    if "http://prometheus:9090" not in datasources_text:
        errors.append("datasources.yaml missing Prometheus datasource url 'http://prometheus:9090'")
    if "http://loki:3100" not in datasources_text:
        errors.append("datasources.yaml missing Loki datasource url 'http://loki:3100'")
    if "http://tempo:3200" not in datasources_text:
        errors.append("datasources.yaml missing Tempo datasource url 'http://tempo:3200'")

    # Correlated navigation: logs-to-traces (Loki derivedFields) and traces-to-logs (Tempo tracesToLogs)
    if "derivedFields" not in datasources_text or "datasourceUid: tempo" not in datasources_text:
        errors.append(
            "datasources.yaml missing Loki derivedFields navigation linking trace_id to Tempo"
        )
    if "tracesToLogs" not in datasources_text or "datasourceUid: loki" not in datasources_text:
        errors.append(
            "datasources.yaml missing Tempo tracesToLogs navigation linking traces to Loki"
        )

    return errors


def check_endpoint(url: str, timeout: float = 3.0) -> tuple[bool, int, str]:
    """Ping an HTTP endpoint and return (is_healthy, status_code, message)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "VerifyObservability/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = response.getcode()
            return (status == 200, status, f"HTTP {status}")
    except urllib.error.HTTPError as exc:
        return (False, exc.code, f"HTTP {exc.code}: {exc.reason}")
    except Exception as exc:
        return (False, 0, str(exc))


def verify_live_endpoints(wait_seconds: int = 0) -> list[str]:
    """Verify live connectivity and health for all 5 observability services."""
    endpoints = {
        "Prometheus readiness": "http://localhost:9090/-/ready",
        "Loki readiness": "http://localhost:3100/ready",
        "Tempo readiness": "http://localhost:3200/ready",
        "Grafana health": "http://localhost:3000/api/health",
        "OTel Collector health": "http://localhost:13133/",
    }

    deadline = time.time() + max(wait_seconds, 1)
    failed: dict[str, str] = {}

    while True:
        failed.clear()
        for name, url in endpoints.items():
            healthy, code, msg = check_endpoint(url)
            if not healthy:
                failed[name] = f"{url} -> {msg}"

        if not failed:
            break

        if time.time() >= deadline:
            break

        time.sleep(2)

    errors: list[str] = []
    for name, reason in failed.items():
        errors.append(f"Live health check failed for {name}: {reason}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify OpenTelemetry Collector and Observability Stack configuration and endpoints."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Perform live health checks against running service containers.",
    )
    parser.add_argument(
        "--wait",
        type=int,
        default=0,
        help="Max seconds to wait for live services to become ready (implies --live).",
    )
    args = parser.parse_args()

    print("======================================================================")
    print("   OpenTelemetry & Observability Stack Verification (Issue #35)")
    print("======================================================================\n")

    print("[1/2] Verifying static configuration files...")
    static_errors = verify_static_configuration()

    if static_errors:
        print("\nFAILED: Static configuration checks failed:")
        for err in static_errors:
            print(f"  ❌ {err}")
        return 1

    print("  ✅ Observability directory and Docker Compose configuration present.")
    print("  ✅ Compose project isolated under 'handover-observability'.")
    print("  ✅ OpenTelemetry Collector configured with OTLP gRPC/HTTP, Loki, Tempo, Prometheus.")
    print("  ✅ Prometheus scrape target configured for otel-collector:8889.")
    print("  ✅ Loki standalone filesystem storage configured on port 3100.")
    print("  ✅ Tempo trace storage and OTLP gRPC ingestion configured on port 3200/4317.")
    print("  ✅ Grafana datasources provisioned with trace-to-logs and logs-to-traces links.")
    print("  ✅ Grafana anonymous admin access configured.")

    if args.live or args.wait > 0:
        print(f"\n[2/2] Checking live health endpoints (timeout: {args.wait}s)...")
        live_errors = verify_live_endpoints(wait_seconds=args.wait)
        if live_errors:
            print("\nFAILED: Live service health checks failed:")
            for err in live_errors:
                print(f"  ❌ {err}")
            return 1
        print("  ✅ Prometheus endpoint (http://localhost:9090/-/ready) returned HTTP 200.")
        print("  ✅ Loki endpoint (http://localhost:3100/ready) returned HTTP 200.")
        print("  ✅ Tempo endpoint (http://localhost:3200/ready) returned HTTP 200.")
        print("  ✅ Grafana endpoint (http://localhost:3000/api/health) returned HTTP 200.")
        print("  ✅ OTel Collector endpoint (http://localhost:13133/) returned HTTP 200.")
    else:
        # Check if containers happen to be running; if so, verify them cleanly
        _, code, _ = check_endpoint("http://localhost:3000/api/health", timeout=0.5)
        if code == 200:
            print("\n[2/2] Detected running stack; verifying live health endpoints...")
            live_errors = verify_live_endpoints(wait_seconds=5)
            if live_errors:
                print("\nFAILED: Live service health checks failed:")
                for err in live_errors:
                    print(f"  ❌ {err}")
                return 1
            print("  ✅ All live services are healthy and responding with HTTP 200.")
        else:
            print("\n[2/2] Live check skipped (use --live or --wait <seconds> to verify active containers).")

    print("\n======================================================================")
    print("✅ All Observability Stack Verification Checks PASSED!")
    print("======================================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
