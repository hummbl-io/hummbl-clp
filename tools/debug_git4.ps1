Write-Host "PWD: $PWD"
$repoPath = 'C:\Users\Owner\PROJECTS\hummbl-clp'

# Add %n for newline at end of format
$cmd = "git -C `"$repoPath`" log --since=2025-01-01 --until=2026-09-30 --pretty=format:'%H|%P|%an|%ae|%ci|%s%n' --all --reverse -n 5"
Write-Host "Command: $cmd"
$gitLog = Invoke-Expression $cmd 2>$null
Write-Host "GitLog is null: $($null -eq $gitLog)"
Write-Host "GitLog length: $($gitLog.Length)"
$lines = $gitLog.Split("`n")
Write-Host "Line count: $($lines.Count)"
foreach ($line in $lines) {
    if ($line.Trim()) {
        Write-Host "Line: '$line'"
        $parts = $line -split "\|", 6
        Write-Host "Parts: $($parts.Count)"
    }
}