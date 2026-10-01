# Crow environment aliases. Reads never modify the process environment.
function Get-CrowEnvironmentNames {
    param([Parameter(Mandatory = $true)][string]$Name)
    $canonical = if ($Name.StartsWith('FAPAI_')) { 'CROW_' + $Name.Substring(6) } else { $Name }
    if ($canonical.StartsWith('CROW_')) { return @($canonical, ('FAPAI_' + $canonical.Substring(5))) }
    return @($Name)
}

function Get-CrowEnvironmentValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [AllowNull()][object]$Default = $null,
        [switch]$PathValue,
        [AllowNull()][System.Collections.IDictionary]$Environment = $null
    )
    $names = @(Get-CrowEnvironmentNames -Name $Name)
    $present = [System.Collections.Generic.List[string]]::new()
    foreach ($key in $names) {
        $value = if ($null -ne $Environment) {
            if ($Environment.Contains($key)) { $Environment[$key] } else { $null }
        } else {
            [Environment]::GetEnvironmentVariable($key, 'Process')
        }
        if ($null -ne $value) { $present.Add([string]$value) }
    }
    $conflict = $present.Count -gt 1 -and $present[0] -cne $present[1]
    if ($conflict -and $PathValue -and $present[0] -ne '' -and $present[1] -ne '') {
        $windows = [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT
        if ($windows -and ($present[0] -match '^[A-Za-z]:(?![\\/])' -or $present[1] -match '^[A-Za-z]:(?![\\/])')) {
            throw ('Drive-relative environment path aliases require explicit selection: ' + ($names -join ', '))
        }
        $separators = [char[]]@([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
        try {
            $first = [IO.Path]::GetFullPath($present[0]).TrimEnd($separators)
            $second = [IO.Path]::GetFullPath($present[1]).TrimEnd($separators)
        } catch { throw ('Invalid environment path aliases: ' + ($names -join ', ')) }
        $comparison = if ($windows) {
            [StringComparison]::OrdinalIgnoreCase
        } else { [StringComparison]::Ordinal }
        $conflict = -not [string]::Equals($first, $second, $comparison)
    }
    if ($conflict) {
        throw ('Conflicting environment aliases: ' + ($names -join ', '))
    }
    if ($present.Count -gt 0) { return $present[0] }
    return $Default
}

function Set-CrowEnvironmentValue {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value,
        [AllowNull()][System.Collections.IDictionary]$Environment = $null
    )
    foreach ($key in @(Get-CrowEnvironmentNames -Name $Name)) {
        if ($null -ne $Environment) { $Environment[$key] = $Value }
        else { [Environment]::SetEnvironmentVariable($key, $Value, 'Process') }
    }
}

function ConvertTo-CrowEnvironmentMap {
    param([AllowNull()][object]$Value)
    if ($Value -is [System.Collections.IDictionary]) { return $Value }
    $result = @{}
    if ($null -ne $Value) {
        foreach ($property in $Value.PSObject.Properties) { $result[$property.Name] = $property.Value }
    }
    return $result
}
