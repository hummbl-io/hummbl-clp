Write-Host "PWD: $PWD"
$repoPath = 'C:\Users\Owner\PROJECTS\hummbl-clp'

# Try direct command
$cmd = "git -C `"$repoPath`" log --since=2025-01-01 --until=2026-09-30 --pretty=format:'%H|%P|%an|%ae|%ci|%s' --all --reverse -n 5"
Write-Host "Command: $cmd"
$gitLog = Invoke-Expression $cmd 2>$null
Write-Host "GitLog is null: $($null -eq $gitLog)"
Write-Host "GitLog length: $($gitLog.Length)"
Write-Host "GitLog: '$gitLog'"