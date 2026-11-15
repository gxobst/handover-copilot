# 05-database.ps1 - Provision Database Persistence
$ErrorActionPreference = "Stop"
$ProjectId = if ($env:GCP_PROJECT) { $env:GCP_PROJECT } else { (gcloud.cmd config get-value project) }
$Region = if ($env:GCP_REGION) { $env:GCP_REGION } else { "europe-west2" }
$Instance = if ($env:DB_INSTANCE) { $env:DB_INSTANCE } else { "handover-db" }
$DbName = if ($env:DB_NAME) { $env:DB_NAME } else { "handover" }
$DbPass = if ($env:DB_PASSWORD) { $env:DB_PASSWORD } else { "Yg0vCNCSfVTNpicWso_EBwDqvk4Vd9V1" }

$exists = & gcloud.cmd sql instances describe $Instance --project=$ProjectId 2>$null
if (-not $exists) {
    Write-Host "Creating Cloud SQL PostgreSQL instance $Instance in $Region..."
    & gcloud.cmd sql instances create $Instance `
      --database-version="POSTGRES_16" `
      --tier="db-f1-micro" `
      --edition="ENTERPRISE" `
      --region=$Region `
      --storage-size="10GB" `
      --storage-auto-increase `
      --root-password=$DbPass `
      --project=$ProjectId
}

Write-Host "Waiting for instance $Instance to be RUNNABLE..."
while ($true) {
    $state = (& gcloud.cmd sql instances describe $Instance --project=$ProjectId --format="value(state)" 2>$null)
    Write-Host "State: $state"
    if ($state -eq "RUNNABLE") { break }
    Start-Sleep -Seconds 10
}

$dbExists = & gcloud.cmd sql databases describe $DbName --instance=$Instance --project=$ProjectId 2>$null
if (-not $dbExists) {
    Write-Host "Creating database $DbName..."
    & gcloud.cmd sql databases create $DbName --instance=$Instance --project=$ProjectId
}

$connectionName = "$ProjectId`:$Region`:$Instance"
$databaseUrl = "postgresql+psycopg://postgres:$DbPass@/$DbName`?host=/cloudsql/$connectionName"
Write-Host "Updating DATABASE_URL secret..."
$databaseUrl | & gcloud.cmd secrets versions add "DATABASE_URL" --data-file=- --project=$ProjectId | Out-Null
Write-Host "==> Database $DbName configured."
