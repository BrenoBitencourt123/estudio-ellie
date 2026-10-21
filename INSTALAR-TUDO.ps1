$ErrorActionPreference='Continue'
Set-Location -LiteralPath $PSScriptRoot
$log=Join-Path $PSScriptRoot 'instalacao.log'
Start-Transcript -LiteralPath $log -Force | Out-Null
function Refresh-Path{$env:PATH=[Environment]::GetEnvironmentVariable('PATH','Machine')+';'+[Environment]::GetEnvironmentVariable('PATH','User')}
function Has($c){[bool](Get-Command $c -ErrorAction SilentlyContinue)}
Write-Host '== Verificando requisitos =='
$py=$null
foreach($c in 'python','py'){ if(Has $c){ $v=& $c -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null; if($v -and [version]$v -ge [version]'3.12'){$py=(Get-Command $c).Source;break} } }
if(-not $py){ Write-Host 'Instalando Python 3.12...'; winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements --silent; Refresh-Path; $py=(Get-Command python -ErrorAction SilentlyContinue).Source }
Write-Host "Python: $py"; & $py --version
$nodeOk=$false
if(Has node){ $nv=[version]((node --version).TrimStart('v')); if($nv.Major -ge 25 -or ($nv.Major -eq 24 -and $nv.Minor -ge 16)){$nodeOk=$true} }
if(-not $nodeOk){ Write-Host 'Instalando/atualizando Node.js LTS...'; winget install -e --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements --silent; winget upgrade -e --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements --silent; Refresh-Path }
Write-Host "Node: $(node --version)"
if(-not (Has ffmpeg) -or -not (Has ffprobe)){ Write-Host 'Instalando FFmpeg...'; winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements --silent; Refresh-Path }
Write-Host "FFmpeg: $((Get-Command ffmpeg -ErrorAction SilentlyContinue).Source)"
Write-Host '== Instalando o Estudio =='
& "$PSScriptRoot\instalar.ps1" -Python $py
Write-Host "RESULTADO_INSTALAR: $?"
Write-Host '== Extras =='
$oc=Join-Path $env:APPDATA 'npm\node_modules\openclaw\openclaw.mjs'
Write-Host "OpenClaw instalado: $(Test-Path $oc)"
Write-Host "Config OpenClaw: $(Test-Path (Join-Path $env:USERPROFILE '.openclaw\openclaw.json'))"
$dr=(Get-Command dreamina-canvas -ErrorAction SilentlyContinue).Source; if(-not $dr -and (Test-Path "$env:USERPROFILE\bin\dreamina-canvas.exe")){$dr="$env:USERPROFILE\bin\dreamina-canvas.exe"}
Write-Host "Dreamina CLI: $dr"
Write-Host '== Testes =='
& $py -m unittest discover -s tests 2>&1 | Select-Object -Last 5
Write-Host 'FIM_INSTALACAO'
Stop-Transcript | Out-Null
