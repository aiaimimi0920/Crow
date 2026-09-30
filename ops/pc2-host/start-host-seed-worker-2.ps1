. (Join-Path $PSScriptRoot 'crow-environment.ps1')
Set-CrowEnvironmentValue -Name 'CROW_HOST_SEED_WORKER_ID' -Value ('pc2-host-seed-2')
& 'C:\fapaifang-worker\ops\start-host-seed-worker.ps1'
