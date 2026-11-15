param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [int]$TimeoutSeconds = 60,
    [switch]$NoTeardown
)

$ErrorActionPreference = "Stop"

Write-Host "================================================================="
Write-Host "Starting Shift Handover Copilot End-to-End Test Orchestration"
Write-Host "================================================================="

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $scriptDir

Set-Location $rootDir

$exitCode = 0
$startedByScript = $false

function Check-Health {
    param([string]$Url)
    try {
        $health = Invoke-RestMethod -Uri "$Url/api/healthz" -TimeoutSec 2 -ErrorAction SilentlyContinue
        return ($health.status -eq "ok")
    }
    catch {
        return $false
    }
}

try {
    # 1. Verify if Docker Compose stack is already running and healthy
    Write-Host "[E2E Orchestrator] Checking if container stack is already healthy at $BaseUrl..."
    $alreadyHealthy = Check-Health -Url $BaseUrl

    if ($alreadyHealthy) {
        Write-Host "[E2E Orchestrator] Container stack is already running and healthy."
    }
    else {
        Write-Host "[E2E Orchestrator] Building and starting Docker Compose stack (docker compose up -d --build)..."
        docker compose up -d --build
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to start docker compose stack (exit code $LASTEXITCODE)"
        }
        $startedByScript = $true

        Write-Host "[E2E Orchestrator] Polling $BaseUrl/api/healthz for healthy status (timeout: ${TimeoutSeconds}s)..."
        $startTime = Get-Date
        $isHealthy = $false

        while (((Get-Date) - $startTime).TotalSeconds -lt $TimeoutSeconds) {
            if (Check-Health -Url $BaseUrl) {
                $isHealthy = $true
                Write-Host "[E2E Orchestrator] Container is healthy!"
                break
            }
            Start-Sleep -Seconds 2
        }

        if (-not $isHealthy) {
            docker compose logs
            throw "Container failed to become healthy within $TimeoutSeconds seconds"
        }
    }

    # 2. Run Playwright end-to-end test suite
    Write-Host "[E2E Orchestrator] Running Playwright E2E test suite targeting $BaseUrl..."
    $env:BASE_URL = $BaseUrl

    npx playwright test -c e2e/playwright.config.ts
    $exitCode = $LASTEXITCODE

    if ($exitCode -ne 0) {
        throw "Playwright E2E tests failed with exit code $exitCode"
    }

    Write-Host "================================================================="
    Write-Host "All Playwright end-to-end test journeys passed successfully!"
    Write-Host "================================================================="
}
catch {
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    $exitCode = 1
}
finally {
    if ($startedByScript -and -not $NoTeardown) {
        Write-Host "[E2E Orchestrator] Tearing down Docker Compose stack (docker compose down -v)..."
        docker compose down -v
    }
    elseif ($NoTeardown) {
        Write-Host "[E2E Orchestrator] Skipping teardown (--NoTeardown flag active)."
    }
}

exit $exitCode
