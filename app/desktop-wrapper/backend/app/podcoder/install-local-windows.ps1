# Simko SI local coding install for native Windows (A5). Same contract as install-local-aspire.sh:
#   PODCODER_STAGE <prereqs|ollama|pull|aider|pytest|smoke> lines, one PODCODER_FAIL line on any failure,
#   PODCODER_LOCAL_SMOKE_PASS at the end, and $PODCODER_STATE_DIR\local-smoke.json.
# Per-user, no admin prompt: reuses an Ollama that already answers, else installs OllamaSetup.exe silently
# into %LOCALAPPDATA%\Programs\Ollama, pulls the model through the HTTP API, installs Aider with uv + Python 3.12,
# and pytest (pinned) into the Simko SI test venv %LOCALAPPDATA%\SimkoSI\test-venv (coding_intent.test_python).
# Never pulls the cloud q8 tag, never rents, never destroys.
# STATUS: written and syntax-reviewed on Linux only. NOT yet run on a real Windows machine.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
function Fail($msg, $code = 1) { [Console]::Error.WriteLine("PODCODER_FAIL $msg"); exit $code }

if ($args -contains 'destroy' -or $env:PODCODER_DESTROY -eq '1') {
  [Console]::Error.WriteLine('refuse destroy; this pack does not auto-destroy'); exit 3
}
$Model = if ($env:PODCODER_MODEL) { $env:PODCODER_MODEL } else { 'granite4.2:8b' }
if ($Model -eq 'granite4.2:8b-q8_0') { [Console]::Error.WriteLine('refuse: Aspire profile does not pull the cloud q8 tag'); exit 4 }
if ($env:PODCODER_DRY_RUN -eq '1') {
  if ($env:PODCODER_DRY_RUN_HOLD -match '^[0-9]+(\.[0-9]+)?$') { Start-Sleep -Seconds ([double]$env:PODCODER_DRY_RUN_HOLD) }
  Write-Output "PODCODER_DRY_RUN script=install-local-windows.ps1 model=$Model"
  Write-Output 'PODCODER_DRY_RUN_OK'
  exit 0
}
$AiderVersion = if ($env:PODCODER_AIDER_VERSION) { $env:PODCODER_AIDER_VERSION } else { '0.86.2' }
$PytestVersion = if ($env:PODCODER_PYTEST_VERSION) { $env:PODCODER_PYTEST_VERSION } else { '9.2.0' }
$TestVenv = if ($env:PODCODER_TEST_VENV) { $env:PODCODER_TEST_VENV } else { Join-Path $env:LOCALAPPDATA 'SimkoSI\test-venv' }
$TestPy = Join-Path $TestVenv 'Scripts\python.exe'
$Base = if ($env:OLLAMA_API_BASE) { $env:OLLAMA_API_BASE.TrimEnd('/') } else { 'http://127.0.0.1:11434' }
$OllamaDir = Join-Path $env:LOCALAPPDATA 'Programs\Ollama'
$OllamaExe = Join-Path $OllamaDir 'ollama.exe'
$UserBin = Join-Path $env:USERPROFILE '.local\bin'
$env:PATH = "$UserBin;$OllamaDir;$env:PATH"

function Api-Up { try { Invoke-RestMethod -Uri "$Base/api/tags" -TimeoutSec 3 | Out-Null; $true } catch { $false } }
function Have-Model {
  try {
    $names = (Invoke-RestMethod -Uri "$Base/api/tags" -TimeoutSec 5).models | ForEach-Object { $_.name }
    return ($names -contains $Model) -or ($names -contains "$Model`:latest")
  } catch { return $false }
}

Write-Output '==> Prerequisites'
Write-Output 'PODCODER_STAGE prereqs'
if ([Environment]::Is64BitOperatingSystem -eq $false) { Fail 'Simko SI needs 64-bit Windows.' }
$arch = $env:PROCESSOR_ARCHITECTURE
if ($arch -eq 'ARM64') { Write-Output 'Windows on ARM: Ollama runs on the CPU here (no GPU acceleration).' }
$drive = (Get-Item $env:USERPROFILE).PSDrive
if ($drive.Free -lt 15GB) { Fail ("Only {0:N0} GB free on {1}:. Granite needs about 15 GB." -f ($drive.Free / 1GB), $drive.Name) }

Write-Output '==> Ollama'
Write-Output 'PODCODER_STAGE ollama'
if (Api-Up) {
  Write-Output "using the Ollama already answering at $Base"
} else {
  if (-not (Test-Path $OllamaExe) -and -not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    $setup = Join-Path $env:TEMP 'OllamaSetup.exe'
    try { Invoke-WebRequest -Uri 'https://ollama.com/download/OllamaSetup.exe' -OutFile $setup -UseBasicParsing }
    catch { Fail 'Downloading Ollama failed. Check the internet connection and press Download again.' }
    # Inno Setup per-user silent install: no UAC prompt, no window.
    $p = Start-Process -FilePath $setup -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', "/DIR=$OllamaDir" -PassThru -Wait
    if ($p.ExitCode -ne 0) { Fail "The Ollama installer stopped with code $($p.ExitCode)." }
  }
  if (-not (Api-Up)) {
    $exe = if (Test-Path $OllamaExe) { $OllamaExe } else { (Get-Command ollama).Source }
    Start-Process -FilePath $exe -ArgumentList 'serve' -WindowStyle Hidden | Out-Null
    $ready = $false
    for ($i = 0; $i -lt 60; $i++) { if (Api-Up) { $ready = $true; break }; Start-Sleep -Seconds 1 }
    if (-not $ready) { Fail 'Ollama did not start.' }
  }
}

Write-Output "==> Model $Model"
Write-Output 'PODCODER_STAGE pull'
if (Have-Model) {
  Write-Output "skip pull; $Model already present"
} else {
  $exe = if (Test-Path $OllamaExe) { $OllamaExe } elseif (Get-Command ollama -ErrorAction SilentlyContinue) { (Get-Command ollama).Source } else { $null }
  if ($exe) {
    & $exe pull $Model
    if ($LASTEXITCODE -ne 0) { Fail "Granite $Model did not finish downloading. Press Download again to resume." }
  } else {
    try {
      $body = @{ model = $Model; stream = $false } | ConvertTo-Json
      $r = Invoke-RestMethod -Uri "$Base/api/pull" -Method Post -Body $body -ContentType 'application/json' -TimeoutSec 7200
      if ($r.error) { Fail "Granite download failed: $($r.error)" }
    } catch { Fail "Granite $Model did not finish downloading. Press Download again to resume." }
  }
}
if (-not (Have-Model)) { Fail 'local model missing after pull' }

Write-Output '==> Aider'
Write-Output 'PODCODER_STAGE aider'
# aider-chat 0.86.2 needs Python >=3.10,<3.13; uv brings its own Python 3.12 (S1).
$aiderOk = $false
try { & aider --version *> $null; $aiderOk = ($LASTEXITCODE -eq 0) } catch { $aiderOk = $false }
if (-not $aiderOk) {
  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    try { $env:UV_NO_MODIFY_PATH = '1'; Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression }
    catch { Fail 'Could not install uv to install Aider.' }
  }
  & uv tool install --quiet --force --python 3.12 "aider-chat==$AiderVersion"
  if ($LASTEXITCODE -ne 0) { Fail 'Aider did not install.' }
}
& aider --version
if ($LASTEXITCODE -ne 0) { Fail 'Aider is installed but does not start.' }

Write-Output '==> pytest'
Write-Output 'PODCODER_STAGE pytest'
# The coding test step runs "<test venv>\Scripts\python.exe -m pytest -q". Idempotent: skip when the pinned pytest answers.
function Pytest-Version {
  if (-not (Test-Path -LiteralPath $TestPy)) { return '' }
  try { return ((& $TestPy -m pytest --version 2>$null) -join ' ').Trim() } catch { return '' }
}
if ((Pytest-Version) -eq "pytest $PytestVersion") {
  Write-Output "skip pytest; $PytestVersion already in $TestVenv"
} else {
  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    try { $env:UV_NO_MODIFY_PATH = '1'; Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression }
    catch { Fail 'Could not install uv to install pytest.' }
  }
  if (-not (Test-Path -LiteralPath $TestPy)) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $TestVenv) | Out-Null
    & uv venv --quiet --python 3.12 "$TestVenv"
    if ($LASTEXITCODE -ne 0) { Fail 'Could not create the Python 3.12 test environment for pytest.' }
  }
  & uv pip install --quiet --python "$TestPy" "pytest==$PytestVersion"
  if ($LASTEXITCODE -ne 0) { Fail 'pytest did not install.' }
}
if (-not (Pytest-Version)) { Fail 'pytest is installed but does not start.' }
Write-Output (Pytest-Version)

Write-Output '==> Smoke generate'
Write-Output 'PODCODER_STAGE smoke'
$smokeTimeout = if ($env:PODCODER_SMOKE_TIMEOUT) { [int]$env:PODCODER_SMOKE_TIMEOUT } else { 300 }
try {
  $req = @{ model = $Model; prompt = 'Reply with the single word pong.'; stream = $false; think = $false; options = @{ num_predict = 16 } } | ConvertTo-Json
  $gen = Invoke-RestMethod -Uri "$Base/api/generate" -Method Post -Body $req -ContentType 'application/json' -TimeoutSec $smokeTimeout
} catch { Fail 'Granite did not answer the test question in time.' }
if (-not ("$($gen.response)".Trim())) { Fail 'Granite answered with an empty reply.' }
$State = if ($env:PODCODER_STATE_DIR) { $env:PODCODER_STATE_DIR } else { Join-Path $env:USERPROFILE '.podcoder' }
New-Item -ItemType Directory -Force -Path $State | Out-Null
$Profile = if ($Model -like '*q5*') { 'local_ram32_q5' } else { 'local_aspire_ryzen7000' }
@{ status = 'pass'; model = $Model; profile = $Profile; compute = 'local'; updated_at = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ') } |
  ConvertTo-Json | Set-Content -Encoding UTF8 -Path (Join-Path $State 'local-smoke.json')
Write-Output 'PODCODER_LOCAL_SMOKE_PASS'
