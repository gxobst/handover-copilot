<#
.SYNOPSIS
    Starts Shift Handover Copilot (FastAPI backend + Vite React frontend).

.DESCRIPTION
    Launches the backend on http://127.0.0.1:8000 and the frontend on http://localhost:5173.
    Provides automatic health checking, graceful termination on exit, and browser launch.

.PARAMETER Mock
    Runs frontend in standalone offline mock mode (without launching backend).

.PARAMETER NoBrowser
    Prevents automatically opening the application in the default web browser.

.PARAMETER BackendPort
    Port for the FastAPI backend (defaults to 8000).

.PARAMETER FrontendPort
    Port for the Vite frontend (defaults to 5173).

.EXAMPLE
    .\start.ps1
    .\start.ps1 -Mock
    .\start.ps1 -NoBrowser
#>

[CmdletBinding()]
param (
    [switch]$Mock,
    [switch]$NoBrowser,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$BackendDir = Join-Path $ScriptDir "backend"
$FrontendDir = Join-Path $ScriptDir "frontend"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "       SHIFT HANDOVER COPILOT - INDUSTRIAL LAUNCHER       " -ForegroundColor Yellow
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Verify Prerequisites
if (-not $Mock) {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Error "uv command not found. Please install uv (https://docs.astral.sh/uv/) to run the backend."
        exit 1
    }
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Error "npm command not found. Please install Node.js (v18+) to run the frontend."
    exit 1
}

# 2. Start Backend (if not in mock mode)
$backendJob = $null
$backendProcess = $null

if (-not $Mock) {
    Write-Host "`n[1/3] Starting FastAPI Backend on http://127.0.0.1:$BackendPort..." -ForegroundColor Green
    
    $backendCmd = "cd '$BackendDir'; uv run uvicorn app.main:app --host 127.0.0.1 --port $BackendPort"
    $backendProcess = Start-Process powershell -ArgumentList "-NoLogo", "-NoProfile", "-Command", "$backendCmd" -PassThru -WindowStyle Hidden

    # Poll health endpoint
    $healthUrl = "http://127.0.0.1:$BackendPort/api/healthz"
    $maxRetries = 20
    $retry = 0
    $backendReady = $false

    Write-Host "Waiting for backend health check ($healthUrl)..." -NoNewline
    while ($retry -lt $maxRetries) {
        Start-Sleep -Milliseconds 800
        try {
            $resp = Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 2 -ErrorAction Stop
            if ($resp.status -eq 'ok') {
                $backendReady = $true
                break
            }
        } catch {
            Write-Host "." -NoNewline
            $retry++
        }
    }

    if ($backendReady) {
        Write-Host " READY!" -ForegroundColor Green
    } else {
        Write-Host " TIMEOUT!" -ForegroundColor Red
        Write-Warning "Backend did not report ready in time. Proceeding anyway..."
    }
} else {
    Write-Host "`n[1/3] Running in Mock Mode (-Mock enabled). Skipping backend." -ForegroundColor Yellow
}

# 3. Start Frontend
Write-Host "`n[2/3] Starting Vite Frontend on http://localhost:$FrontendPort..." -ForegroundColor Green

# Set environment variable for mock mode if requested
if ($Mock) {
    $env:VITE_API_MODE = "mock"
} else {
    $env:VITE_API_MODE = "real"
}

$frontendCmd = "cd '$FrontendDir'; npm run dev -- --port $FrontendPort"
$frontendProcess = Start-Process powershell -ArgumentList "-NoLogo", "-NoProfile", "-Command", "$frontendCmd" -PassThru -WindowStyle Hidden

# Poll frontend readiness
$frontendUrl = "http://localhost:$FrontendPort"
$maxRetries = 15
$retry = 0
$frontendReady = $false

Write-Host "Waiting for frontend server ($frontendUrl)..." -NoNewline
while ($retry -lt $maxRetries) {
    Start-Sleep -Milliseconds 600
    try {
        $resp = Invoke-WebRequest -Uri $frontendUrl -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            $frontendReady = $true
            break
        }
    } catch {
        Write-Host "." -NoNewline
        $retry++
    }
}

if ($frontendReady) {
    Write-Host " READY!" -ForegroundColor Green
} else {
    Write-Host " TIMEOUT!" -ForegroundColor Yellow
}

# 4. Launch Browser
Write-Host "`n[3/3] Application status:" -ForegroundColor Cyan
Write-Host "  -> Frontend Dashboard: $frontendUrl" -ForegroundColor White
if (-not $Mock) {
    Write-Host "  -> Backend API:        http://127.0.0.1:$BackendPort/api" -ForegroundColor White
    Write-Host "  -> Swagger Docs:       http://127.0.0.1:$BackendPort/docs" -ForegroundColor White
}

if (-not $NoBrowser) {
    Write-Host "`nLaunching web browser..." -ForegroundColor Cyan
    Start-Process $frontendUrl
}

Write-Host "`nPress Ctrl+C to stop all servers and exit.`n" -ForegroundColor Yellow

# 5. Monitor and graceful termination
try {
    while ($true) {
        Start-Sleep -Seconds 1
        if ($frontendProcess -and $frontendProcess.HasExited) {
            Write-Host "Frontend process exited." -ForegroundColor Yellow
            break
        }
        if ($backendProcess -and $backendProcess.HasExited) {
            Write-Host "Backend process exited." -ForegroundColor Yellow
            break
        }
    }
} finally {
    Write-Host "`nShutting down servers..." -ForegroundColor Cyan
    if ($frontendProcess -and -not $frontendProcess.HasExited) {
        Stop-Process -Id $frontendProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($backendProcess -and -not $backendProcess.HasExited) {
        Stop-Process -Id $backendProcess.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "All processes stopped. Have a safe shift!" -ForegroundColor Green
}
