# Identity service test: applies the schema to a throwaway container, then runs
# the authentication scenarios against it.
#
#   .\database\tests\run_identity_test.ps1

param(
    [string]$Container = "chilon-pg-identity",
    [int]$Port = 55436,
    [string]$Password = "chilon_test_only"
)

# Native commands write diagnostics to stderr; keep 'Continue' and check codes.
$ErrorActionPreference = "Continue"
if (Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ddl = Join-Path $root "database/generated/schema.sql"
$python = Join-Path $root ".venv/Scripts/python.exe"
if (-not (Test-Path $python)) { $python = "python" }

trap {
    Write-Host "::error::identity test failed: $_"
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

Write-Host "==> running identity scenarios" -ForegroundColor Cyan
$env:CHILON_TEST_DATABASE_URL = "postgresql+psycopg://postgres:$Password@localhost:$Port/chilon"
Push-Location (Join-Path $root "backend")
try {
    $out = & $python "tests/test_identity.py" 2>&1
    $code = $LASTEXITCODE
    $out | ForEach-Object { Write-Host "  $_" }
    if ($code -ne 0) {
        $out | Select-Object -Last 12 | ForEach-Object { Write-Host "::error::identity: $_" }
        throw "identity scenarios failed (exit $code)"
    }
}
finally {
    Pop-Location
    docker rm -f $Container 2>&1 | Out-Null
}

Write-Host ""
Write-Host "PASS: identity service verified" -ForegroundColor Green
