$ErrorActionPreference = 'Stop'
$taskModelRecord = Join-Path $PSScriptRoot 'runtime\local_aigc\process.json'
if (Test-Path -LiteralPath $taskModelRecord) {
    $taskModelInfo = Get-Content -LiteralPath $taskModelRecord -Raw | ConvertFrom-Json
    $taskModelAllowed = @((Join-Path $PSScriptRoot 'runtime\local_aigc\llama\llama-server.exe'), (Join-Path $PSScriptRoot 'runtime\local_aigc\llama-cuda\llama-server.exe'))
    $taskModelProc = Get-CimInstance Win32_Process -Filter "ProcessId=$($taskModelInfo.pid)" -ErrorAction SilentlyContinue
    if ($taskModelProc) {
        if ($taskModelInfo.exe -notin $taskModelAllowed -or $taskModelProc.ExecutablePath -ne $taskModelInfo.exe) {
            throw 'Local model PID belongs to another process; no action taken.'
        }
        Stop-Process -Id $taskModelInfo.pid
    }
    Remove-Item -LiteralPath $taskModelRecord
}
$taskRecord = Join-Path $PSScriptRoot 'runtime\server-process.json'
if (-not (Test-Path -LiteralPath $taskRecord)) { Write-Host 'No managed local server.'; exit 0 }
$taskInfo = Get-Content -LiteralPath $taskRecord -Raw | ConvertFrom-Json
$taskProc = Get-CimInstance Win32_Process -Filter "ProcessId=$($taskInfo.pid)" -ErrorAction SilentlyContinue
$taskExpected = Join-Path $PSScriptRoot 'server.py'
if ($taskProc -and $taskProc.CommandLine.Contains($taskExpected) -and $taskInfo.server -eq $taskExpected) {
    Stop-Process -Id $taskInfo.pid
    Remove-Item -LiteralPath $taskRecord
    Write-Host 'AeroLens stopped. Research data is retained.'
} elseif ($taskProc) {
    throw 'PID belongs to another process; no action taken.'
} else {
    Remove-Item -LiteralPath $taskRecord
    Write-Host 'Server already stopped.'
}
