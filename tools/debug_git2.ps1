Write-Host "PWD: $PWD"
Write-Host "Git: $(git --version)"
$repoPath = 'C:\Users\Owner\PROJECTS\hummbl-clp'
Write-Host "Repo exists: $(Test-Path $repoPath)"
Write-Host "Repo .git exists: $(Test-Path (Join-Path $repoPath '.git'))"

$logArgs = @('log', '--since=2025-01-01', '--until=2026-09-30', '--pretty=format:%H|%P|%an|%ae|%ci|%s', '--all', '--reverse', '-n', '5')
Write-Host "Running git with args: $logArgs"
$gitLog = & git -C $repoPath @$logArgs 2>$null
Write-Host "GitLog is null: $($null -eq $gitLog)"
Write-Host "GitLog length: $($gitLog.Length)"
Write-Host "GitLog: '$gitLog'"