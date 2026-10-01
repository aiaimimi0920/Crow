$workerSpecs = @(
  [pscustomobject]@{
    Name = 'seed'
    WorkerId = 'pc2-real-seed-1'
    ScriptPattern = 'tools\seed_collector.py'
    ScriptPath = Join-Path $root 'ops\start-host-direct-seed-worker.ps1'
    SummaryPath = Join-Path $sharedRoot 'output\nodes\pc2-real\seed_collector\seed_collector_summary.json'
    SummaryMaxAgeSeconds = $SeedSummaryMaxAgeSeconds
    StartupGraceSeconds = $StartupGraceSeconds
    RequiresCdp = $collectorRequiresCdp
    IsAnalysis = $false
    # seed_collector performs scope-aware pause handling and can keep scanning
    # while a detail-page challenge waits for manual confirmation.
    StopsWhenCollectionPaused = $false
    StdoutPath = Join-Path $logDir 'seed.out.log'
    StderrPath = Join-Path $logDir 'seed.err.log'
  },
  [pscustomobject]@{
    Name = 'detail-1'
    WorkerId = 'pc2-real-detail-1'
    ScriptPattern = 'tools\detail_worker.py'
    ScriptPath = Join-Path $root 'ops\start-host-direct-detail-worker.ps1'
    SummaryPath = Join-Path $sharedRoot 'output\nodes\pc2-real\detail_worker\detail_worker_summary.json'
    SummaryMaxAgeSeconds = $DetailSummaryMaxAgeSeconds
    StartupGraceSeconds = $StartupGraceSeconds
    RequiresCdp = $collectorRequiresCdp
    IsAnalysis = $false
    StopsWhenCollectionPaused = $true
    StdoutPath = Join-Path $logDir 'detail1.out.log'
    StderrPath = Join-Path $logDir 'detail1.err.log'
  },
  [pscustomobject]@{
    Name = 'detail-2'
    WorkerId = 'pc2-real-detail-2'
    ScriptPattern = 'tools\detail_worker.py'
    ScriptPath = Join-Path $root 'ops\start-host-direct-detail-worker-2.ps1'
    SummaryPath = Join-Path $sharedRoot 'output\nodes\pc2-real\detail_worker_2\detail_worker_summary.json'
    SummaryMaxAgeSeconds = $DetailSummaryMaxAgeSeconds
    StartupGraceSeconds = $StartupGraceSeconds
    RequiresCdp = $collectorRequiresCdp
    IsAnalysis = $false
    StopsWhenCollectionPaused = $true
    StdoutPath = Join-Path $logDir 'detail2.out.log'
    StderrPath = Join-Path $logDir 'detail2.err.log'
  },
  [pscustomobject]@{
    Name = 'analysis-1'
    WorkerId = 'pc2-real-analysis-1'
    ScriptPattern = 'tools\detail_worker.py'
    ScriptPath = Join-Path $root 'ops\start-host-direct-analysis-worker.ps1'
    SummaryPath = Join-Path $sharedRoot 'output\nodes\pc2-real\detail_analysis_worker\detail_worker_summary.json'
    SummaryMaxAgeSeconds = $AnalysisSummaryMaxAgeSeconds
    StartupGraceSeconds = [Math]::Max($StartupGraceSeconds, 420)
    RequiresCdp = $false
    IsAnalysis = $true
    StopsWhenCollectionPaused = $false
    StdoutPath = Join-Path $logDir 'analysis1.out.log'
    StderrPath = Join-Path $logDir 'analysis1.err.log'
  },
  [pscustomobject]@{
    Name = 'analysis-2'
    WorkerId = 'pc2-real-analysis-2'
    ScriptPattern = 'tools\detail_worker.py'
    ScriptPath = Join-Path $root 'ops\start-host-direct-analysis-worker-2.ps1'
    SummaryPath = Join-Path $sharedRoot 'output\nodes\pc2-real\detail_analysis_worker_2\detail_worker_summary.json'
    SummaryMaxAgeSeconds = $AnalysisSummaryMaxAgeSeconds
    StartupGraceSeconds = [Math]::Max($StartupGraceSeconds, 420)
    RequiresCdp = $false
    IsAnalysis = $true
    StopsWhenCollectionPaused = $false
    StdoutPath = Join-Path $logDir 'analysis2.out.log'
    StderrPath = Join-Path $logDir 'analysis2.err.log'
  },
  [pscustomobject]@{
    Name = 'analysis-3'
    WorkerId = 'pc2-real-analysis-3'
    ScriptPattern = 'tools\detail_worker.py'
    ScriptPath = Join-Path $root 'ops\start-host-direct-analysis-worker-3.ps1'
    SummaryPath = Join-Path $sharedRoot 'output\nodes\pc2-real\detail_analysis_worker_3\detail_worker_summary.json'
    SummaryMaxAgeSeconds = $AnalysisSummaryMaxAgeSeconds
    StartupGraceSeconds = [Math]::Max($StartupGraceSeconds, 420)
    RequiresCdp = $false
    IsAnalysis = $true
    StopsWhenCollectionPaused = $false
    StdoutPath = Join-Path $logDir 'analysis3.out.log'
    StderrPath = Join-Path $logDir 'analysis3.err.log'
  },
  [pscustomobject]@{
    Name = 'detail-3-http'
    WorkerId = 'pc2-real-detail-3'
    ScriptPattern = 'tools\detail_worker.py'
    ScriptPath = Join-Path $root 'ops\start-host-direct-detail-worker-3.ps1'
    SummaryPath = Join-Path $sharedRoot 'output\nodes\pc2-real\detail_worker_3\detail_worker_summary.json'
    SummaryMaxAgeSeconds = $DetailSummaryMaxAgeSeconds
    StartupGraceSeconds = $StartupGraceSeconds
    RequiresCdp = $collectorRequiresCdp
    IsAnalysis = $false
    StopsWhenCollectionPaused = $true
    StdoutPath = Join-Path $logDir 'detail3.out.log'
    StderrPath = Join-Path $logDir 'detail3.err.log'
  }
)

function Resolve-WorkerCount {
  param(
    [Parameter(Mandatory = $true)][int]$RequestedCount,
    [Parameter(Mandatory = $true)][string]$EnvironmentName,
    [Parameter(Mandatory = $true)][int]$DefaultCount
  )

  $resolved = $RequestedCount
  if ($resolved -eq 0) {
    $configured = (Get-CrowEnvironmentValue -Name $EnvironmentName)
    if ($configured) {
      if (-not [int]::TryParse($configured, [ref]$resolved)) {
        throw "$EnvironmentName must be an integer."
      }
    } else {
      $resolved = $DefaultCount
    }
  }
  if ($resolved -lt 3 -or $resolved -gt 8) {
    throw "$EnvironmentName must be between 3 and 8."
  }
  return $resolved
}

$DetailWorkerCount = Resolve-WorkerCount `
  -RequestedCount $DetailWorkerCount `
  -EnvironmentName 'CROW_HOST_DETAIL_WORKER_COUNT' `
  -DefaultCount 4
$AnalysisWorkerCount = Resolve-WorkerCount `
  -RequestedCount $AnalysisWorkerCount `
  -EnvironmentName 'CROW_HOST_ANALYSIS_WORKER_COUNT' `
  -DefaultCount 4

for ($index = 4; $index -le $DetailWorkerCount; $index++) {
  $workerId = "pc2-real-detail-$index"
  $outputDir = Join-Path $sharedRoot "output\nodes\pc2-real\detail_worker_$index"
  $workerSpecs += [pscustomobject]@{
    Name = "detail-$index-http"
    WorkerId = $workerId
    ScriptPattern = 'tools\detail_worker.py'
    ScriptPath = Join-Path $root 'ops\start-host-direct-detail-worker.ps1'
    ScriptArguments = @(
      '-RequestedWorkerId', $workerId,
      '-RequestedOutputDir', $outputDir,
      '-BrowserFallbackOverride', '0'
    )
    SummaryPath = Join-Path $outputDir 'detail_worker_summary.json'
    SummaryMaxAgeSeconds = $DetailSummaryMaxAgeSeconds
    StartupGraceSeconds = $StartupGraceSeconds
    RequiresCdp = $collectorRequiresCdp
    IsAnalysis = $false
    StopsWhenCollectionPaused = $true
    StdoutPath = Join-Path $logDir "detail$index.out.log"
    StderrPath = Join-Path $logDir "detail$index.err.log"
  }
}

for ($index = 4; $index -le $AnalysisWorkerCount; $index++) {
  $workerId = "pc2-real-analysis-$index"
  $outputDir = Join-Path $sharedRoot "output\nodes\pc2-real\detail_analysis_worker_$index"
  $workerSpecs += [pscustomobject]@{
    Name = "analysis-$index"
    WorkerId = $workerId
    ScriptPattern = 'tools\detail_worker.py'
    ScriptPath = Join-Path $root 'ops\start-host-direct-analysis-worker.ps1'
    ScriptArguments = @(
      '-RequestedWorkerId', $workerId,
      '-RequestedOutputDir', $outputDir
    )
    SummaryPath = Join-Path $outputDir 'detail_worker_summary.json'
    SummaryMaxAgeSeconds = $AnalysisSummaryMaxAgeSeconds
    StartupGraceSeconds = [Math]::Max($StartupGraceSeconds, 420)
    RequiresCdp = $false
    IsAnalysis = $true
    StopsWhenCollectionPaused = $false
    StdoutPath = Join-Path $logDir "analysis$index.out.log"
    StderrPath = Join-Path $logDir "analysis$index.err.log"
  }
}
