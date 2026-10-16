# Remove only the retired generated batch and flight diagnostic files.
# Original workbooks, models, activity databases and saved personal plans are excluded.
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\航旅智策应用\runtime'))
$taskTargets = @('independent-evaluation\annual-2026-10-16-v1', 'flight-logs', 'server.log', 'server-error.log')
foreach ($taskRelative in $taskTargets) {
    $taskTarget = [IO.Path]::GetFullPath((Join-Path $taskRoot $taskRelative))
    if (-not $taskTarget.StartsWith($taskRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Target is outside the project runtime'
    }
    if (Test-Path -LiteralPath $taskTarget) {
        Remove-Item -LiteralPath $taskTarget -Recurse -Force
        Write-Host "Removed: $taskRelative"
    }
}
