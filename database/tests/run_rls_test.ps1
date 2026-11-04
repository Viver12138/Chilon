# Row-level security isolation test.
#
#   .\database\tests\run_rls_test.ps1
#
# Applies the generated schema to a throwaway PostgreSQL 17 container, then
# proves that one teacher cannot see, modify or forge another teacher's rows.

param(
    [string]$Container = "chilon-pg-rls",
    [int]$Port = 55434,
    [string]$Password = "chilon_test_only"
)

# Native commands write diagnostics to stderr; keep 'Continue' and check codes.
$ErrorActionPreference = "Continue"
if (Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ddl = Join-Path $root "database/generated/schema.sql"
$rls = Join-Path $root "database/tests/rls_isolation_test.sql"

trap {
    Write-Host "::error::RLS test failed: $_"
    Write-Host "::error::at $($_.InvocationInfo.PositionMessage -replace "`r?`n", ' | ')"
    docker logs --tail 40 $Container 2>&1 | ForEach-Object { Write-Host "  $_" }
    docker rm -f $Container 2>&1 | Out-Null
    exit 1
}

if (-not (Test-Path $ddl)) { throw "Missing $ddl - run: python database/generator/generate_ddl.py" }

Write-Host "==> starting postgres:17" -ForegroundColor Cyan
docker rm -f $Container 2>&1 | Out-Null
docker run -d --name $Container -e "POSTGRES_PASSWORD=$Password" -e "POSTGRES_DB=chilon" -p "${Port}:5432" postgres:17 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "docker run failed" }

$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    # Probe over TCP (-h 127.0.0.1): during initdb the entrypoint runs a temporary
    # instance that listens on the unix socket only, so a socket-only probe reports
    # ready while the server is about to be shut down. TCP exists only on the real one.
    docker exec $Container pg_isready -h 127.0.0.1 -p 5432 -U postgres -d chilon *> $null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) { throw "PostgreSQL did not become ready" }

docker cp $ddl "${Container}:/tmp/schema.sql" 2>&1 | Out-Null
docker cp $rls "${Container}:/tmp/rls_isolation_test.sql" 2>&1 | Out-Null

Write-Host "==> applying schema" -ForegroundColor Cyan
docker exec $Container psql -U postgres -d chilon -v ON_ERROR_STOP=1 -q -f /tmp/schema.sql 2>&1 | ForEach-Object { Write-Host "    $_" }
if ($LASTEXITCODE -ne 0) { throw "DDL application failed" }

Write-Host "==> running isolation assertions" -ForegroundColor Cyan
docker exec $Container psql -U postgres -d chilon -v ON_ERROR_STOP=1 -f /tmp/rls_isolation_test.sql 2>&1 | ForEach-Object { Write-Host "    $_" }
if ($LASTEXITCODE -ne 0) { throw "RLS isolation assertions failed" }

docker rm -f $Container 2>&1 | Out-Null

Write-Host ""
Write-Host "PASS: RLS hides, blocks and rejects cross-tenant access" -ForegroundColor Green
