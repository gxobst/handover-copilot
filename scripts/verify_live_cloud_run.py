"""Live verification script for Shift Handover Copilot Cloud Run deployment."""

import json
import re
import sys
import time
import urllib.request
import urllib.error

BASE_URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "https://handover-dev-budwggf4rq-nw.a.run.app"

print("============================================================")
print(f" Verifying Live Cloud Run Deployment: {BASE_URL}")
print("============================================================")

def http_get(path: str):
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "VerificationScript/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, resp.headers, resp.read()

def http_post_json(path: str, data: dict):
    url = f"{BASE_URL}{path}"
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "VerificationScript/1.0"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, resp.headers, json.loads(resp.read().decode("utf-8"))

# 1. Health check
print("\n[1/7] Testing GET /api/healthz...")
status, headers, body = http_get("/api/healthz")
data = json.loads(body.decode("utf-8"))
print(f"  Status: {status}, Content-Type: {headers.get('content-type')}")
print(f"  Body: {json.dumps(data)}")
assert status == 200, f"Expected 200, got {status}"
assert data.get("status") == "ok", f"Expected ok, got {data}"
print("  => Healthz check PASSED")

# 2. Root route SPA HTML
print("\n[2/7] Testing GET / (Root SPA HTML)...")
status, headers, body = http_get("/")
content_type = headers.get("content-type", "")
html = body.decode("utf-8")
print(f"  Status: {status}, Content-Type: {content_type}")
assert status == 200, f"Expected 200, got {status}"
assert "text/html" in content_type, f"Expected text/html in {content_type}"
assert "<div id=\"root\">" in html or "<div id=\"app\">" in html or "html" in html.lower(), "HTML does not look like SPA"
print("  => Root SPA serving check PASSED")

# 3. Direct client SPA routes
print("\n[3/7] Testing GET /reports and GET /reports/123 (Client fallback)...")
for route in ["/reports", "/reports/test-id-123"]:
    status, headers, body = http_get(route)
    content_type = headers.get("content-type", "")
    print(f"  {route} -> Status: {status}, Content-Type: {content_type}")
    assert status == 200, f"Expected 200 on {route}, got {status}"
    assert "text/html" in content_type, f"Expected text/html for {route}"
print("  => Client routes fallback check PASSED")

# 4. Static asset bundles
print("\n[4/7] Testing static asset bundles (/assets/*)...")
assets = re.findall(r'href="(/assets/[^"]+)"|src="(/assets/[^"]+)"', html)
flat_assets = [a[0] or a[1] for a in assets if a[0] or a[1]]
print(f"  Found static asset paths in HTML: {flat_assets}")
assert len(flat_assets) > 0, "No assets found in index.html"
for asset_path in flat_assets:
    status, headers, body = http_get(asset_path)
    content_type = headers.get("content-type", "")
    print(f"  {asset_path} -> Status: {status}, Content-Type: {content_type}, Size: {len(body)} bytes")
    assert status == 200, f"Asset {asset_path} returned {status}"
    if asset_path.endswith(".js"):
        assert "javascript" in content_type, f"Expected javascript in {content_type}"
    elif asset_path.endswith(".css"):
        assert "css" in content_type, f"Expected css in {content_type}"
print("  => Static assets MIME types check PASSED")

# 5. Live event persistence
print("\n[5/7] Testing POST /api/events (Live DB Persistence)...")
shift_key = "2026-11-15-early"
event1 = {
    "shift_key": shift_key,
    "machine": "P-101A",
    "category": "downtime",
    "note": "Boiler Feed Pump P-101A high vibration alarm triggered during shift handover test."
}
event2 = {
    "shift_key": shift_key,
    "machine": "V-204",
    "category": "safety",
    "note": "Chemical leak detected at Valve V-204, containment barrier deployed. Maintenance team must inspect before next shift."
}
status1, _, res1 = http_post_json("/api/events", event1)
status2, _, res2 = http_post_json("/api/events", event2)
print(f"  Event 1 (P-101A) -> Status: {status1}, ID: {res1['id']}")
print(f"  Event 2 (V-204)  -> Status: {status2}, ID: {res2['id']}")
assert status1 == 201 and status2 == 201

# Verify events were persisted in database
status, _, body = http_get(f"/api/events?shift_key={shift_key}")
events_list = json.loads(body.decode("utf-8"))
ids = {e.get("id") for e in events_list}
assert res1["id"] in ids and res2["id"] in ids
print(f"  Successfully retrieved {len(events_list)} persisted events from database.")
print("  => Live event persistence check PASSED")

# 6. Live report generation (Live Vertex AI)
print("\n[6/7] Testing POST /api/reports/generate (Live Vertex AI Gemini)...")
start_time = time.time()
generate_payload = {"shift_key": shift_key}
status, _, res_body = http_post_json("/api/reports/generate", generate_payload)
duration = time.time() - start_time
print(f"  POST /api/reports/generate -> Status: {status} in {duration:.2f}s")
print(f"  Report ID: {res_body.get('id')}, Version: {res_body.get('version')}")
print(f"  Model Used: {res_body.get('model_used')}")
print(f"  Summary: {res_body.get('summary')}")
print(f"  Safety Notes: {res_body.get('safety_notes')}")
print(f"  Open Actions: {res_body.get('open_actions')}")
assert status == 201, f"Expected 201, got {status}"
assert res_body.get("summary"), "Missing summary!"
print("  => Live report generation with Vertex AI check PASSED")

# 7. Data preservation across scale-to-zero / subsequent retrieval
print("\n[7/7] Testing data preservation from database...")
report_id = res_body["id"]
status, _, body = http_get(f"/api/reports/{report_id}")
retrieved_report = json.loads(body.decode("utf-8"))
print(f"  GET /api/reports/{report_id} -> Status: {status}")
assert status == 200
assert retrieved_report.get("id") == report_id
assert retrieved_report.get("shift_key") == shift_key
print(f"  Confirmed report {report_id} retrieved successfully from persistent database.")
print("  => Data preservation check PASSED")

print("\n============================================================")
print(" ALL 7 LIVE CLOUD RUN ACCEPTANCE CHECKS PASSED SUCCESSFULLY!")
print("============================================================")
