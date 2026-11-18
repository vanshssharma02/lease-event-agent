<#
.SYNOPSIS
  Developer task runner for lease-event-agent (Windows PowerShell).

.DESCRIPTION
  Automates testing, environment seeding, API launching, UI startup, and evaluation.

.EXAMPLE
  .\tasks.ps1 test
  .\tasks.ps1 smoke
  .\tasks.ps1 eval
  .\tasks.ps1 seed
  .\tasks.ps1 run
  .\tasks.ps1 api
  .\tasks.ps1 ui
  .\tasks.ps1 lint
#>

param (
    [Parameter(Position=0, Mandatory=$true)]
    [ValidateSet("test", "smoke", "eval", "seed", "run", "api", "ui", "lint", "clean", "help")]
    [string]$Task,

    [Parameter(Position=1, Mandatory=$false)]
    [string]$ExtraArgs = ""
)

$ErrorActionPreference = "Stop"

switch ($Task) {
    "test" {
        Write-Host "==> Executing test suite with pytest..." -ForegroundColor Cyan
        python -m pytest tests/ -v
    }

    "smoke" {
        Write-Host "==> Executing isolated end-to-end smoke test..." -ForegroundColor Cyan
        python scripts/smoke_test.py
    }

    "eval" {
        Write-Host "==> Executing benchmark evaluation harness..." -ForegroundColor Cyan
        python -m eval.run_eval --runs 3
    }

    "seed" {
        Write-Host "==> Seeding synthetic commercial leases, assets, and PDFs..." -ForegroundColor Cyan
        python -m app.seed
    }

    "run" {
        Write-Host "==> Triggering batch agent run for in-window leases..." -ForegroundColor Cyan
        python -m app.run $ExtraArgs
    }

    "api" {
        Write-Host "==> Starting FastAPI Approvals & Audit backend on http://localhost:8000..." -ForegroundColor Cyan
        python -m uvicorn app.api:app --reload --port 8000
    }

    "ui" {
        Write-Host "==> Starting Streamlit Approvals Inbox on http://localhost:8501..." -ForegroundColor Cyan
        python -m streamlit run ui/streamlit_app.py
    }

    "lint" {
        Write-Host "==> Running ruff code quality checks..." -ForegroundColor Cyan
        python -m ruff check app/ ui/ eval/ tests/ scripts/
    }

    "clean" {
        Write-Host "==> Cleaning cache directories and temporary test files..." -ForegroundColor Cyan
        Get-ChildItem -Path . -Include __pycache__, .pytest_cache -Recurse -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "Clean completed." -ForegroundColor Green
    }

    "help" {
        Write-Host "Available tasks in tasks.ps1:" -ForegroundColor Yellow
        Write-Host "  test   - Run pytest unit and integration test suite"
        Write-Host "  smoke  - Run automated isolated end-to-end smoke test"
        Write-Host "  eval   - Run benchmark evaluation harness"
        Write-Host "  seed   - Seed database and generate lease PDFs"
        Write-Host "  run    - Run batch agent over in-window leases"
        Write-Host "  api    - Start FastAPI backend server"
        Write-Host "  ui     - Start Streamlit approvals UI"
        Write-Host "  lint   - Run ruff linter checks"
        Write-Host "  clean  - Remove pycache and temporary files"
    }
}
