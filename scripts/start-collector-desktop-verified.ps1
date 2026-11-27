param(
    [Parameter(Mandatory)][string]$LauncherPath,
    [Parameter(Mandatory)][string]$ExecutablePath,
    [Parameter(Mandatory)][string]$ExpectedHash
)
$ErrorActionPreference = 'Stop'
$expectedPath = [IO.Path]::GetFullPath($ExecutablePath)
$shell = (Get-Command powershell.exe -ErrorAction Stop).Source
$launcherArgs = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$LauncherPath`""

function Wait-CollectorWindow {
    for ($i = 0; $i -lt 16; $i++) {
        Start-Sleep -Milliseconds 500
        $sessions = @(Get-Process -Name explorer -ErrorAction SilentlyContinue | Select-Object -ExpandProperty SessionId)
        $process = Get-Process -Name fapaifang_collector_desktop -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -eq $expectedPath -and $_.SessionId -in $sessions -and $_.MainWindowHandle -ne 0 } |
            Select-Object -First 1
        if ($process) { return $process }
    }
}

Start-Process -FilePath $shell -ArgumentList $launcherArgs -WorkingDirectory (Split-Path -Parent $expectedPath) -WindowStyle Hidden
$running = Wait-CollectorWindow
if (-not $running) {
    $name = 'CrowDesktopInteractiveLaunch-' + [guid]::NewGuid().ToString('N')
    $action = New-ScheduledTaskAction -Execute $shell -Argument $launcherArgs -WorkingDirectory (Split-Path -Parent $expectedPath)
    $principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $name -Action $action -Principal $principal | Out-Null
    try {
        Start-ScheduledTask -TaskName $name
        $running = Wait-CollectorWindow
    } finally {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
    }
}
if (-not $running) { throw "Crow Desktop interactive window not found at $expectedPath" }
$hash = (Get-FileHash -LiteralPath $running.Path -Algorithm SHA256).Hash
if ($hash -ne $ExpectedHash) { throw "Running Crow Desktop executable hash mismatch ($hash != $ExpectedHash)" }
Write-Output "Verified running PID=$($running.Id) SessionId=$($running.SessionId) SHA256=$hash"
