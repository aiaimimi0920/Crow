. (Join-Path $PSScriptRoot 'crow-environment.ps1')
Set-CrowEnvironmentValue -Name 'CROW_HOST_ANALYSIS_WORKER_ID' -Value ('pc2-real-analysis-3')
Set-CrowEnvironmentValue -Name 'CROW_HOST_ANALYSIS_OUTPUT_DIR' -Value ('\\192.168.15.200\home\project\project\FPFData\output\nodes\pc2-real\detail_analysis_worker_3')
& 'C:\fapaifang-worker\ops\start-host-direct-analysis-worker.ps1'
