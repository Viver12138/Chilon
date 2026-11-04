# Outbox dispatcher test: applies the schema to a throwaway container, then runs
# the Python correctness scenarios against it.
#
#   .\database\tests\run_outbox_test.ps1
#
# Requires: Docker, and alembic/sqlalchemy/psycopg installed in .venv.

param(
    [string]$Container = "chilon-pg-outbox",
    [int]$Port = 55435,
    [string]$Password = "chilon_test_only"
)

# Native commands write diagnostics to stderr; keep 'Continue' and check codes.
$ErrorActionPreference = "Continue"
if (Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ddl = Join-Path $root "database/generated/schema.sql"
$test = Join-Path $root "backend/tests/test_outbox.py"
$python = Join-Path $root ".venv/Scripts/python.exe"
if (-not (Test-Path $python)) { $python = "python" }

trap {
    Write-Host "::error::outbox test failed: $_"
    Write-Host "::error::at $($_.InvocationInfo.PositionMessage -replace "`r?`n", ' | ')"
    # the container may already be gone if the failure came after cleanup
    if (docker ps -aq -f "name=^/$Container$") {
        docker logs --tail 30 $Container 2>&1 | ForEach-Object { Write-Host "  $_" }
    }
    docker rm -f $Container 2>&1 | Out-Null
    exit 1
}

Write-Host "==> starting postgres:17" -ForegroundColor Cyan
docker rm -f $Container 2>&1 | Out-Null
docker run -d --name $Container -e "POSTGRES_PASSWORD=$Password" -e "POSTGRES_DB=chilon" -p "${Port}:5432" postgres:17 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "docker run failed" }

$ready = $false
for ($i = 0; $i -lt 120; $i++) {
    # TCP probe: the initdb temp instance listens on the unix socket only.
    docker exec $Container pg_isready -h 127.0.0.1 -p 5432 -U postgres -d chilon *> $null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) { throw "PostgreSQL did not become ready" }

docker cp $ddl "${Container}:/tmp/schema.sql" 2>&1 | Out-Null

Write-Host "==> applying schema" -ForegroundColor Cyan
docker exec $Container psql -U postgres -d chilon -v ON_ERROR_STOP=1 -q -f /tmp/schema.sql 2>&1 | ForEach-Object { Write-Host "    $_" }
if ($LASTEXITCODE -ne 0) { throw "DDL application failed" }

Write-Host "==> running outbox scenarios" -ForegroundColor Cyan
$env:CHILON_TEST_DATABASE_URL = "postgresql+psycopg://postgres:$Password@localhost:$Port/chilon"
Push-Location (Join-Path $root "backend")
try {
    Write-Host "    python: $python"
    & $python --version 2>&1 | ForEach-Object { Write-Host "    $_" }
    $out = & $python "tests/test_outbox.py" 2>&1
    $code = $LASTEXITCODE
    $out | ForEach-Object { Write-Host "  $_" }
    if ($code -ne 0) {
        # surface the tail as annotations: CI logs need admin rights to read
        $out | Select-Object -Last 12 | ForEach-Object { Write-Host "::error::outbox: $_" }
        throw "outbox scenarios failed (exit $code)"
    }
}
finally {
    Pop-Location
    docker rm -f $Container 2>&1 | Out-Null
}

Write-Host ""
Write-Host "PASS: outbox dispatcher verified" -ForegroundColor Green
