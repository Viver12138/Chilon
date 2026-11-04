# End-to-end migration test: upgrade -> verify -> downgrade -> verify rollback.
#
#   .\database\tests\run_migration_test.ps1
#
# Requires: Docker Desktop running, and alembic + psycopg installed in .venv.

param(
    [string]$Container = "chilon-pg-migrate",
    [int]$Port = 55433,
    [string]$Password = "chilon_test_only",
    [string]$Revision = "0001_baseline"
)

# Native commands write diagnostics to stderr (psql NOTICE, alembic INFO).
# With 'Stop', PowerShell turns redirected stderr into terminating errors, so we
# keep 'Continue' and check exit codes explicitly. `throw` is always terminating.
$ErrorActionPreference = "Continue"
if (Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$verify = Join-Path $root "database/tests/verify_schema.sql"
$python = Join-Path $root ".venv/Scripts/python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$manifest = Get-Content (Join-Path $root "database/generated/manifest.json") -Raw | ConvertFrom-Json
$verifyArgs = @(
    "-v", "expected_tables=$($manifest.tables)",
    "-v", "expected_policies=$($manifest.policies)",
    "-v", "expected_indexes=$($manifest.indexes)",
    "-v", "expected_min_fk=$($manifest.min_foreign_keys)"
)

Write-Host "==> docker daemon" -ForegroundColor Cyan
docker version --format "{{.Server.Version}}" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Docker is not running" }

if (docker ps -a --filter "name=^/$Container$" --format "{{.Names}}") {
    docker rm -f $Container | Out-Null
}

Write-Host "==> starting postgres:17 on port $Port" -ForegroundColor Cyan
docker run -d --name $Container -e "POSTGRES_PASSWORD=$Password" -e "POSTGRES_DB=chilon" -p "${Port}:5432" postgres:17 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "docker run failed" }

$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    docker exec $Container pg_isready -U postgres -d chilon 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) { docker logs --tail 40 $Container; throw "PostgreSQL not ready" }

function Invoke-Psql {
    param([string]$File, [string[]]$ExtraArgs)
    $psqlArgs = @("exec", $Container, "psql", "-U", "postgres", "-d", "chilon", "-v", "ON_ERROR_STOP=1", "-f", $File)
    if ($ExtraArgs) { $psqlArgs += $ExtraArgs }
    $ErrorActionPreference = "Continue"
    $raw = & docker @psqlArgs 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($raw) { $raw | ForEach-Object { "$_" } | Write-Host }
    return $code
}

$env:CHILON_DATABASE_URL = "postgresql+psycopg://postgres:$Password@localhost:$Port/chilon"
Push-Location (Join-Path $root "backend")
try {
    Write-Host "==> alembic upgrade head" -ForegroundColor Cyan
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "alembic upgrade failed" }

    Write-Host "==> verifying schema after upgrade" -ForegroundColor Cyan
    docker cp $verify "${Container}:/tmp/verify_schema.sql" | Out-Null
    if ((Invoke-Psql -File "/tmp/verify_schema.sql" -ExtraArgs $verifyArgs) -ne 0) { throw "post-upgrade verification failed" }

    Write-Host "==> checking alembic bookkeeping" -ForegroundColor Cyan
    $revOut = & docker exec $Container psql -U postgres -d chilon -t -A -c "SELECT version_num FROM alembic_version" 2>&1
    $rev = ($revOut | ForEach-Object { "$_" }) -join ""
    Write-Host "    alembic_version = $rev"
    if ($rev -ne $Revision) { throw "unexpected revision stamp: $rev" }

    Write-Host "==> alembic downgrade base" -ForegroundColor Cyan
    & $python -m alembic downgrade base
    if ($LASTEXITCODE -ne 0) { throw "alembic downgrade failed" }

    Write-Host "==> verifying rollback is clean" -ForegroundColor Cyan
    $leftOut = & docker exec $Container psql -U postgres -d chilon -t -A -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name <> 'alembic_version'" 2>&1
    $left = (($leftOut | ForEach-Object { "$_" }) -join "").Trim()
    Write-Host "    remaining tables = $left"
    if ($left -ne "0") { throw "downgrade left $left table(s) behind" }

    $fnOut = & docker exec $Container psql -U postgres -d chilon -t -A -c "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.proname LIKE 'app_current_%'" 2>&1
    $fn = (($fnOut | ForEach-Object { "$_" }) -join "").Trim()
    Write-Host "    remaining context functions = $fn"
    if ($fn -ne "0") { throw "downgrade left $fn function(s) behind" }
}
finally {
    Pop-Location
    Write-Host "==> removing container" -ForegroundColor Cyan
    docker rm -f $Container | Out-Null
}

Write-Host ""
Write-Host "PASS: upgrade applied, schema verified, downgrade clean" -ForegroundColor Green
