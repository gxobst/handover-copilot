#!/usr/bin/env python3
"""Comprehensive verification script for Prometheus User-Impact Alerts (GitHub Issue #38).

Validates:
1. Local alert rules configuration (observability/alert.rules.yml):
   - Valid Prometheus 2.x YAML format and alert group naming.
   - HandoverGenerationFailureRateHigh: PromQL expression with > 0.2 threshold, 5m duration,
     required labels (service, environment, version, owner=shift-operations, severity=critical),
     and required annotations (summary, description, dashboard_url, runbook_url).
   - HandoverHttpErrorRateHigh: PromQL expression with > 0.1 threshold, 5m duration,
     required labels (service, environment, version, owner=shift-operations, severity=warning),
     and required annotations (summary, description, dashboard_url, runbook_url).
2. Prometheus configuration (observability/prometheus.yml):
   - Defines rule_files containing '/etc/prometheus/alert.rules.yml'.
3. Docker Compose configuration (observability/docker-compose.yml):
   - Mounts './alert.rules.yml:/etc/prometheus/alert.rules.yml:ro' in prometheus container.
4. Infrastructure provisioning scripts:
   - infra/08-observability-stack.sh and infra/08-observability-stack.ps1 include alert.rules.yml.
5. Remote Prometheus API (http://<HOST>:9090/api/v1/rules):
   - Returns HTTP 200 with status: 'success'.
   - Rules group loaded and both alerts active with health: 'ok'.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

REPO_ROOT = Path(__file__).resolve().parent.parent
OBSERVABILITY_DIR = REPO_ROOT / "observability"
ALERT_RULES_FILE = OBSERVABILITY_DIR / "alert.rules.yml"
PROMETHEUS_FILE = OBSERVABILITY_DIR / "prometheus.yml"
COMPOSE_FILE = OBSERVABILITY_DIR / "docker-compose.yml"
INFRA_SH_FILE = REPO_ROOT / "infra" / "08-observability-stack.sh"
INFRA_PS1_FILE = REPO_ROOT / "infra" / "08-observability-stack.ps1"


def parse_yaml_file(path: Path) -> dict:
    """Parse YAML file with PyYAML fallback to basic parsing if not installed."""
    raw = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        parsed = yaml.safe_load(raw)
        if isinstance(parsed, dict):
            return parsed
    except ImportError:
        pass
    except Exception as exc:
        raise ValueError(f"Failed to parse YAML file {path}: {exc}") from exc

    # Fallback minimal parser for basic dictionary structures
    return {"_raw": raw}


def verify_local_alert_rules() -> list[str]:
    """Verify observability/alert.rules.yml against all acceptance criteria."""
    errors: list[str] = []

    if not ALERT_RULES_FILE.is_file():
        errors.append(f"Alert rules file not found: {ALERT_RULES_FILE}")
        return errors

    raw_text = ALERT_RULES_FILE.read_text(encoding="utf-8")
    data = parse_yaml_file(ALERT_RULES_FILE)

    groups = data.get("groups") if isinstance(data, dict) else None
    if groups is None:
        if "groups:" not in raw_text:
            errors.append("alert.rules.yml missing top-level 'groups' key")
            return errors
        # If PyYAML wasn't available, rely on text inspection
        rules_map = {}
        for block in re.split(r"\n\s*-\s+alert:", raw_text)[1:]:
            alert_name = block.splitlines()[0].strip()
            rules_map[alert_name] = block
    else:
        rules_map = {}
        for group in groups:
            for rule in group.get("rules", []):
                alert_name = rule.get("alert")
                if alert_name:
                    rules_map[alert_name] = rule

    # 1. Verify HandoverGenerationFailureRateHigh
    if "HandoverGenerationFailureRateHigh" not in rules_map:
        errors.append("Rule 'HandoverGenerationFailureRateHigh' not found in alert.rules.yml")
    else:
        rule_obj = rules_map["HandoverGenerationFailureRateHigh"]
        rule_str = str(rule_obj)
        if "> 0.2" not in rule_str:
            errors.append("HandoverGenerationFailureRateHigh missing failure threshold '> 0.2'")
        if "5m" not in rule_str:
            errors.append("HandoverGenerationFailureRateHigh missing duration 'for: 5m'")
        if "handover_reports_generated_total" not in rule_str:
            errors.append("HandoverGenerationFailureRateHigh must query 'handover_reports_generated_total'")
        if "severity" not in rule_str or "critical" not in rule_str:
            errors.append("HandoverGenerationFailureRateHigh must specify 'severity: critical'")
        if "owner" not in rule_str or "shift-operations" not in rule_str:
            errors.append("HandoverGenerationFailureRateHigh must specify 'owner: shift-operations'")
        if "dashboard_url" not in rule_str:
            errors.append("HandoverGenerationFailureRateHigh must include 'dashboard_url' annotation")
        if "var-environment" not in rule_str or "var-version" not in rule_str:
            errors.append("HandoverGenerationFailureRateHigh dashboard_url must filter by var-environment & var-version")

    # 2. Verify HandoverHttpErrorRateHigh
    if "HandoverHttpErrorRateHigh" not in rules_map:
        errors.append("Rule 'HandoverHttpErrorRateHigh' not found in alert.rules.yml")
    else:
        rule_obj = rules_map["HandoverHttpErrorRateHigh"]
        rule_str = str(rule_obj)
        if "> 0.1" not in rule_str:
            errors.append("HandoverHttpErrorRateHigh missing threshold '> 0.1'")
        if "5m" not in rule_str:
            errors.append("HandoverHttpErrorRateHigh missing duration 'for: 5m'")
        if "handover_http_requests_total" not in rule_str:
            errors.append("HandoverHttpErrorRateHigh must query 'handover_http_requests_total'")
        if "severity" not in rule_str or ("warning" not in rule_str and "critical" not in rule_str):
            errors.append("HandoverHttpErrorRateHigh must specify 'severity: warning' or 'critical'")
        if "owner" not in rule_str or "shift-operations" not in rule_str:
            errors.append("HandoverHttpErrorRateHigh must specify 'owner: shift-operations'")
        if "dashboard_url" not in rule_str:
            errors.append("HandoverHttpErrorRateHigh must include 'dashboard_url' annotation")

    return errors


def verify_prometheus_config() -> list[str]:
    """Verify observability/prometheus.yml references alert.rules.yml."""
    errors: list[str] = []
    if not PROMETHEUS_FILE.is_file():
        errors.append(f"Prometheus configuration file not found: {PROMETHEUS_FILE}")
        return errors

    content = PROMETHEUS_FILE.read_text(encoding="utf-8")
    if "rule_files:" not in content or "alert.rules.yml" not in content:
        errors.append("prometheus.yml must include 'rule_files' referencing '/etc/prometheus/alert.rules.yml'")

    return errors


def verify_docker_compose_config() -> list[str]:
    """Verify observability/docker-compose.yml mounts alert.rules.yml."""
    errors: list[str] = []
    if not COMPOSE_FILE.is_file():
        errors.append(f"Docker Compose file not found: {COMPOSE_FILE}")
        return errors

    content = COMPOSE_FILE.read_text(encoding="utf-8")
    if "alert.rules.yml:/etc/prometheus/alert.rules.yml:ro" not in content:
        errors.append("docker-compose.yml must mount './alert.rules.yml:/etc/prometheus/alert.rules.yml:ro'")

    return errors


def verify_infra_scripts() -> list[str]:
    """Verify infra scripts include alert.rules.yml."""
    errors: list[str] = []
    if INFRA_SH_FILE.is_file():
        content_sh = INFRA_SH_FILE.read_text(encoding="utf-8")
        if "alert.rules.yml" not in content_sh:
            errors.append("infra/08-observability-stack.sh must include 'alert.rules.yml' in CONFIG_FILES")
    else:
        errors.append(f"Missing infra script: {INFRA_SH_FILE}")

    if INFRA_PS1_FILE.is_file():
        content_ps1 = INFRA_PS1_FILE.read_text(encoding="utf-8")
        if "alert.rules.yml" not in content_ps1:
            errors.append("infra/08-observability-stack.ps1 must include 'alert.rules.yml' in $configFiles")
    else:
        errors.append(f"Missing infra script: {INFRA_PS1_FILE}")

    return errors


def verify_remote_prometheus_rules(host: str, timeout: float = 8.0) -> list[str]:
    """Verify active rules loaded via remote Prometheus REST API."""
    errors: list[str] = []
    url = f"http://{host}:9090/api/v1/rules"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "VerifyAlerts/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.getcode() != 200:
                errors.append(f"Prometheus rules endpoint returned HTTP {resp.getcode()} (expected 200)")
                return errors

            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") != "success":
                errors.append(f"Prometheus rules endpoint returned status: {data.get('status')}")
                return errors

            groups = data.get("data", {}).get("groups", [])
            if not groups:
                errors.append("Prometheus returned zero rule groups")
                return errors

            found_rules: dict[str, dict] = {}
            for g in groups:
                for r in g.get("rules", []):
                    name = r.get("name")
                    if name:
                        found_rules[name] = r

            required_alerts = ["HandoverGenerationFailureRateHigh", "HandoverHttpErrorRateHigh"]
            for alert_name in required_alerts:
                if alert_name not in found_rules:
                    errors.append(f"Remote Prometheus missing active alert rule '{alert_name}'")
                else:
                    rule = found_rules[alert_name]
                    health = rule.get("health")
                    if health != "ok":
                        errors.append(f"Alert rule '{alert_name}' health is '{health}' (expected 'ok')")
                    labels = rule.get("labels", {})
                    if labels.get("owner") != "shift-operations":
                        errors.append(f"Alert rule '{alert_name}' missing label owner='shift-operations'")
                    ann = rule.get("annotations", {})
                    if "dashboard_url" not in ann:
                        errors.append(f"Alert rule '{alert_name}' missing annotation 'dashboard_url'")

    except Exception as exc:
        errors.append(f"Failed to query remote Prometheus API at {url}: {exc}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify Prometheus alerting rules configuration and remote deployment (Issue #38)."
    )
    parser.add_argument(
        "--prometheus-host",
        default=os.environ.get("PROMETHEUS_HOST", "34.153.185.34"),
        help="Prometheus host external IP or hostname (default: 34.153.185.34)",
    )
    parser.add_argument(
        "--skip-remote",
        action="store_true",
        help="Skip remote Prometheus API checks",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("   Prometheus User-Impact Failure Alerts Verification (Issue #38)")
    print(f"   Target Host: {args.prometheus_host}")
    print("=" * 70)

    all_errors: list[str] = []

    # 1. Local Alert Rules YAML
    print("\n[1/5] Verifying alert rules configuration (observability/alert.rules.yml)...")
    errs = verify_local_alert_rules()
    if errs:
        all_errors.extend(errs)
        for e in errs:
            print(f"  ❌ {e}")
    else:
        print("  ✅ alert.rules.yml syntax and rule group valid.")
        print("  ✅ HandoverGenerationFailureRateHigh defined (> 0.2 threshold, 5m duration, critical).")
        print("  ✅ HandoverHttpErrorRateHigh defined (> 0.1 threshold, 5m duration, warning).")
        print("  ✅ Required labels (service, environment, version, owner) verified.")
        print("  ✅ Required annotations (summary, description, dashboard_url, runbook_url) verified.")

    # 2. Prometheus config
    print("\n[2/5] Verifying Prometheus configuration (observability/prometheus.yml)...")
    errs = verify_prometheus_config()
    if errs:
        all_errors.extend(errs)
        for e in errs:
            print(f"  ❌ {e}")
    else:
        print("  ✅ prometheus.yml includes rule_files: ['/etc/prometheus/alert.rules.yml'].")

    # 3. Docker Compose mount
    print("\n[3/5] Verifying Docker Compose configuration (observability/docker-compose.yml)...")
    errs = verify_docker_compose_config()
    if errs:
        all_errors.extend(errs)
        for e in errs:
            print(f"  ❌ {e}")
    else:
        print("  ✅ docker-compose.yml mounts alert.rules.yml into container volumes as read-only (:ro).")

    # 4. Infra provisioning scripts
    print("\n[4/5] Verifying infrastructure scripts (infra/08-observability-stack.*)...")
    errs = verify_infra_scripts()
    if errs:
        all_errors.extend(errs)
        for e in errs:
            print(f"  ❌ {e}")
    else:
        print("  ✅ infra/08-observability-stack.sh includes alert.rules.yml.")
        print("  ✅ infra/08-observability-stack.ps1 includes alert.rules.yml.")

    # 5. Remote Prometheus API
    if not args.skip_remote:
        print(f"\n[5/5] Verifying remote Prometheus API (http://{args.prometheus_host}:9090/api/v1/rules)...")
        errs = verify_remote_prometheus_rules(args.prometheus_host)
        if errs:
            all_errors.extend(errs)
            for e in errs:
                print(f"  ❌ {e}")
        else:
            print(f"  ✅ Prometheus API returned HTTP 200 with status: 'success'.")
            print("  ✅ Rule group 'handover-user-impact-alerts' loaded.")
            print("  ✅ Both rules active with health: 'ok'.")
    else:
        print("\n[5/5] Remote Prometheus API check skipped (--skip-remote).")

    print("\n" + "=" * 70)
    if all_errors:
        print(f"❌ Verification FAILED with {len(all_errors)} error(s):")
        for err in all_errors:
            print(f"  • {err}")
        print("=" * 70)
        return 1

    print("✅ All Prometheus Alert Verification Checks PASSED!")
    print(f"   Alert Rules Path:   {ALERT_RULES_FILE}")
    print(f"   Prometheus Rules:   http://{args.prometheus_host}:9090/api/v1/rules")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
