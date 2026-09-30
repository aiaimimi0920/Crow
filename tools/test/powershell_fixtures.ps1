# Test-only host: each request gets a new runspace; never run operational bodies.
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
while ($null -ne ($line = [Console]::ReadLine())) {
    $request = $line | ConvertFrom-Json
    $before = [Collections.Generic.Dictionary[string,string]]::new([StringComparer]::Ordinal)
    Get-ChildItem Env: | ForEach-Object { $before[$_.Name] = $_.Value }
    $directory = [Environment]::CurrentDirectory
    $runner = [PowerShell]::Create()
    $result = @{code=0;stdout='';stderr=''}
    try {
        # Preserve subprocess inheritance at request time, including monkeypatches.
        Get-ChildItem Env: | ForEach-Object { Remove-Item -LiteralPath ('Env:' + $_.Name) }
        foreach($entry in $request.environment) {
            [Environment]::SetEnvironmentVariable($entry.Name,[string]$entry.Value)
        }
        $sourceText = if($request.mode -eq '-File') { [IO.File]::ReadAllText($request.source) } else { $request.source }
        $tokens=$null; $parseErrors=$null
        $syntax=[Management.Automation.Language.Parser]::ParseInput($sourceText,[ref]$tokens,[ref]$parseErrors)
        if($syntax.Find({param($node) $node -is [Management.Automation.Language.ExitStatementAst]},$true)) {
            throw 'Exit statements are unsupported in shared pure fixtures'
        }
        [void]$runner.AddScript('param($location,$mode,$source)
$ErrorActionPreference="Stop"
$global:LASTEXITCODE=0
Set-Location -LiteralPath $location
[Environment]::CurrentDirectory=$location
if($mode -eq "-File") { & $source } else { & ([ScriptBlock]::Create($source)) }
').AddArgument($request.cwd).AddArgument($request.mode).AddArgument($request.source)
        $output = $runner.Invoke()
        $result.stdout = (($output | ForEach-Object { [string]$_ }) -join "`n")
        $nativeCode=$runner.Runspace.SessionStateProxy.GetVariable('LASTEXITCODE')
        if($nativeCode) { $result.code=[int]$nativeCode; $result.stderr='Native fixture command failed' }
        if($runner.HadErrors) {
            $result.code=1
            $result.stderr=($runner.Streams.Error | Out-String)
        }
    } catch {
        $result.code=1
        $result.stderr=$_.Exception.Message
    } finally {
        $runner.Dispose()
        # Environment variables are process-wide, unlike runspace variables/functions.
        Get-ChildItem Env: | ForEach-Object {
            if(-not $before.ContainsKey($_.Name)) { Remove-Item -LiteralPath ('Env:' + $_.Name) }
        }
        foreach($name in $before.Keys) {
            if([Environment]::GetEnvironmentVariable($name) -cne $before[$name]) {
                [Environment]::SetEnvironmentVariable($name,$before[$name])
            }
        }
        [Environment]::CurrentDirectory=$directory
    }
    [Console]::WriteLine(($result | ConvertTo-Json -Compress))
}
