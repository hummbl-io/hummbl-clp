$repoPath = 'C:\Users\Owner\PROJECTS\hummbl-clp'
$logArgs = @('log', '--since=2025-01-01', '--until=2026-09-30', '--pretty=format:%H|%P|%an|%ae|%ci|%s', '--all', '--reverse', '-n', '5')
$gitLog = & git -C $repoPath @$logArgs 2>$null
Write-Host "Type: $($gitLog.GetType().Name)"
Write-Host "Length: $($gitLog.Length)"
Write-Host "First 200 chars: $($gitLog.Substring(0, [Math]::Min(200, $gitLog.Length)))"
Write-Host '---'
$lines = $gitLog.Split("`n")
Write-Host "Line count: $($lines.Count)"
foreach ($line in $lines) {
    Write-Host "Line: '$line'"
    $parts = $line -split "\|", 6
    Write-Host "Parts: $($parts.Count)"
}