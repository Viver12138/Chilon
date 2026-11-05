# One-off: import the TeX corpus (2012+) into a throwaway database and measure it.
#
#   .\tools\_tex_run.ps1

param(
    [string]$Container = "chilon-pg-tex",
    [int]$Port = 55480,
    [string]$Password = "chilon_test_only",
    [string]$Content = "D:\Chilon\var\_tex_clone\repo\content",
    [int]$Since = 2012
)

$ErrorActionPreference = "Continue"
if (Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$root = "D:\Chilon"
$ddl = Join-Path $root "database/generated/schema.sql"
$python = Join-Path $root ".venv/Scripts/python.exe"

Write-Host "==> starting postgres:17" -ForegroundColor Cyan
docker rm -f $Container 2>&1 | Out-Null
$started = $false
for ($attempt = 1; $attempt -le 3; $attempt++) {
    docker rm -f $Container 2>&1 | Out-Null
    $out = docker run -d --name $Container -e "POSTGRES_PASSWORD=$Password" -e "POSTGRES_DB=chilon" -p "${Port}:5432" postgres:17 2>&1
    if ($LASTEXITCODE -eq 0) { $started = $true; break }
    Start-Sleep -Seconds 2
}
if (-not $started) { Write-Host "docker run failed: $out" -ForegroundColor Red; exit 1 }

$ready = $false
for ($i = 0; $i -lt 120; $i++) {
    docker exec $Container pg_isready -h 127.0.0.1 -p 5432 -U postgres -d chilon *> $null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) { Write-Host "postgres not ready" -ForegroundColor Red; docker rm -f $Container | Out-Null; exit 1 }

docker cp $ddl "${Container}:/tmp/schema.sql" 2>&1 | Out-Null
Write-Host "==> applying schema" -ForegroundColor Cyan
docker exec $Container psql -U postgres -d chilon -v ON_ERROR_STOP=1 -q -f /tmp/schema.sql 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "DDL failed" -ForegroundColor Red; docker rm -f $Container | Out-Null; exit 1 }

$url = "postgresql+psycopg://postgres:$Password@localhost:$Port/chilon"
$env:CHILON_DATABASE_URL = $url
$env:CHILON_TEST_DATABASE_URL = $url
Push-Location $root
try {
    Write-Host "==> importing TeX corpus (since $Since)" -ForegroundColor Cyan
    & $python "tools/import_tex.py" --content $Content --since $Since *>&1 | ForEach-Object { Write-Host "  $_" }

    Write-Host "==> measuring" -ForegroundColor Cyan
    & $python "tools/_tex_probe.py" *>&1 | ForEach-Object { Write-Host "  $_" }
}
finally {
    Pop-Location
    docker rm -f $Container 2>&1 | Out-Null
}
