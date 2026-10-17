# Centaur-SE Corpus Pilot Extraction - PowerShell Version (Fast)
# Very reduced commit limit for speed

$pilotRepos = @(
    "hummbl-clp",
    "agents",
    "hummbl-bus",
    "hummbl-graphs",
    "hummbl-skills",
    "hummbl-intel",
    "hummbl-omnimeta",
    "hummbl-governance-intelligence",
    "hummbl-governance-kernel",
    "governance-as-code"
)

$basePath = "C:\Users\Owner\PROJECTS"
$outputDir = "C:\Users\Owner\AppData\Local\Temp\centaur-se-pilot"
$dateStart = "2025-01-01"
$dateEnd = "2026-09-30"
$salt = "centaur-se-pilot-v1-20261009"
$maxCommitsPerRepo = 50  # Very reduced for speed

if (-not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}

function Get-HashActor($email) {
    $input = $salt + ":" + $email
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($input)
    $hash = [System.Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
    return (-join ($hash | ForEach-Object { '{0:x2}' -f $_ })).Substring(0, 16)
}

function Get-HashEvent($repoName, $commitHash) {
    $input = $repoName + ":" + $commitHash
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($input)
    $hash = [System.Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
    return (-join ($hash | ForEach-Object { '{0:x2}' -f $_ })).Substring(0, 24)
}

function Run-Git($repoPath, $cmd) {
    $fullCmd = "git -C `"$repoPath`" " + $cmd
    $result = Invoke-Expression $fullCmd 2>$null
    if ($null -eq $result) { return "" }
    return $result
}

$allEvents = @()
$repoStats = @{}

foreach ($repoName in $pilotRepos) {
    Write-Host "=== Extracting $repoName ==="
    $repoPath = Join-Path $basePath $repoName

    if (-not (Test-Path $repoPath)) {
        Write-Host "  Repo not found: $repoPath"
        continue
    }

    # Get commits
    $logCmd = "log --since=$dateStart --until=$dateEnd --pretty=format:'%H|%P|%an|%ae|%ci|%s%n' --all --reverse -n $maxCommitsPerRepo"
    $gitLog = Run-Git $repoPath $logCmd

    if (-not $gitLog) {
        Write-Host "  No commits found"
        $repoStats[$repoName] = 0
        continue
    }

    # Get tags
    $gitTags = Run-Git $repoPath 'tag --format="%(refname:short)|%(objectname)"'
    $tagMap = @{}
    if ($gitTags) {
        $gitTags.Split("`n") | Where-Object { $_ -match "\|" } | ForEach-Object {
            $parts = $_ -split "\|", 2
            $tagMap[$parts[1]] = $parts[0]
        }
    }

    # Get branches
    $gitBranches = Run-Git $repoPath 'for-each-ref --format="%(objectname)|%(refname:short)" refs/heads/ refs/remotes/'
    $branchMap = @{}
    if ($gitBranches) {
        $gitBranches.Split("`n") | Where-Object { $_ -match "\|" } | ForEach-Object {
            $parts = $_ -split "\|", 2
            if (-not $branchMap.ContainsKey($parts[0])) {
                $branchMap[$parts[0]] = @()
            }
            $branchMap[$parts[0]] += $parts[1]
        }
    }

    $lines = $gitLog.Split("`n")
    Write-Host "  Processing $($lines.Count) lines..."

    $count = 0
    foreach ($line in $lines) {
        if (-not $line.Trim()) { continue }
        $parts = $line -split "\|", 6
        if ($parts.Count -lt 6) { continue }

        $commitHash = $parts[0]
        $parentsStr = $parts[1]
        $authorName = $parts[2]
        $authorEmail = $parts[3]
        $timestamp = $parts[4]
        $subject = $parts[5]

        $parents = $parentsStr.Split(" ", [StringSplitOptions]::RemoveEmptyEntries)
        $isMerge = $parents.Count -gt 1
        $eventType = if ($tagMap.ContainsKey($commitHash)) { "tag" } elseif ($isMerge) { "merge" } else { "commit" }
        $branch = if ($branchMap.ContainsKey($commitHash)) { $branchMap[$commitHash][0] } else { "unknown" }
        $message = $subject

        # Get diff stats (batched - single call per commit)
        $statOutput = Run-Git $repoPath ("show --stat --oneline " + $commitHash)
        $filesChanged = 0
        $insertions = 0
        $deletions = 0

        if ($statOutput) {
            foreach ($statLine in $statOutput.Split("`n")) {
                if ($statLine -match "(\d+) files? changed") { $filesChanged = [int]$matches[1] }
                if ($statLine -match "(\d+) insertions?") { $insertions = [int]$matches[1] }
                if ($statLine -match "(\d+) deletions?") { $deletions = [int]$matches[1] }
            }
        }

        # Get file names
        $nameOutput = Run-Git $repoPath ("show --name-only --oneline " + $commitHash)
        $changedFiles = @()
        if ($nameOutput) {
            foreach ($f in $nameOutput.Split("`n")) {
                $f = $f.Trim()
                if ($f -and -not $f.StartsWith("commit")) {
                    $changedFiles += $f
                }
            }
        }

        $eventId = Get-HashEvent $repoName $commitHash
        $actorHash = Get-HashActor $authorEmail

        $event = @{
            event_id = $eventId
            repo = $repoName
            event_type = $eventType
            timestamp_utc = $timestamp
            actor_hash = $actorHash
            commit_hash = $commitHash
            parent_hashes = $parents
            message = $message
            files_changed = $filesChanged
            insertions = $insertions
            deletions = $deletions
            is_merge = $isMerge
            branch = $branch
            diff_stats = @{
                files = $changedFiles[0..([Math]::Min(49, $changedFiles.Count - 1))]
                file_count = $changedFiles.Count
            }
        }

        $allEvents += $event
        $count++
    }

    $repoStats[$repoName] = $count
    Write-Host "  Extracted $count events"
}

Write-Host "`nTotal events: $($allEvents.Count)"

# Save as JSON
$outputFile = Join-Path $outputDir "events.json"
$allEvents | ConvertTo-Json -Depth 5 | Set-Content $outputFile -Encoding UTF8
Write-Host "Saved to $outputFile"

# Metadata
$meta = @{
    extraction_date = (Get-Date).ToUniversalTime().ToString("o")
    date_range = $dateStart + " to " + $dateEnd
    repos = $pilotRepos
    repo_stats = $repoStats
    total_events = $allEvents.Count
    max_commits_per_repo = $maxCommitsPerRepo
    schema_version = "1.0"
    salt = $salt
}
$metaFile = Join-Path $outputDir "metadata.json"
$meta | ConvertTo-Json -Depth 3 | Set-Content $metaFile -Encoding UTF8
Write-Host "Metadata saved to $metaFile"

# Summary
Write-Host "`n=== VALIDATION REPORT ==="
Write-Host "Event count: $($allEvents.Count)"
$uniqueRepos = $allEvents | Select-Object -ExpandProperty repo -Unique | Measure-Object
Write-Host "Repos covered: $($uniqueRepos.Count)"
$dates = $allEvents | Select-Object -ExpandProperty timestamp_utc | ForEach-Object { [DateTime]::Parse($_) }
Write-Host "Date range: $($dates | Measure-Object -Minimum).Minimum to $($dates | Measure-Object -Maximum).Maximum"
$eventTypes = $allEvents | Group-Object event_type
$typeStr = ""
foreach ($g in $eventTypes) { $typeStr += "$($g.Name)=$($g.Count), " }
Write-Host "Event types: $($typeStr.TrimEnd(', '))"
$uniqueActors = $allEvents | Select-Object -ExpandProperty actor_hash -Unique | Measure-Object
Write-Host "Unique actors: $($uniqueActors.Count)"
$mergeCount = $allEvents | Where-Object { $_.is_merge } | Measure-Object
Write-Host "Merge commits: $($mergeCount.Count)"
$avgFiles = [Math]::Round(($allEvents | Measure-Object -Property files_changed -Average).Average, 1)
Write-Host "Avg files/commit: $avgFiles"

Write-Host "`nPer-repo:"
foreach ($repo in $pilotRepos) {
    $repoEvents = $allEvents | Where-Object { $_.repo -eq $repo }
    if ($repoEvents.Count -gt 0) {
        $repoDates = $repoEvents | Select-Object -ExpandProperty timestamp_utc | ForEach-Object { [DateTime]::Parse($_) }
        $repoActors = $repoEvents | Select-Object -ExpandProperty actor_hash -Unique | Measure-Object
        Write-Host ("  {0}: {1} events, {2} actors, {3} to {4}" -f $repo, $repoEvents.Count, $repoActors.Count, ($repoDates | Measure-Object -Minimum).Minimum, ($repoDates | Measure-Object -Maximum).Maximum)
    } else {
        Write-Host ("  {0}: 0 events" -f $repo)
    }
}