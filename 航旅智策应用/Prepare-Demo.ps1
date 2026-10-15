param([switch]$DataOnly, [switch]$NoBrowser, [switch]$EnableLocalModel)
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
    elseif ($taskLauncher) { & $taskLauncher.Source -3 -m venv $taskVenv }
    else {
        $taskBasePython = Get-Command python -ErrorAction SilentlyContinue
        if (-not $taskBasePython) { throw 'Install Python 3.11+ first, then run this script again.' }
        & $taskBasePython.Source -m venv $taskVenv
    }
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create the project Python environment. Python 3.11+ is required.' }
}
& $taskPython -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11+ required'"
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11+ is required.' }
$taskProxy = $env:HTTPS_PROXY
if (-not $taskProxy) { $taskProxy = $env:https_proxy }
if (-not $taskProxy) { throw 'Configure HTTPS_PROXY/https_proxy before downloading dependencies and release data.' }
& $taskPython -m pip install --disable-pip-version-check --proxy "$taskProxy" -r (Join-Path $PSScriptRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the network and retry.' }
$taskArgs = @((Join-Path $PSScriptRoot 'bootstrap_demo.py'))
if (-not $EnableLocalModel) { $taskArgs += '--data-only' }
& $taskPython @taskArgs
if ($LASTEXITCODE -ne 0) { throw 'Demo preparation failed. Downloads can resume on the next run.' }
$taskMode = if ($EnableLocalModel) { 'local-model' } else { 'template' }
& (Join-Path $PSScriptRoot 'Start-Local.ps1') -NoBrowser:$NoBrowser -GenerationMode $taskMode
