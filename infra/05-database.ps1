# ==============================================================================
# 05-database.ps1 - Provision AlloyDB Express Database Persistence in europe-west2
# Matches plan.md §6 & §14: AlloyDB cluster with scale-to-zero compute (PostgreSQL 18).
# Idempotent: safe to run multiple times.
# ==============================================================================
[CmdletBinding()]
param(
    [string]$ProjectId = $env:GCP_PROJECT,
    [string]$Region = "europe-west2",
    [string]$ClusterId = "handover-cluster",
    [string]$InstanceId = "handover-primary",
    [string]$DbPassword = "Yg0vCNCSfVTNpicWso_EBwDqvk4Vd9V1"
)

$ErrorActionPreference = "Stop"

if (-not $ProjectId) {
    $ProjectId = & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" config get-value project 2>$null
}
if (-not $ProjectId) {
    Write-Error "ERROR: ProjectId is required and could not be determined from gcloud config."
}

Write-Host "==> Configuring AlloyDB persistence in '$Region' (project: $ProjectId)..."

# Check if cluster exists
$clusterCheck = & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" alloydb clusters describe $ClusterId --region=$Region --project=$ProjectId 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "AlloyDB cluster '$ClusterId' already exists."
} else {
    Write-Host "Creating AlloyDB cluster '$ClusterId' (PostgreSQL 18) with Private Service Connect..."
    & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" alloydb clusters create $ClusterId `
        --region=$Region `
        --project=$ProjectId `
        --password=$DbPassword `
        --database-version="POSTGRES_18" `
        --enable-private-service-connect
}

# Check if primary instance exists
$instCheck = & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" alloydb instances describe $InstanceId --cluster=$ClusterId --region=$Region --project=$ProjectId 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "AlloyDB primary instance '$InstanceId' already exists."
} else {
    Write-Host "Creating AlloyDB primary instance '$InstanceId' (1 vCPU)..."
    & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" alloydb instances create $InstanceId `
        --cluster=$ClusterId `
        --region=$Region `
        --project=$ProjectId `
        --instance-type="PRIMARY" `
        --cpu-count=1
}

Write-Host "Waiting for AlloyDB primary instance '$InstanceId' to become READY..."
while ($true) {
    $state = & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" alloydb instances describe $InstanceId --cluster=$ClusterId --region=$Region --project=$ProjectId --format="value(state)" 2>$null
    Write-Host "Current instance state: $state"
    if ($state -eq "READY") {
        break
    }
    Start-Sleep -Seconds 15
}

# Ensure allowed PSC projects on instance
& "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" alloydb instances update $InstanceId `
    --cluster=$ClusterId `
    --region=$Region `
    --project=$ProjectId `
    --allowed-psc-projects=$ProjectId `
    --quiet 2>$null

$pscDns = & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" alloydb instances describe $InstanceId --cluster=$ClusterId --region=$Region --project=$ProjectId --format="value(pscInstanceConfig.pscDnsName)" 2>$null
Write-Host "AlloyDB instance '$InstanceId' is READY (PSC DNS: $pscDns)."

$saLink = & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" alloydb instances describe $InstanceId --cluster=$ClusterId --region=$Region --project=$ProjectId --format="value(pscInstanceConfig.serviceAttachmentLink)" 2>$null
$addrCheck = & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" compute addresses describe alloydb-psc-ip --region=$Region --project=$ProjectId 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Creating consumer PSC IP 'alloydb-psc-ip'..."
    & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" compute addresses create alloydb-psc-ip --region=$Region --subnet="default" --project=$ProjectId
}
$pscIp = (& "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" compute addresses describe alloydb-psc-ip --region=$Region --project=$ProjectId --format="value(address)").Trim()

$fwdCheck = & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" compute forwarding-rules describe alloydb-psc-forwarding-rule --region=$Region --project=$ProjectId 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Creating consumer PSC forwarding rule 'alloydb-psc-forwarding-rule'..."
    & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" compute forwarding-rules create alloydb-psc-forwarding-rule `
        --region=$Region `
        --network="default" `
        --address="alloydb-psc-ip" `
        --target-service-attachment=$saLink `
        --project=$ProjectId
}

& "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" services enable dns.googleapis.com --project=$ProjectId --quiet 2>$null
$zoneCheck = & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" dns managed-zones describe alloydb-psc-zone --project=$ProjectId 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Creating private Cloud DNS zone 'alloydb-psc-zone'..."
    & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" dns managed-zones create alloydb-psc-zone `
        --dns-name="alloydb-psc.goog." `
        --description="AlloyDB PSC Private Zone" `
        --visibility=private `
        --networks="default" `
        --project=$ProjectId
}

$recCheck = & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" dns record-sets list --zone=alloydb-psc-zone --project=$ProjectId --format="value(name)" 2>$null
if ($recCheck -notmatch [regex]::Escape($pscDns)) {
    Write-Host "Creating DNS record for $pscDns -> $pscIp..."
    & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" dns record-sets create $pscDns `
        --zone="alloydb-psc-zone" `
        --type="A" `
        --ttl=300 `
        --rrdatas=$pscIp `
        --project=$ProjectId
}

$hostName = if ($pscDns) { $pscDns } else { $pscIp }
$databaseUrlDev = "postgresql+psycopg://postgres:${DbPassword}@${hostName}:5432/handover_dev?sslmode=require"
$databaseUrlProd = "postgresql+psycopg://postgres:${DbPassword}@${hostName}:5432/handover_prod?sslmode=require"
$databaseUrl = $databaseUrlDev

function Update-SecretVersion($name, $val) {
    $tempFile = [System.IO.Path]::GetTempFileName()
    [System.IO.File]::WriteAllText($tempFile, $val)
    & "C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd" secrets versions add $name --data-file=$tempFile --project=$ProjectId 2>$null
    Remove-Item $tempFile -Force -ErrorAction SilentlyContinue
}

Write-Host "Updating database secrets in Secret Manager..."
Update-SecretVersion "DATABASE_URL_DEV" $databaseUrlDev
Update-SecretVersion "DATABASE_URL_PROD" $databaseUrlProd
Update-SecretVersion "DATABASE_URL" $databaseUrl

Write-Host "==> AlloyDB cluster '$ClusterId' / instance '$InstanceId' configured successfully."
