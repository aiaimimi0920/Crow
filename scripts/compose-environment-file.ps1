# Settings-mode writers retain both names without rewriting unrelated keys.
. (Join-Path $PSScriptRoot 'project-environment.ps1')

function Set-CrowEnvironmentFileValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value,
        [switch]$OnlyIfMissing
    )
    if ($Key -cnotmatch '^[A-Za-z_][A-Za-z0-9_]*$') { throw 'Invalid environment key name' }
    $names = @(Get-CrowEnvironmentNames -Name $Key)
    $pattern = '^\s*(?<export>export\s+)?(?<name>' + (($names | ForEach-Object { [regex]::Escape($_) }) -join '|') + ')\s*=(?<value>.*)$'
    try { $content = if (Test-Path -LiteralPath $Path) { [IO.File]::ReadAllLines($Path) } else { @() } }
    catch { throw ('Unable to read environment keys: ' + ($names -join ', ')) }
    if ($OnlyIfMissing -and @($content | Where-Object { $_ -cmatch $pattern }).Count) { return }
    # Existing mode scripts set literal paths/numbers/flags, not dotenv expressions.
    # Refuse unsupported serialization rather than silently changing a path/value.
    if ($Value -match '[\r\n\x00"'']|\s#|\$[A-Za-z_{(]') {
        throw ('Environment keys require a literal single-line value: ' + ($names -join ', '))
    }
    $seen = @{}
    $exported = $false
    $updated = [System.Collections.Generic.List[string]]::new()
    foreach ($line in $content) {
        if ($line -cmatch $pattern) {
            $name = $Matches["name"]
            $old = $Matches["value"].Trim()
            $prefix = if ($Matches["export"]) { $exported = $true; "export " } else { "" }
            if ($old -match '^["'']' -and $old -notmatch '^(["'']).*\1(?:\s+#.*)?$') {
                throw ('Multiline environment keys require an explicit edit: ' + ($names -join ', '))
            }
            if (-not $seen.ContainsKey($name)) { $updated.Add("$prefix$name=$Value"); $seen[$name] = $true }
        } else { $updated.Add($line) }
    }
    foreach ($name in $names) {
        if (-not $seen.ContainsKey($name)) {
            $prefix = if ($exported) { "export " } else { "" }
            $updated.Add("$prefix$name=$Value")
        }
    }
    try { [IO.File]::WriteAllLines($Path, $updated, (New-Object Text.UTF8Encoding($false))) }
    catch { throw ('Unable to write environment keys: ' + ($names -join ', ')) }
}
