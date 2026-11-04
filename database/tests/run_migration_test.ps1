# End-to-end migration test: applies the Alembic baseline to a throwaway
# PostgreSQL 17 container, verifies the schema, then rolls it back and verifies
# the rollback is clean.
#
#   .\database\tests\run_migration_test.ps1
#
# Requires: Docker Desktop running, and `pip install alembic "psycopg[binary]"`
# into the venv (or any environment on PATH with those packages).

param(
    [string]$Container = "chilon-pg-migrate",
    [int]$Port = 55433,
    [string]$Password = "chilon_test_only"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$verify = Join-Path $root "database/tests/verify_k009.sql"
$python = Join-Path $root ".venv/Scripts/python.exe"
if (-not (Test-Path $python)) { $python = "python" }

function Invoke-Psql {
    param([string]$File, [switch]$Quiet)
    $psqlArgs = @(
        "exec", $Container, "psql", "-U", "postgres", "-d", "chilon",
        "-v", "ON_ERROR_STOP=1", "-f", $File
    )
    if ($Quiet) { $psqlArgs += "-q" }
    $ErrorActionPreference = "Continue"
    $raw = & docker @psqlArgs 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($raw) { $raw | ForEach-Object { "$_" } | Write-Host }
    return $code
}

Write-Host "==> docker daemon" -ForegroundColor Cyan
docker version --format "{{.Server.Version}}" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Docker is not running" }

if (docker ps -a --filter "name=^/$Container$" --format "{{.Names}}") {
    docker rm -f $Container | Out-Null
}

Write-Host "==> starting postgres:17 on port $Port" -ForegroundColor Cyan
docker run -d --name $Container `
    -e "POSTGRES_PASSWORD=$Password" `
    -e "POSTGRES_DB=chilon" `
    -p "${Port}:5432" `
    postgres:17 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "docker run failed" }

$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    docker exec $Container pg_isready -U postgres -d chilon 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) { docker logs --tail 40 $Container; throw "PostgreSQL not ready" }

$env:CHILON_DATABASE_URL = "postgresql+psycopg://postgres:$Password@localhost:$Port/chilon"
Push-Location (Join-Path $root "backend")
try {
    Write-Host "==> alembic upgrade head" -ForegroundColor Cyan
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "alembic upgrade failed" }

    Write-Host "==> verifying schema after upgrade" -ForegroundColor Cyan
    docker cp $verify "${Container}:/tmp/verify_k009.sql" | Out-Null
    if ((Invoke-Psql -File "/tmp/verify_k009.sql") -ne 0) { throw "post-upgrade verification failed" }

    Write-Host "==> checking alembic bookkeeping" -ForegroundColor Cyan
    $revOut = & docker exec $Container psql -U postgres -d chilon -t -A -c "SELECT version_num FROM alembic_version" 2>&1
    $rev = ($revOut | ForEach-Object { "$_" }) -join ""
    Write-Host "    alembic_version = $rev"
    if ($rev -ne "0001_k009_baseline") { throw "unexpected revision stamp: $rev" }

    Write-Host "==> alembic downgrade base" -ForegroundColor Cyan
    & $python -m alembic downgrade base
    if ($LASTEXITCODE -ne 0) { throw "alembic downgrade failed" }

    Write-Host "==> verifying rollback is clean" -ForegroundColor Cyan
    $leftOut = & docker exec $Container psql -U postgres -d chilon -t -A -c `
        "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND (table_name LIKE 'knowledge\_%' OR table_name='material_knowledge_citations')" 2>&1
    $left = ($leftOut | ForEach-Object { "$_" }) -join ""
    Write-Host "    remaining K009 tables = $left"
    if ($left.Trim() -ne "0") { throw "downgrade left $left table(s) behind" }

    $fnOut = & docker exec $Container psql -U postgres -d chilon -t -A -c `
        "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname LIKE 'app_current_%'" 2>&1
    $fn = ($fnOut | ForEach-Object { "$_" }) -join ""
    Write-Host "    remaining context functions = $fn"
    if ($fn.Trim() -ne "0") { throw "downgrade left $fn function(s) behind" }
}
finally {
    Pop-Location
    Write-Host "==> removing container" -ForegroundColor Cyan
    docker rm -f $Container | Out-Null
}

Write-Host ""
Write-Host "PASS: upgrade applied, schema verified, downgrade clean" -ForegroundColor Green
