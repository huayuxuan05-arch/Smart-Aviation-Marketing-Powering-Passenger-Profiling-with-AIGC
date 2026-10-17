# Remove only retired flight diagnostic files.
# Original workbooks, models, activity databases and saved personal plans are excluded.
# Existing simulated cohorts are retained as audited SFT development sources.
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\航旅智策应用\runtime'))
$taskTargets = @('flight-logs')
foreach ($taskRelative in $taskTargets) {
    $taskTarget = [IO.Path]::GetFullPath((Join-Path $taskRoot $taskRelative))
    if (-not $taskTarget.StartsWith($taskRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Target is outside the project runtime'
    }
    if (Test-Path -LiteralPath $taskTarget) {
        $taskItem = Get-Item -LiteralPath $taskTarget -Force
        if ($taskItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Refusing to delete a linked directory'
        }
        if (Get-ChildItem -LiteralPath $taskTarget -Recurse -Force | Where-Object {
            $_.Attributes -band [IO.FileAttributes]::ReparsePoint
        } | Select-Object -First 1) {
            throw 'Refusing recursive deletion through a linked entry'
        }
        Remove-Item -LiteralPath $taskTarget -Recurse -Force
        Write-Host "Removed: $taskRelative"
    }
}
