. (Join-Path $PSScriptRoot 'crow-environment.ps1')
Set-CrowEnvironmentValue -Name 'CROW_HOST_DETAIL_WORKER_ID' -Value ('pc2-real-detail-2')
Set-CrowEnvironmentValue -Name 'CROW_HOST_DETAIL_OUTPUT_DIR' -Value ('\\192.168.15.200\home\project\project\FPFData\output\nodes\pc2-real\detail_worker_2')
& 'C:\fapaifang-worker\ops\start-host-direct-detail-worker.ps1'
