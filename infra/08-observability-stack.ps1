# ==============================================================================
# 08-observability-stack.ps1 - Provision Standalone Observability Host on GCP
# Idempotent: creates or updates GCE VM instance & firewall rule in europe-west2.
# Observability stack runs OpenTelemetry Collector, Prometheus, Loki, Tempo, Grafana.
# ==============================================================================
[CmdletBinding()]
param(
    [string]$ProjectId = $env:GCP_PROJECT,
    [string]$Region = "europe-west2",
    [string]$Zone = "europe-west2-a",
    [string]$VmName = "handover-observability",
    [string]$MachineType = "e2-medium",
    [string]$ImageFamily = "ubuntu-2404-lts-amd64",
    [string]$ImageProject = "ubuntu-os-cloud",
    [string]$Network = "default",
    [string]$Subnet = "default"
)

$ErrorActionPreference = "Stop"

$gcloudCmd = if (Get-Command "gcloud.cmd" -ErrorAction SilentlyContinue) { "gcloud.cmd" } else { "gcloud" }

if (-not $ProjectId) {
    $ProjectId = (& $gcloudCmd config get-value project 2>$null).Trim()
}
if (-not $ProjectId) {
    Write-Error "ERROR: ProjectId is required and could not be determined from gcloud config."
}

if ($ImageFamily -eq "ubuntu-2404-lts") {
    $ImageFamily = "ubuntu-2404-lts-amd64"
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
$ObservabilityDir = Join-Path $RootDir "observability"
$FirewallRule = "allow-observability-ingress"
$Tags = "observability-stack,http-server,https-server"

Write-Host "=========================================================================="
Write-Host " Provisioning Standalone Observability Host on GCP"
Write-Host " Project:      $ProjectId"
Write-Host " Region/Zone:  $Region / $Zone"
Write-Host " VM Instance:  $VmName ($MachineType)"
Write-Host " Image Family: $ImageFamily ($ImageProject)"
Write-Host " Network/Sub:  $Network / $Subnet"
Write-Host "=========================================================================="

# 1. Firewall Rule: allow-observability-ingress
Write-Host "==> [1/4] Ensuring firewall rule '$FirewallRule'..."
$prevEA = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
& $gcloudCmd compute firewall-rules describe $FirewallRule --project=$ProjectId 2>&1 | Out-Null
$fwExists = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $prevEA

if ($fwExists) {
    Write-Host "Firewall rule '$FirewallRule' exists. Updating rules..."
    & $gcloudCmd compute firewall-rules update $FirewallRule `
        --project=$ProjectId `
        --allow="tcp:3000,tcp:4317,tcp:4318,tcp:9090,tcp:3100,tcp:3200,tcp:13133" `
        --target-tags="observability-stack"
} else {
    Write-Host "Creating firewall rule '$FirewallRule'..."
    & $gcloudCmd compute firewall-rules create $FirewallRule `
        --project=$ProjectId `
        --network=$Network `
        --allow="tcp:3000,tcp:4317,tcp:4318,tcp:9090,tcp:3100,tcp:3200,tcp:13133" `
        --target-tags="observability-stack" `
        --source-ranges="0.0.0.0/0" `
        --description="Allow inbound traffic for observability stack (Grafana, OTLP, Prometheus, Loki, Tempo, health)"
}

# 2. Build Startup Script
Write-Host "==> [2/4] Assembling VM startup script..."
$tempStartup = [System.IO.Path]::GetTempFileName()

$startupScript = @'
#!/usr/bin/env bash
set -euo pipefail

echo "==> [Observability Startup] Bootstrapping standalone observability host..."
mkdir -p /opt/observability/dashboards

while fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || fuser /var/lib/apt/lists/lock >/dev/null 2>&1; do
  echo "Waiting for package manager lock..."
  sleep 3
done

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y ca-certificates curl gnupg

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
'@

$configFiles = @(
    "docker-compose.yml",
    "otel-collector-config.yaml",
    "prometheus.yml",
    "loki-config.yaml",
    "tempo-config.yaml",
    "datasources.yaml",
    "dashboards.yaml",
    "dashboards/application-metrics.json"
)

foreach ($rel in $configFiles) {
    $fullPath = Join-Path $ObservabilityDir $rel
    if (-not (Test-Path $fullPath)) {
        Write-Error "ERROR: Required observability config file '$fullPath' not found!"
    }
    $fileContent = [System.IO.File]::ReadAllText($fullPath)
    # Ensure unix line endings
    $fileContent = $fileContent -replace "`r`n", "`n"
    $startupScript += "`ncat <<'EOF' > `"/opt/observability/$rel`"`n"
    $startupScript += $fileContent
    $startupScript += "`nEOF`n"
}

$startupScript += @'
chmod -R 755 /opt/observability

echo "==> [Observability Startup] Starting containers via Docker Compose..."
cd /opt/observability
docker compose -f /opt/observability/docker-compose.yml up -d

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
'@

# Ensure unix line endings for the entire startup script
$startupScript = $startupScript -replace "`r`n", "`n"
[System.IO.File]::WriteAllText($tempStartup, $startupScript, [System.Text.Encoding]::UTF8)

# 3. Create or Update GCE VM Instance
Write-Host "==> [3/4] Ensuring Compute Engine instance '$VmName' in zone '$Zone'..."
$prevEA = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
& $gcloudCmd compute instances describe $VmName --zone=$Zone --project=$ProjectId 2>&1 | Out-Null
$vmExists = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $prevEA

if (-not $vmExists) {
    Write-Host "Creating instance '$VmName'..."
    & $gcloudCmd compute instances create $VmName `
        --project=$ProjectId `
        --zone=$Zone `
        --machine-type=$MachineType `
        --image-family=$ImageFamily `
        --image-project=$ImageProject `
        --network=$Network `
        --subnet=$Subnet `
        --tags=$Tags `
        --metadata-from-file="startup-script=$tempStartup"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to create instance $VmName"
    }
} else {
    $status = (& $gcloudCmd compute instances describe $VmName --zone=$Zone --project=$ProjectId --format="value(status)").Trim()
    Write-Host "Instance '$VmName' exists with status: $status."
    if ($status -eq "TERMINATED" -or $status -eq "STOPPED") {
        Write-Host "Starting instance '$VmName'..."
        & $gcloudCmd compute instances start $VmName --zone=$Zone --project=$ProjectId
    }
    Write-Host "Updating startup-script metadata..."
    & $gcloudCmd compute instances add-metadata $VmName `
        --zone=$Zone `
        --project=$ProjectId `
        --metadata-from-file="startup-script=$tempStartup"
}

Remove-Item -Path $tempStartup -Force -ErrorAction SilentlyContinue

$internalIp = (& $gcloudCmd compute instances describe $VmName --zone=$Zone --project=$ProjectId --format="value(networkInterfaces[0].networkIP)").Trim()
$externalIp = (& $gcloudCmd compute instances describe $VmName --zone=$Zone --project=$ProjectId --format="value(networkInterfaces[0].accessConfigs[0].natIP)").Trim()

Write-Host "Instance '$VmName' active:"
Write-Host "  Internal IP: $internalIp"
Write-Host "  External IP: $externalIp"

# 4. Wait for Endpoints to become Healthy
Write-Host "==> [4/4] Verifying health endpoints on http://${externalIp}..."

$endpoints = @(
    @{ Name = "OTel Collector"; Url = "http://${externalIp}:13133/" },
    @{ Name = "Prometheus"; Url = "http://${externalIp}:9090/-/ready" },
    @{ Name = "Loki"; Url = "http://${externalIp}:3100/ready" },
    @{ Name = "Tempo"; Url = "http://${externalIp}:3200/ready" },
    @{ Name = "Grafana"; Url = "http://${externalIp}:3000/api/health" }
)

$maxRetries = 40
$intervalSec = 10

foreach ($ep in $endpoints) {
    Write-Host "Checking $($ep.Name) at $($ep.Url)..."
    $ready = $false
    for ($i = 1; $i -le $maxRetries; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri $ep.Url -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
            if ($resp.StatusCode -eq 200) {
                Write-Host "  $($ep.Name) is healthy (HTTP 200)."
                $ready = $true
                break
            }
        } catch {
            $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
            Write-Host "  [Attempt $i/$maxRetries] Waiting for $($ep.Name)... (HTTP $code)"
        }
        Start-Sleep -Seconds $intervalSec
    }
    if (-not $ready) {
        Write-Error "ERROR: $($ep.Name) failed to become healthy within timeout!"
    }
}

Write-Host "=========================================================================="
Write-Host " Observability Stack Deployed and Verified Successfully!"
Write-Host " Internal IP (Direct VPC Egress): http://${internalIp}:4318"
Write-Host " External IP:                     $externalIp"
Write-Host " Grafana Dashboard:               http://${externalIp}:3000/d/handover-app-metrics/shift-handover-application-metrics"
Write-Host " Prometheus UI:                   http://${externalIp}:9090"
Write-Host "=========================================================================="
