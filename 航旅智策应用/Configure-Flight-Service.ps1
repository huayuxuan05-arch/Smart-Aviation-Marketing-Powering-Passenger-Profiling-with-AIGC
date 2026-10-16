$ErrorActionPreference='Stop'
$taskPython=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Please prepare the project environment first.' }
& $taskPython (Join-Path $PSScriptRoot 'configure_flight_service.py')
