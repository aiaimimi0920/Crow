param(
    [string]$DataRoot = "",
    [string]$PostgresContainer = "fapaifang-postgres",
    [string]$PostgresDb = "fapaifang",
    [string]$PostgresUser = "fapaifang",
    [string]$PostgresPassword = "",
    [int]$KeepLast = 96,
    [int]$CommandTimeoutSeconds = 900
)
$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot 'project-environment.ps1')
if (-not $PSBoundParameters.ContainsKey('PostgresPassword')) { $PostgresPassword = (Get-CrowEnvironmentValue -Name 'CROW_POSTGRES_PASSWORD') }


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

if ($KeepLast -lt 1) {
    throw "KeepLast must be at least 1."
}

$runningContainer = Invoke-DockerCommand `
    -Arguments @("ps", "-q", "--filter", "name=^/$PostgresContainer$") `
    -Description "checking Postgres container"
if (-not $runningContainer) {
    throw "Postgres container '$PostgresContainer' is not running; cannot create backup."
}

$backupDir = Join-Path $DataRoot "postgres\backups"
New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$tmpPath = "/tmp/fapaifang-$stamp.dump"
$verifyPath = "/tmp/fapaifang-$stamp.verify.dump"
$destPath = Join-Path $backupDir "fapaifang-$stamp.dump"

try {
    Invoke-DockerCommand `
        -Arguments @("exec", "-e", "PGPASSWORD=$PostgresPassword", $PostgresContainer, "pg_dump", "-U", $PostgresUser, "-d", $PostgresDb, "-Fc", "-f", $tmpPath) `
        -Description "pg_dump for container '$PostgresContainer'" | Out-Null

    Invoke-DockerCommand `
        -Arguments @("exec", "-e", "PGPASSWORD=$PostgresPassword", $PostgresContainer, "pg_restore", "-l", $tmpPath) `
        -Description "pg_restore -l for dump '$tmpPath'" | Out-Null

    Invoke-DockerCommand `
        -Arguments @("cp", "${PostgresContainer}:$tmpPath", $destPath) `
        -Description "docker cp for Postgres dump '$tmpPath'" | Out-Null
}
finally {
    Invoke-DockerCommand `
        -Arguments @("exec", $PostgresContainer, "rm", "-f", $tmpPath) `
        -Description "cleanup temporary dump '$tmpPath'" `
        -IgnoreExitCode | Out-Null
}

$backup = Get-Item -LiteralPath $destPath -Force
if ($backup.Length -lt 1024) {
    throw "Postgres backup is unexpectedly small: $destPath ($($backup.Length) bytes)."
}

try {
    Invoke-DockerCommand `
        -Arguments @("cp", $destPath, "${PostgresContainer}:$verifyPath") `
        -Description "docker cp when verifying copied host dump '$destPath'" | Out-Null

    Invoke-DockerCommand `
        -Arguments @("exec", "-e", "PGPASSWORD=$PostgresPassword", $PostgresContainer, "pg_restore", "-l", $verifyPath) `
        -Description "pg_restore -l for copied host dump '$destPath'" | Out-Null
}
finally {
    Invoke-DockerCommand `
        -Arguments @("exec", $PostgresContainer, "rm", "-f", $verifyPath) `
        -Description "cleanup verification dump '$verifyPath'" `
        -IgnoreExitCode | Out-Null
}

Write-Output "Verified Postgres backup written to $destPath ($($backup.Length) bytes)."
Write-Output "Verified copied host dump with pg_restore -l."
Write-Output "All existing Postgres dump files retained under $backupDir; KeepLast no longer deletes backups."
