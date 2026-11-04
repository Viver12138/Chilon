# Applies the generated K009 DDL to a throwaway PostgreSQL 17 container and
# verifies the result.
#
#   .\database\tests\run_container_test.ps1
#   .\database\tests\run_container_test.ps1 -KeepContainer
#
# Requires: Docker Desktop running.
#
# SQL is copied into the container with `docker cp` instead of being piped over
# stdin: Windows PowerShell 5.1 mangles UTF-8 through the pipeline, and the DDL
# contains Chinese comments.

param(
    [string]$Container = "chilon-pg-test",
    [int]$Port = 55432,
    [string]$Password = "chilon_test_only",
    [switch]$KeepContainer
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ddl = Join-Path $root "database/generated/k009.sql"
$verify = Join-Path $root "database/tests/verify_k009.sql"

if (-not (Test-Path $ddl)) {
    throw "Missing $ddl - run: python database/generator/generate_ddl.py"
}

Write-Host "==> docker daemon" -ForegroundColor Cyan
docker version --format "{{.Server.Version}}" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Docker is not running. Start Docker Desktop and retry." }

$existing = (docker ps -a --filter "name=^/$Container$" --format "{{.Names}}")
if ($existing) {
    Write-Host "==> removing previous container $Container" -ForegroundColor Cyan
    docker rm -f $Container | Out-Null
}

Write-Host "==> starting postgres:17" -ForegroundColor Cyan
docker run -d --name $Container `
    -e "POSTGRES_PASSWORD=$Password" `
    -e "POSTGRES_DB=chilon" `
    -p "${Port}:5432" `
    postgres:17 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "docker run failed" }

Write-Host "==> waiting for readiness" -ForegroundColor Cyan
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    docker exec $Container pg_isready -U postgres -d chilon 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) {
    docker logs --tail 40 $Container
    throw "PostgreSQL did not become ready"
}

Write-Host "==> copying SQL into the container" -ForegroundColor Cyan
docker cp $ddl "${Container}:/tmp/k009.sql" | Out-Null
docker cp $verify "${Container}:/tmp/verify_k009.sql" | Out-Null

function Invoke-DockerPsql {
    param([string]$File, [switch]$Quiet)
    # Build the argument list explicitly: a switch cannot be spliced in as "-q:$true".
    $psqlArgs = @(
        "exec", $Container, "psql", "-U", "postgres", "-d", "chilon",
        "-v", "ON_ERROR_STOP=1", "-f", $File
    )
    if ($Quiet) { $psqlArgs += "-q" }
    # Capture stderr as text: PowerShell turns native stderr into error records,
    # which would become terminating under $ErrorActionPreference = 'Stop'.
    $ErrorActionPreference = 'Continue'
    $raw = & docker @psqlArgs 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($raw) { $raw | ForEach-Object { "$_" } | Write-Host }
    return $code
}

Write-Host "==> applying generated DDL" -ForegroundColor Cyan
$ddlCode = Invoke-DockerPsql -File "/tmp/k009.sql" -Quiet
if ($ddlCode -ne 0) { throw "DDL application failed (see output above)" }

Write-Host "==> running structural verification" -ForegroundColor Cyan
$verifyCode = Invoke-DockerPsql -File "/tmp/verify_k009.sql"
if ($verifyCode -ne 0) { throw "Verification failed (see output above)" }

Write-Host ""
Write-Host "PASS: K009 DDL applied and verified on postgres:17" -ForegroundColor Green

if (-not $KeepContainer) {
    Write-Host "==> removing container" -ForegroundColor Cyan
    docker rm -f $Container | Out-Null
} else {
    Write-Host "container kept: $Container (port $Port)" -ForegroundColor Yellow
    Write-Host "connect: psql postgresql://postgres:${Password}@localhost:${Port}/chilon"
}
