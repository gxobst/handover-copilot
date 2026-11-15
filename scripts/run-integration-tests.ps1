param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [int]$TimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"

Write-Host "================================================================="
Write-Host "Starting Shift Handover Copilot Integration Test Orchestration"
Write-Host "================================================================="

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $scriptDir

Set-Location $rootDir

$exitCode = 0

try {
    Write-Host "[Orchestrator] Building and starting Docker Compose stack..."
    docker compose up -d --build
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to start docker compose stack (exit code $LASTEXITCODE)"
    }

    Write-Host "[Orchestrator] Polling $BaseUrl/api/healthz for healthy status (timeout: ${TimeoutSeconds}s)..."
    $startTime = Get-Date
    $isHealthy = $false

    while (((Get-Date) - $startTime).TotalSeconds -lt $TimeoutSeconds) {
        try {
            $health = Invoke-RestMethod -Uri "$BaseUrl/api/healthz" -TimeoutSec 2 -ErrorAction SilentlyContinue
            if ($health.status -eq "ok") {
                $isHealthy = $true
                Write-Host "[Orchestrator] Container is healthy! Status: $($health.status), Env: $($health.environment)"
                break
            }
        }
        catch {
            # Retry until timeout
        }
        Start-Sleep -Seconds 2
    }

    if (-not $isHealthy) {
        docker compose logs
        throw "Container failed to become healthy within $TimeoutSeconds seconds"
    }

    Write-Host "[Orchestrator] Executing integration test suite against $BaseUrl..."
    python scripts/test_compose_integration.py --base-url $BaseUrl
    $exitCode = $LASTEXITCODE

    if ($exitCode -ne 0) {
        throw "Integration tests failed with exit code $exitCode"
    }

    Write-Host "================================================================="
    Write-Host "All integration test scenarios passed successfully!"
    Write-Host "================================================================="
}
catch {
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    $exitCode = 1
}
finally {
    Write-Host "[Orchestrator] Tearing down Docker Compose stack (docker compose down -v)..."
    docker compose down -v
}

exit $exitCode
