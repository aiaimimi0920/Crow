# Pure, read-only management-root selection. Never moves or creates data.
function Resolve-CrowProjectDataRoot {
    param([Parameter(Mandatory = $true)][string]$RepoRoot, [string]$ExplicitRoot = "")
    $RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
    function Convert-RootPath([string]$Value) {
        if (-not [IO.Path]::IsPathRooted($Value)) { $Value = Join-Path $RepoRoot $Value }
        $full = [IO.Path]::GetFullPath($Value)
        if ($full.Length -gt ([IO.Path]::GetPathRoot($full)).Length) {
            $full = $full.TrimEnd([char[]]@([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar))
        }
        return $full
    }
    if (-not [string]::IsNullOrWhiteSpace($ExplicitRoot)) { return Convert-RootPath $ExplicitRoot }
    $keys = @("CROW_DATA_ROOT_HOST", "FAPAI_DATA_ROOT_HOST")
    $values = @{}
    foreach ($key in $keys) {
        $value = [Environment]::GetEnvironmentVariable($key, "Process")
        if (-not [string]::IsNullOrWhiteSpace($value)) { $values[$key] = $value.Trim() }
    }
    if ($values.Count -eq 0) {
        $config = Join-Path $RepoRoot "docker.local.env"
        if (Test-Path -LiteralPath $config) {
            foreach ($line in Get-Content -LiteralPath $config -Encoding UTF8 -ErrorAction Stop) {
                if ($line -cmatch '^\s*(?:export\s+)?(CROW_DATA_ROOT_HOST|FAPAI_DATA_ROOT_HOST)\s*=\s*(.*)$') {
                    $key = $Matches[1]; $value = $Matches[2].Trim()
                    if ($value.StartsWith('"') -or $value.StartsWith("'")) {
                        if ($value -cnotmatch "^([`"'])(.*?)\1(?:\s+#.*)?$") { throw "Invalid quoted $key in docker.local.env" }
                        $value = $Matches[2]
                    } else {
                        $value = ($value -split '\s+#', 2)[0].Trim()
                        if ($value.Contains('"') -or $value.Contains("'")) { throw "Invalid unquoted $key in docker.local.env" }
                    }
                    if ($value.Contains('${') -or $value.Contains('$(') -or $value -match '\$[A-Za-z_]') { throw "Unexpanded $key in docker.local.env; use a literal path" }
                    if ($values.ContainsKey($key) -and $values[$key] -cne $value) { throw "Conflicting duplicate $key in docker.local.env" }
                    $values[$key] = $value
                }
            }
        }
    }
    $paths = @($keys | Where-Object { $values.ContainsKey($_) -and -not [string]::IsNullOrWhiteSpace($values[$_]) } | ForEach-Object { Convert-RootPath $values[$_] })
    if ($paths.Count -gt 1) {
        $comparison = if ([IO.Path]::DirectorySeparatorChar -eq '\') { [StringComparison]::OrdinalIgnoreCase } else { [StringComparison]::Ordinal }
        if (-not [string]::Equals($paths[0], $paths[1], $comparison)) { throw "Conflicting CROW_DATA_ROOT_HOST and FAPAI_DATA_ROOT_HOST; select one root explicitly" }
    }
    if ($paths.Count) { return $paths[0] }
    $roots = @(Get-ChildItem -LiteralPath $RepoRoot -Force -ErrorAction Stop | Where-Object { $_.Name -ieq "CrowData" -or $_.Name -ieq "FPFData" })
    foreach ($name in @("CrowData", "FPFData")) {
        if (@($roots | Where-Object { $_.Name -ieq $name }).Count -gt 1) { throw "Multiple case variants of a runtime data root; select one explicitly" }
    }
    $active = @()
    foreach ($directory in $roots) {
        if (-not $directory.PSIsContainer) { throw "Runtime data root is not a readable directory: $($directory.FullName)" }
        $content = @(Get-ChildItem -LiteralPath $directory.FullName -Force -ErrorAction Stop | Where-Object { $_.PSIsContainer -or ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) -or ($_.Name -cne '.gitignore' -and $_.Name -cne 'README.md') })
        if ($content.Count) { $active += $directory }
    }
    if ($active.Count -gt 1) { throw "CrowData and FPFData both contain runtime data; select one explicitly" }
    if ($active.Count) { return $active[0].FullName }
    $new = @($roots | Where-Object { $_.Name -ieq 'CrowData' })
    if ($new.Count) { return $new[0].FullName }
    return Join-Path $RepoRoot "CrowData"
}
