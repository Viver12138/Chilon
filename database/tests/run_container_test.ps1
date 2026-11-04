# Applies the generated DDL to a throwaway PostgreSQL 17 container and verifies it.
#
#   .\database\tests\run_container_test.ps1
#   .\database\tests\run_container_test.ps1 -KeepContainer
#
# Expected counts come from database/generated/manifest.json, so the test cannot
# drift from the registry. Requires Docker running (Docker Desktop locally, the
# preinstalled daemon on GitHub runners).

param(
    [string]$Container = "chilon-pg-test",
    [int]$Port = 55432,
    [string]$Password = "chilon_test_only",
    [switch]$KeepContainer
)

# Native commands write diagnostics to stderr (psql NOTICE, docker pull progress).
# With 'Stop', PowerShell turns redirected stderr into terminating errors, so we
# keep 'Continue' and check exit codes explicitly. `throw` is always terminating.
$ErrorActionPreference = "Continue"
if (Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ddl = Join-Path $root "database/generated/schema.sql"
$verify = Join-Path $root "database/tests/verify_schema.sql"

# Any terminating error prints enough context to diagnose from CI logs alone.
# Details are also emitted as ::error:: annotations, which are readable through
# the GitHub API without admin rights on the repository.
trap {
    $detail = "$_"
    Write-Host "::error::container test failed: $detail"
    Write-Host "::error::PowerShell $($PSVersionTable.PSVersion) on $([System.Environment]::OSVersion.VersionString)"
    Write-Host "::error::at $($_.InvocationInfo.PositionMessage -replace "`r?`n", ' | ')"
    Write-Host "PowerShell      : $($PSVersionTable.PSVersion)"
    Write-Host "Root            : $root"
    Write-Host "Error           : $detail"
    Write-Host "--- docker ps -a ---"
    docker ps -a 2>&1 | ForEach-Object { Write-Host "  $_" }
    Write-Host "--- container logs ---"
    docker logs --tail 40 $Container 2>&1 | ForEach-Object { Write-Host "  $_" }
    exit 1
}

if (-not (Test-Path $ddl)) { throw "Missing $ddl - run: python database/generator/generate_ddl.py" }

$manifest = Get-Content (Join-Path $root "database/generated/manifest.json") -Raw | ConvertFrom-Json
$verifyArgs = @(
    "-v", "expected_tables=$($manifest.tables)",
    "-v", "expected_policies=$($manifest.policies)",
    "-v", "expected_indexes=$($manifest.indexes)",
    "-v", "expected_min_fk=$($manifest.min_foreign_keys)"
)
Write-Host "==> expected: $($manifest.tables) tables, $($manifest.policies) policies, $($manifest.indexes) indexes" -ForegroundColor Cyan

Write-Host "==> docker daemon" -ForegroundColor Cyan
$version = & docker version --format "{{.Server.Version}}" 2>&1
Write-Host "    server $version (exit $LASTEXITCODE)"
if ($LASTEXITCODE -ne 0) { throw "Docker is not reachable: $version" }

$existing = (& docker ps -a --filter "name=^/$Container$" --format "{{.Names}}" 2>&1)
if ($existing) {
    Write-Host "==> removing previous container" -ForegroundColor Cyan
    & docker rm -f $Container 2>&1 | Out-Null
}

Write-Host "==> starting postgres:17" -ForegroundColor Cyan
& # Nine throwaway containers in one CI job is enough that a transient
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
for ($i = 0; $i -lt 60; $i++) {
    # Probe over TCP (-h 127.0.0.1): during initdb the entrypoint runs a temporary
    # instance that listens on the unix socket only, so a socket-only probe reports
    # ready while the server is about to be shut down. TCP exists only on the real one.
    & docker exec $Container pg_isready -h 127.0.0.1 -p 5432 -U postgres -d chilon *> $null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) { throw "PostgreSQL did not become ready in 30s" }
Write-Host "    ready after $([math]::Round($i * 0.5, 1))s"

Write-Host "==> copying SQL into the container" -ForegroundColor Cyan
& docker cp $ddl "${Container}:/tmp/schema.sql" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "docker cp (schema.sql) failed" }
& docker cp $verify "${Container}:/tmp/verify_schema.sql" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "docker cp (verify_schema.sql) failed" }

function Invoke-Psql {
    param([string]$File, [string[]]$ExtraArgs, [switch]$Quiet)
    $psqlArgs = @("exec", $Container, "psql", "-U", "postgres", "-d", "chilon", "-v", "ON_ERROR_STOP=1", "-f", $File)
    if ($ExtraArgs) { $psqlArgs += $ExtraArgs }
    if ($Quiet) { $psqlArgs += "-q" }
    $raw = & docker @psqlArgs 2>&1
    $code = $LASTEXITCODE
    if ($raw) {
        foreach ($line in $raw) {
            $text = "$line"
            Write-Host "    $text"
            # surface SQL errors as annotations so CI failures are diagnosable
            if ($code -ne 0) { Write-Host "::error::psql: $text" }
        }
    }
    return $code
}

Write-Host "==> applying generated DDL" -ForegroundColor Cyan
if ((Invoke-Psql -File "/tmp/schema.sql" -Quiet) -ne 0) { throw "DDL application failed" }

Write-Host "==> running structural verification" -ForegroundColor Cyan
if ((Invoke-Psql -File "/tmp/verify_schema.sql" -ExtraArgs $verifyArgs) -ne 0) { throw "Verification failed" }

Write-Host ""
Write-Host "PASS: DDL applied and verified on postgres:17" -ForegroundColor Green

if (-not $KeepContainer) {
    & docker rm -f $Container 2>&1 | Out-Null
} else {
    Write-Host "container kept: $Container (port $Port)" -ForegroundColor Yellow
}
