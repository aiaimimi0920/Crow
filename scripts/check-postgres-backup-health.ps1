param(
    [string]$DataRoot = "",
    [int]$MaxAgeMinutes = 30,
    [long]$MinBytes = 1048576,
    [string]$TaskName = "FapaiFangPostgresBackup",
    [string]$TaskPath = "\FapaiFang\",
    [string]$VerifierImage = "postgres:16-alpine",
    [int]$CommandTimeoutSeconds = 300,
    [switch]$SkipRestoreList
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "project-data-root.ps1")
$DataRoot = Resolve-CrowProjectDataRoot -RepoRoot (Join-Path $PSScriptRoot "..") -ExplicitRoot $DataRoot

function ConvertTo-ProcessArgument {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Argument)

    if ($Argument -notmatch '[\s"]') {
        return $Argument
    }

    $builder = [System.Text.StringBuilder]::new()
    $null = $builder.Append('"')
    $backslashes = 0
    foreach ($char in $Argument.ToCharArray()) {
        if ($char -eq '\') {
            $backslashes += 1
            continue
        }

        if ($char -eq '"') {
            $null = $builder.Append('\' * (($backslashes * 2) + 1))
            $null = $builder.Append('"')
            $backslashes = 0
            continue
        }

        if ($backslashes -gt 0) {
            $null = $builder.Append('\' * $backslashes)
            $backslashes = 0
        }
        $null = $builder.Append($char)
    }

    if ($backslashes -gt 0) {
        $null = $builder.Append('\' * ($backslashes * 2))
    }
    $null = $builder.Append('"')
    return $builder.ToString()
}

function Invoke-DockerCommand {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [string]$Description = "docker command",
        [switch]$IgnoreExitCode
    )

    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $process.StartInfo.FileName = "docker"
    $process.StartInfo.Arguments = ($Arguments | ForEach-Object { ConvertTo-ProcessArgument $_ }) -join " "
    $process.StartInfo.UseShellExecute = $false
    $process.StartInfo.RedirectStandardOutput = $true
    $process.StartInfo.RedirectStandardError = $true
    $process.StartInfo.CreateNoWindow = $true

    try {
        $null = $process.Start()
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()

        if (-not $process.WaitForExit($CommandTimeoutSeconds * 1000)) {
            try {
                $process.Kill()
            }
            catch {
                Write-Warning "Failed to kill timed-out docker process for ${Description}: $($_.Exception.Message)"
            }
            throw "$Description timed out after $CommandTimeoutSeconds seconds."
        }
        $process.WaitForExit()

        $stdout = $stdoutTask.Result
        $stderr = $stderrTask.Result
        if ($stdout) {
            Write-Output $stdout.TrimEnd()
        }
        if ($stderr) {
            Write-Error $stderr.TrimEnd() -ErrorAction Continue
        }

        if (-not $IgnoreExitCode -and $process.ExitCode -ne 0) {
            throw "$Description failed with exit code $($process.ExitCode)."
        }
    }
    finally {
        $process.Dispose()
    }
}

if ($MaxAgeMinutes -lt 1) {
    throw "MaxAgeMinutes must be at least 1."
}

if ($MinBytes -lt 1) {
    throw "MinBytes must be at least 1."
}

if ($CommandTimeoutSeconds -lt 1) {
    throw "CommandTimeoutSeconds must be at least 1."
}

$task = Get-ScheduledTask -TaskPath $TaskPath -TaskName $TaskName -ErrorAction Stop
$taskInfo = Get-ScheduledTaskInfo -TaskPath $TaskPath -TaskName $TaskName -ErrorAction Stop
if ($task.State -eq "Disabled") {
    throw "Postgres backup task '$TaskPath$TaskName' is disabled."
}

if ($task.State -ne "Running" -and $taskInfo.LastTaskResult -ne 0) {
    throw "Postgres backup task '$TaskPath$TaskName' LastTaskResult is $($taskInfo.LastTaskResult), expected 0."
}

$backupDir = Join-Path $DataRoot "postgres\backups"
if (-not (Test-Path -LiteralPath $backupDir)) {
    throw "Postgres backup directory does not exist: $backupDir"
}

$latest = Get-ChildItem -LiteralPath $backupDir -Filter "fapaifang-*.dump" -File |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (-not $latest) {
    throw "No Postgres backup dump files found under $backupDir"
}

$ageMinutes = ((Get-Date) - $latest.LastWriteTime).TotalMinutes
if ($ageMinutes -gt $MaxAgeMinutes) {
    throw "latest Postgres backup is stale: $($latest.FullName) is $([Math]::Round($ageMinutes, 1)) minutes old, max is $MaxAgeMinutes."
}

if ($latest.Length -lt $MinBytes) {
    throw "Latest Postgres backup is too small: $($latest.FullName) is $($latest.Length) bytes, min is $MinBytes."
}

if (-not $SkipRestoreList) {
    $containerName = "fapaifang-backup-health-" + [guid]::NewGuid().ToString("N")
    try {
        Invoke-DockerCommand `
            -Arguments @("create", "--name", $containerName, $VerifierImage, "sh", "-c", "sleep 300") `
            -Description "docker create for backup verifier" | Out-Null

        Invoke-DockerCommand `
            -Arguments @("cp", $latest.FullName, "${containerName}:/tmp/fapaifang.dump") `
            -Description "docker cp for latest Postgres backup '$($latest.FullName)'" | Out-Null

        Invoke-DockerCommand `
            -Arguments @("start", $containerName) `
            -Description "docker start for backup verifier" | Out-Null

        Invoke-DockerCommand `
            -Arguments @("exec", $containerName, "pg_restore", "-l", "/tmp/fapaifang.dump") `
            -Description "pg_restore -l for latest Postgres backup '$($latest.FullName)'" | Out-Null
    }
    finally {
        Invoke-DockerCommand `
            -Arguments @("rm", "-f", $containerName) `
            -Description "cleanup backup verifier '$containerName'" `
            -IgnoreExitCode | Out-Null
    }
}

Write-Output "Postgres backup health OK."
Write-Output "Latest dump: $($latest.FullName)"
Write-Output "Latest dump size: $($latest.Length) bytes"
Write-Output "Latest dump age: $([Math]::Round($ageMinutes, 1)) minutes"
Write-Output "Task: $TaskPath$TaskName LastTaskResult=$($taskInfo.LastTaskResult) NextRunTime=$($taskInfo.NextRunTime)"
