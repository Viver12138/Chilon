# One-off: pilot the textbook import on a few pages, then measure chunk quality.
#
#   .\tools\_tb_run.ps1 -MaxPages 12

param(
    [string]$Container = "chilon-pg-tb",
    [int]$Port = 55490,
    [string]$Password = "chilon_test_only",
    [int]$MaxPages = 12,
    [string]$File = ""
)

$ErrorActionPreference = "Continue"
if (Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$root = "D:\Chilon"
$ddl = Join-Path $root "database/generated/schema.sql"
$python = Join-Path $root ".venv/Scripts/python.exe"

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
docker exec $Container psql -U postgres -d chilon -v ON_ERROR_STOP=1 -q -f /tmp/schema.sql 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "DDL failed" -ForegroundColor Red; docker rm -f $Container | Out-Null; exit 1 }

$url = "postgresql+psycopg://postgres:$Password@localhost:$Port/chilon"
$env:CHILON_DATABASE_URL = $url
$env:CHILON_TEST_DATABASE_URL = $url
$env:CHILON_OCR_PROVIDER = "aliyun"
Push-Location $root
try {
    $args = @("tools/import_textbook.py", "--dir", "corpus/textbooks", "--max-pages", "$MaxPages")
    if ($File) { $args += @("--file", $File) }
    & $python @args *>&1 | ForEach-Object { Write-Host "  $_" }

    & $python "tools/_tb_probe.py" *>&1 | ForEach-Object { Write-Host "  $_" }
}
finally {
    Pop-Location
    docker rm -f $Container 2>&1 | Out-Null
}
