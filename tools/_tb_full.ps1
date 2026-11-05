# Full corpus build into a persistent container: 6050 TeX problems + 5 textbooks (OCR).
#
#   .\tools\_tb_full.ps1
#
# Leaves the container running as chilon-pg-corpus so the corpus can be inspected.

param(
    [string]$Container = "chilon-pg-corpus",
    [int]$Port = 55495,
    [string]$Password = "chilon_test_only"
)

$ErrorActionPreference = "Continue"
if (Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

$root = "D:\Chilon"
$ddl = Join-Path $root "database/generated/schema.sql"
$python = Join-Path $root ".venv/Scripts/python.exe"

Write-Host "==> postgres" -ForegroundColor Cyan
if (-not (docker ps -aq -f "name=^/$Container$")) {
    docker run -d --name $Container -e "POSTGRES_PASSWORD=$Password" -e "POSTGRES_DB=chilon" -p "${Port}:5432" postgres:17 | Out-Null
}
$ready = $false
for ($i = 0; $i -lt 120; $i++) {
    docker exec $Container pg_isready -h 127.0.0.1 -p 5432 -U postgres -d chilon *> $null
    if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) { Write-Host "postgres not ready" -ForegroundColor Red; exit 1 }

$url = "postgresql+psycopg://postgres:$Password@localhost:$Port/chilon"
$env:CHILON_DATABASE_URL = $url
$env:CHILON_TEST_DATABASE_URL = $url
$env:CHILON_OCR_PROVIDER = "aliyun"

# apply the schema only once: re-applying it wipes the corpus
$hasTable = docker exec $Container psql -U postgres -d chilon -tAc "SELECT to_regclass('public.knowledge_sources')" 2>&1
if ($hasTable -notmatch "knowledge_sources") {
    docker cp $ddl "${Container}:/tmp/schema.sql" 2>&1 | Out-Null
    Write-Host "==> applying schema" -ForegroundColor Cyan
    docker exec $Container psql -U postgres -d chilon -v ON_ERROR_STOP=1 -q -f /tmp/schema.sql 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Host "DDL failed" -ForegroundColor Red; exit 1 }
}

Push-Location $root
try {
    Write-Host "==> TeX problems (2012-2026)" -ForegroundColor Cyan
    & $python "tools/import_tex.py" --content "var/_tex_clone/repo/content" --since 2012 *>&1 |
        ForEach-Object { Write-Host "  $_" }

    Write-Host "==> textbooks (974 pages, 974 OCR calls)" -ForegroundColor Cyan
    & $python "tools/import_textbook.py" --dir "corpus/textbooks" *>&1 |
        ForEach-Object { Write-Host "  $_" }

    Write-Host "==> summary" -ForegroundColor Cyan
    & $python "tools/_corpus_summary.py" *>&1 | ForEach-Object { Write-Host "  $_" }
}
finally {
    Pop-Location
}
Write-Host "container $Container left running on port $Port" -ForegroundColor Green
