param([switch]$DataOnly, [switch]$NoBrowser, [switch]$EnableLocalModel, [ValidateSet('4b')][string]$Model='4b', [ValidateSet('Auto','CPU','Vulkan','CUDA')][string]$Backend='Auto')
$ErrorActionPreference = 'Stop'
if ($DataOnly -and $EnableLocalModel) { throw 'Use either -DataOnly or -EnableLocalModel.' }
if ([IO.Path]::GetPathRoot($PSScriptRoot) -eq 'C:\') { throw 'Move the repository to D: or another non-C: drive first.' }
$taskRuntime = Join-Path $PSScriptRoot 'runtime'
$taskTemp = Join-Path $taskRuntime 'tmp'
New-Item -ItemType Directory -Path $taskTemp -Force | Out-Null
$env:TEMP = $taskTemp
$env:TMP = $taskTemp
$env:TMPDIR = $taskTemp
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PIP_CACHE_DIR = Join-Path $taskRuntime 'cache\pip'
$env:HF_HOME = Join-Path $taskRuntime 'local_aigc\cache\huggingface'
$env:CUDA_CACHE_PATH = Join-Path $taskRuntime 'local_aigc\cache\cuda'
$taskVenv = Join-Path $PSScriptRoot '.venv'
$taskPython = Join-Path $taskVenv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    $taskBundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    $taskLauncher = Get-Command py -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $taskBundledPython) { & $taskBundledPython -m venv $taskVenv }
    elseif ($taskLauncher) { & $taskLauncher.Source -3.12 -m venv $taskVenv }
    else {
        $taskBasePython = Get-Command python -ErrorAction SilentlyContinue
        if (-not $taskBasePython) { throw 'Install Python 3.12+ first, then run this script again.' }
        & $taskBasePython.Source -m venv $taskVenv
    }
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create the project Python environment. Python 3.12+ is required.' }
}
& $taskPython -c "import sys; assert sys.version_info >= (3,12), 'Python 3.12+ required'"
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12+ is required.' }
$taskProxy = $env:HTTPS_PROXY
if (-not $taskProxy) { $taskProxy = $env:https_proxy }
if (-not $taskProxy) { throw 'Configure HTTPS_PROXY/https_proxy before downloading dependencies and release data.' }
& $taskPython -m pip install --disable-pip-version-check --proxy "$taskProxy" -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the network and retry.' }
$taskArgs = @((Join-Path $PSScriptRoot 'bootstrap_demo.py'))
if (-not $EnableLocalModel) { $taskArgs += '--data-only' }
if ($EnableLocalModel) {
    $taskArgs += @('--model',$Model,'--backend',$Backend)
}
$taskRunning=$null
try { $taskRunning=Invoke-RestMethod 'http://127.0.0.1:8765/api/health' -TimeoutSec 2 } catch { }
$taskMode=if($EnableLocalModel){'local-model'}else{'template'}
$taskSwitch=$taskRunning -and ($EnableLocalModel -or $taskRunning.generation.mode -ne $taskMode)
if ($taskSwitch) { & (Join-Path $PSScriptRoot 'Stop-Local.ps1') }
& $taskPython @taskArgs
if ($LASTEXITCODE -ne 0) { throw 'Demo preparation failed. Downloads can resume on the next run.' }
& (Join-Path $PSScriptRoot 'Start-Local.ps1') -NoBrowser:$NoBrowser -GenerationMode $taskMode
