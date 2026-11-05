# OCR test: applies the schema to a throwaway container, then checks
# the service against every transition in the frozen contract.
#
#   .\database\tests\run_e2e_aliyun.ps1

param(
    [string]$Container = "chilon-pg-e2e",
    [int]$Port = 55459,
    [string]$Password = "chilon_test_only"
)

$ErrorActionPreference = "Continue"
if (Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ddl = Join-Path $root "database/generated/schema.sql"
$python = Join-Path $root ".venv/Scripts/python.exe"
if (-not (Test-Path $python)) { $python = "python" }

trap {
    Write-Host "::error::e2e failed: $_"
    Write-Host "::error::at $($_.InvocationInfo.PositionMessage -replace "`r?`n", ' | ')"
    if (docker ps -aq -f "name=^/$Container$") {
        docker logs --tail 30 $Container 2>&1 | ForEach-Object { Write-Host "  $_" }
    }
    docker rm -f $Container 2>&1 | Out-Null
    exit 1
}

Write-Host "==> starting postgres:17" -ForegroundColor Cyan
docker rm -f $Container 2>&1 | Out-Null
# Nine throwaway containers in one CI job is enough that a transient
# daemon error looks like a broken commit. Retry: the operation is idempotent
# (fixed name, removed before each attempt) and the error is printed if it
# really is permanent.
$runError = ""
$started = $false
for ($attempt = 1; $attempt -le 3; $attempt++) {
    docker rm -f $Container 2>&1 | Out-Null
    $runError = docker run -d --name $Container -e "POSTGRES_PASSWORD=$Password" -e "POSTGRES_DB=chilon" -p "${Port}:5432" postgres:17 2>&1
    if ($LASTEXITCODE -eq 0) { $started = $true; break }
    Write-Host "    docker run attempt $attempt failed: $runError" -ForegroundColor Yellow
    Start-Sleep -Seconds 2
}
if (-not $started) { throw "docker run failed after 3 attempts: $runError" }

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

Write-Host "==> running the real Aliyun end-to-end run" -ForegroundColor Cyan
$env:CHILON_TEST_DATABASE_URL = "postgresql+psycopg://postgres:$Password@localhost:$Port/chilon"
$env:CHILON_DATABASE_URL = $env:CHILON_TEST_DATABASE_URL
Push-Location $root
try {
    $out = & $python "tools/aliyun_e2e.py" 2>&1
    $code = $LASTEXITCODE
    $out | ForEach-Object { Write-Host "  $_" }
    if ($code -ne 0) {
        $out | Select-Object -Last 15 | ForEach-Object { Write-Host "::error::e2e: $_" }
        throw "e2e failed (exit $code)"
    }
}
finally {
    Pop-Location
    docker rm -f $Container 2>&1 | Out-Null
}

Write-Host ""
Write-Host "PASS: ocr verified" -ForegroundColor Green
