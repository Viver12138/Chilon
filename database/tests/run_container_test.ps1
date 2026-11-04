# Applies the generated DDL to a throwaway PostgreSQL 17 container and verifies it.
#
#   .\database\tests\run_container_test.ps1
#   .\database\tests\run_container_test.ps1 -KeepContainer
#
# Expected counts come from database/generated/manifest.json, so the test cannot
# drift from the registry. Requires Docker Desktop running.

param(
    [string]$Container = "chilon-pg-test",
    [int]$Port = 55432,
    [string]$Password = "chilon_test_only",
    [switch]$KeepContainer
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ddl = Join-Path $root "database/generated/schema.sql"
$verify = Join-Path $root "database/tests/verify_schema.sql"

if (-not (Test-Path $ddl)) { throw "Missing $ddl - run: python database/generator/generate_ddl.py" }

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

Write-Host "==> starting postgres:17" -ForegroundColor Cyan
docker run -d --name $Container -e "POSTGRES_PASSWORD=$Password" -e "POSTGRES_DB=chilon" -p "${Port}:5432" postgres:17 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "docker run failed" }

$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    docker exec $Container pg_isready -U postgres -d chilon 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) { docker logs --tail 40 $Container; throw "PostgreSQL not ready" }

Write-Host "==> copying SQL into the container" -ForegroundColor Cyan
docker cp $ddl "${Container}:/tmp/schema.sql" | Out-Null
docker cp $verify "${Container}:/tmp/verify_schema.sql" | Out-Null

function Invoke-Psql {
    param([string]$File, [string[]]$ExtraArgs, [switch]$Quiet)
    $psqlArgs = @("exec", $Container, "psql", "-U", "postgres", "-d", "chilon", "-v", "ON_ERROR_STOP=1", "-f", $File)
    if ($ExtraArgs) { $psqlArgs += $ExtraArgs }
    if ($Quiet) { $psqlArgs += "-q" }
    $ErrorActionPreference = "Continue"
    $raw = & docker @psqlArgs 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($raw) { $raw | ForEach-Object { "$_" } | Write-Host }
    return $code
}

Write-Host "==> applying generated DDL" -ForegroundColor Cyan
if ((Invoke-Psql -File "/tmp/schema.sql" -Quiet) -ne 0) { throw "DDL application failed" }

Write-Host "==> running structural verification" -ForegroundColor Cyan
if ((Invoke-Psql -File "/tmp/verify_schema.sql" -ExtraArgs $verifyArgs) -ne 0) { throw "Verification failed" }

Write-Host ""
Write-Host "PASS: DDL applied and verified on postgres:17" -ForegroundColor Green

if (-not $KeepContainer) {
    docker rm -f $Container | Out-Null
} else {
    Write-Host "container kept: $Container (port $Port)" -ForegroundColor Yellow
}
