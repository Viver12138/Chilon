$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$src = Join-Path $PSScriptRoot 'dsh-presets\chilon-teaching'
$homeRoot = Join-Path $env:USERPROFILE '.dsh\.agent-presets'
$dst = Join-Path $homeRoot 'chilon-teaching'
$repoForYaml = $repo -replace '\\', '/'

if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
New-Item -ItemType Directory -Force $homeRoot | Out-Null
Copy-Item $src $dst -Recurse -Force

$composition = Join-Path $dst 'agent.cordis.yml'
$text = Get-Content $composition -Raw
$text = $text -replace 'D:/Chilon', $repoForYaml
Set-Content $composition $text -Encoding UTF8

Write-Host "Installed DSH preset: $dst"
Write-Host "Refresh the DSH Web UI and choose 'Chilon 教学 Agent' for a new session."
