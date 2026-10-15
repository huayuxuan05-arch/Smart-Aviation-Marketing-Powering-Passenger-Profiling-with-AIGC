param([int]$Port = 8765, [switch]$NoBrowser, [ValidateSet('template','local-model')][string]$GenerationMode = 'template')
$ErrorActionPreference = 'Stop'
$taskRuntime = Join-Path $PSScriptRoot 'runtime'
New-Item -ItemType Directory -Path $taskRuntime -Force | Out-Null
$taskTemp = Join-Path $taskRuntime 'tmp'
New-Item -ItemType Directory -Path $taskTemp -Force | Out-Null
$env:TEMP = $taskTemp
$env:TMP = $taskTemp
$env:TMPDIR = $taskTemp
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:AEROLENS_GENERATION_MODE = $GenerationMode
$env:HF_HOME = Join-Path $taskRuntime 'local_aigc\cache\huggingface'
$env:CUDA_CACHE_PATH = Join-Path $taskRuntime 'local_aigc\cache\cuda'
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    $taskPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
}
if (-not (Test-Path -LiteralPath $taskPython)) {
    $taskCommand = Get-Command python -ErrorAction Stop
    $taskPython = $taskCommand.Source
}
$taskUrl = "http://127.0.0.1:$Port"
$taskHealth = $null
try { $taskHealth = Invoke-RestMethod "$taskUrl/api/health" -TimeoutSec 2 } catch { }
if ($taskHealth -and $taskHealth.application -eq 'aerolens') {
    if ($taskHealth.generation.mode -ne $GenerationMode) { throw 'Running service uses another generation mode. Stop it with Stop-Local.ps1 before restarting.' }
    Write-Host "Already running: $taskUrl"
    if (-not $NoBrowser) { Start-Process $taskUrl }
    exit 0
}
if ($taskHealth) { throw 'Port belongs to another application. Use -Port 8766.' }
& $taskPython (Join-Path $PSScriptRoot 'build_data.py')
if ($LASTEXITCODE -ne 0) { throw 'Data indexing failed. See the message above.' }
$taskServer = Join-Path $PSScriptRoot 'server.py'
$taskProc = Start-Process -FilePath $taskPython -ArgumentList @('-u', ('"' + $taskServer + '"'), '--port', "$Port") -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskRuntime 'server.log') -RedirectStandardError (Join-Path $taskRuntime 'server-error.log') -PassThru
$taskProcessInfo = @{ pid=$taskProc.Id; port=$Port; server=$taskServer; generation_mode=$GenerationMode; started=(Get-Date).ToString('o') }
$taskProcessInfo | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskRuntime 'server-process.json') -Encoding UTF8
for ($taskAttempt=0; $taskAttempt -lt 30; $taskAttempt++) {
    Start-Sleep -Milliseconds 500
    if ($taskProc.HasExited) { throw 'Server exited. See runtime/server-error.log.' }
    try {
        $taskHealth = Invoke-RestMethod "$taskUrl/api/health" -TimeoutSec 2
        if ($taskHealth.application -eq 'aerolens') {
            # Windows virtual environments may use a launcher process. Track the serving process.
            $taskProcessInfo.pid = [int]$taskHealth.process_id
            $taskProcessInfo | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $taskRuntime 'server-process.json') -Encoding UTF8
            Write-Host "AeroLens local site: $taskUrl"
            if (-not $NoBrowser) { Start-Process $taskUrl }
            exit 0
        }
    } catch { }
}
throw 'Server did not become ready. See runtime/server-error.log.'
