#!/usr/bin/env bash
# ==============================================================================
# 08-observability-stack.sh - Provision Standalone Observability Host on GCP
# Idempotent: creates or updates GCE VM instance & firewall rule in europe-west2.
# Observability stack runs OpenTelemetry Collector, Prometheus, Loki, Tempo, Grafana.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
OBSERVABILITY_DIR="${ROOT_DIR}/observability"

PROJECT_ID="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${GCP_REGION:-europe-west2}"
ZONE="${GCP_ZONE:-europe-west2-a}"
VM_NAME="${VM_NAME:-handover-observability}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-medium}"
IMAGE_FAMILY="${IMAGE_FAMILY:-ubuntu-2404-lts-amd64}"
if [[ "${IMAGE_FAMILY}" == "ubuntu-2404-lts" ]]; then
  IMAGE_FAMILY="ubuntu-2404-lts-amd64"
fi
IMAGE_PROJECT="${IMAGE_PROJECT:-ubuntu-os-cloud}"
NETWORK="${NETWORK:-default}"
SUBNET="${SUBNET:-default}"
TAGS="observability-stack,http-server,https-server"
FIREWALL_RULE="allow-observability-ingress"

if [[ -z "${PROJECT_ID}" ]]; then
  echo "ERROR: GCP_PROJECT is not set and could not be determined from gcloud config." >&2
  exit 1
fi

echo "=========================================================================="
echo " Provisioning Standalone Observability Host on GCP"
echo " Project:      ${PROJECT_ID}"
echo " Region/Zone:  ${REGION} / ${ZONE}"
echo " VM Instance:  ${VM_NAME} (${MACHINE_TYPE})"
echo " Image Family: ${IMAGE_FAMILY} (${IMAGE_PROJECT})"
echo " Network/Sub:  ${NETWORK} / ${SUBNET}"
echo "=========================================================================="

# 1. Firewall Rule: allow-observability-ingress
echo "==> [1/4] Ensuring firewall rule '${FIREWALL_RULE}'..."
if gcloud compute firewall-rules describe "${FIREWALL_RULE}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Firewall rule '${FIREWALL_RULE}' exists. Updating rules..."
  gcloud compute firewall-rules update "${FIREWALL_RULE}" \
    --project="${PROJECT_ID}" \
    --allow=tcp:3000,tcp:4317,tcp:4318,tcp:9090,tcp:3100,tcp:3200,tcp:13133 \
    --target-tags=observability-stack
else
  echo "Creating firewall rule '${FIREWALL_RULE}'..."
  gcloud compute firewall-rules create "${FIREWALL_RULE}" \
    --project="${PROJECT_ID}" \
    --network="${NETWORK}" \
    --allow=tcp:3000,tcp:4317,tcp:4318,tcp:9090,tcp:3100,tcp:3200,tcp:13133 \
    --target-tags=observability-stack \
    --source-ranges="0.0.0.0/0" \
    --description="Allow inbound traffic for observability stack (Grafana, OTLP, Prometheus, Loki, Tempo, health)"
fi

# 2. Build Startup Script
echo "==> [2/4] Assembling VM startup script..."
STARTUP_SCRIPT="$(mktemp)"
trap 'rm -f "${STARTUP_SCRIPT}"' EXIT

cat <<'STARTUP_HEAD' > "${STARTUP_SCRIPT}"
#!/usr/bin/env bash
set -euo pipefail

echo "==> [Observability Startup] Bootstrapping standalone observability host..."
mkdir -p /opt/observability/dashboards

# Wait for any background apt operations to complete
while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || fuser /var/lib/apt/lists/lock >/dev/null 2>&1; do
  echo "Waiting for package manager lock..."
  sleep 3
done

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl gnupg

# Set up Docker official repository
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list

apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin || apt-get install -y docker.io docker-compose-v2

systemctl enable --now docker

echo "==> [Observability Startup] Writing configuration files to /opt/observability..."
STARTUP_HEAD

# Embed configuration files
CONFIG_FILES=(
  "docker-compose.yml"
  "otel-collector-config.yaml"
  "prometheus.yml"
  "loki-config.yaml"
  "tempo-config.yaml"
  "datasources.yaml"
  "dashboards.yaml"
  "dashboards/application-metrics.json"
)

for rel in "${CONFIG_FILES[@]}"; do
  full_path="${OBSERVABILITY_DIR}/${rel}"
  if [[ ! -f "${full_path}" ]]; then
    echo "ERROR: Required observability config file '${full_path}' not found!" >&2
    exit 1
  fi
  cat <<EMBED_HEADER >> "${STARTUP_SCRIPT}"
cat <<'EOF' > "/opt/observability/${rel}"
EMBED_HEADER
  cat "${full_path}" >> "${STARTUP_SCRIPT}"
  echo "" >> "${STARTUP_SCRIPT}"
  echo "EOF" >> "${STARTUP_SCRIPT}"
done

cat <<'STARTUP_TAIL' >> "${STARTUP_SCRIPT}"
chmod -R 755 /opt/observability

echo "==> [Observability Startup] Starting containers via Docker Compose..."
cd /opt/observability
docker compose -f /opt/observability/docker-compose.yml up -d

# Create systemd persistence service
cat <<'SERVICE_EOF' > /etc/systemd/system/observability-stack.service
[Unit]
Description=Handover Observability Stack
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/observability
ExecStart=/usr/bin/docker compose -f /opt/observability/docker-compose.yml up -d
ExecStop=/usr/bin/docker compose -f /opt/observability/docker-compose.yml down

[Install]
WantedBy=multi-user.target
SERVICE_EOF

systemctl daemon-reload
systemctl enable observability-stack.service

echo "==> [Observability Startup] Observability stack bootstrap completed successfully."
STARTUP_TAIL

# 3. Create or Update GCE VM Instance
echo "==> [3/4] Ensuring Compute Engine instance '${VM_NAME}' in zone '${ZONE}'..."
INSTANCE_EXISTS=false
if gcloud compute instances describe "${VM_NAME}" --zone="${ZONE}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  INSTANCE_EXISTS=true
fi

if [[ "${INSTANCE_EXISTS}" == "false" ]]; then
  echo "Creating instance '${VM_NAME}'..."
  gcloud compute instances create "${VM_NAME}" \
    --project="${PROJECT_ID}" \
    --zone="${ZONE}" \
    --machine-type="${MACHINE_TYPE}" \
    --image-family="${IMAGE_FAMILY}" \
    --image-project="${IMAGE_PROJECT}" \
    --network="${NETWORK}" \
    --subnet="${SUBNET}" \
    --tags="${TAGS}" \
    --metadata-from-file="startup-script=${STARTUP_SCRIPT}"
else
  STATUS="$(gcloud compute instances describe "${VM_NAME}" --zone="${ZONE}" --project="${PROJECT_ID}" --format='value(status)')"
  echo "Instance '${VM_NAME}' exists with status: ${STATUS}."
  if [[ "${STATUS}" == "TERMINATED" || "${STATUS}" == "STOPPED" ]]; then
    echo "Starting instance '${VM_NAME}'..."
    gcloud compute instances start "${VM_NAME}" --zone="${ZONE}" --project="${PROJECT_ID}"
  fi
  echo "Updating startup-script metadata..."
  gcloud compute instances add-metadata "${VM_NAME}" \
    --zone="${ZONE}" \
    --project="${PROJECT_ID}" \
    --metadata-from-file="startup-script=${STARTUP_SCRIPT}"
fi

INTERNAL_IP="$(gcloud compute instances describe "${VM_NAME}" --zone="${ZONE}" --project="${PROJECT_ID}" --format='value(networkInterfaces[0].networkIP)')"
EXTERNAL_IP="$(gcloud compute instances describe "${VM_NAME}" --zone="${ZONE}" --project="${PROJECT_ID}" --format='value(networkInterfaces[0].accessConfigs[0].natIP)')"

echo "Instance '${VM_NAME}' active:"
echo "  Internal IP: ${INTERNAL_IP}"
echo "  External IP: ${EXTERNAL_IP}"

# 4. Wait for Endpoints to become Healthy
echo "==> [4/4] Verifying health endpoints on http://${EXTERNAL_IP}..."

ENDPOINTS=(
  "OTel Collector:http://${EXTERNAL_IP}:13133/"
  "Prometheus:http://${EXTERNAL_IP}:9090/-/ready"
  "Loki:http://${EXTERNAL_IP}:3100/ready"
  "Tempo:http://${EXTERNAL_IP}:3200/ready"
  "Grafana:http://${EXTERNAL_IP}:3000/api/health"
)

MAX_RETRIES=40
INTERVAL=10

for item in "${ENDPOINTS[@]}"; do
  NAME="${item%%:*}"
  URL="${item#*:}"
  echo "Checking ${NAME} at ${URL}..."

  READY=false
  for ((i=1; i<=MAX_RETRIES; i++)); do
    HTTP_CODE="$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "${URL}" 2>/dev/null || echo "000")"
    if [[ "${HTTP_CODE}" == "200" ]]; then
      echo "  ✅ ${NAME} is healthy (HTTP 200)."
      READY=true
      break
    fi
    echo "  [Attempt ${i}/${MAX_RETRIES}] Waiting for ${NAME}... (HTTP ${HTTP_CODE})"
    sleep "${INTERVAL}"
  done

  if [[ "${READY}" != "true" ]]; then
    echo "ERROR: ${NAME} failed to become healthy within timeout!" >&2
    exit 1
  fi
done

echo "=========================================================================="
echo " Observability Stack Deployed and Verified Successfully!"
echo " Internal IP (Direct VPC Egress): http://${INTERNAL_IP}:4318"
echo " External IP:                     ${EXTERNAL_IP}"
echo " Grafana Dashboard:               http://${EXTERNAL_IP}:3000/d/handover-app-metrics/shift-handover-application-metrics"
echo " Prometheus UI:                   http://${EXTERNAL_IP}:9090"
echo "=========================================================================="
