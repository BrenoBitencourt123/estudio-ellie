param([string]$Python='python',[string]$Node='node',[switch]$Desenvolvimento)
$ErrorActionPreference='Stop'
$root=$PSScriptRoot
Set-Location -LiteralPath $root
$pythonExe=(Get-Command $Python -ErrorAction Stop).Source
# Procura um Node 24+: o do PATH ou o que vem com o Codex (o mesmo que o openclaw-local.ps1 usa)
$nodeCandidates=@()
$nodeFound=Get-Command $Node -ErrorAction SilentlyContinue
if($nodeFound){$nodeCandidates+=$nodeFound.Source}
$nodeCandidates+=@(Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe')
$nodeExe=$null
foreach($candidate in $nodeCandidates){
 if(Test-Path -LiteralPath $candidate){
  $nodeVersion=[version]((& $candidate --version).Trim().TrimStart('v'))
  if($nodeVersion.Major -ge 24){$nodeExe=$candidate;break}
 }
}
if(-not $nodeExe){throw 'Instale Node.js 24 ou superior (a ponte OpenClaw usa TypeScript nativo).'}
& $pythonExe -c 'import fastapi,uvicorn,PIL,requests,multipart'
if($LASTEXITCODE -ne 0){throw 'Instale as dependências: python -m pip install -r requirements.txt'}
if(Test-Path -LiteralPath (Join-Path $root '.env')){
 foreach($line in Get-Content -LiteralPath (Join-Path $root '.env')){
  if($line -match '^(OPENCLAW_AGENTE|OPENCLAW_URL|OPENCLAW_AGENTE_CHAT|OPENCLAW_AGENTE_RESERVA|DREAMINA_CLI)=(.*)$'){
   [Environment]::SetEnvironmentVariable($Matches[1],$Matches[2].Trim().Trim('"'), 'Process')
  }
 }
}
if($Desenvolvimento -and -not(Test-Path -LiteralPath 'studio\web\node_modules')){throw 'Instale a interface: cd studio/web; npm ci'}
if(-not $Desenvolvimento -and -not(Test-Path -LiteralPath 'studio\web\dist\index.html')){throw 'Falta a interface compilada. Rode instalar.ps1 ou compile em studio/web.'}
if(-not(Test-Path -LiteralPath 'studio\mcp\node_modules')){throw 'Instale a ponte: cd studio/mcp; npm ci'}
$ports=if($Desenvolvimento){@(8000,5173,8790)}else{@(8000,8790)}
foreach($port in $ports){
 if(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue){throw "A porta $port já está em uso. Use a instância aberta ou encerre-a antes de iniciar outra."}
}
$logs=Join-Path $root 'studio\dados\logs'
New-Item -ItemType Directory -Force -Path $logs|Out-Null
$api=Start-Process -FilePath $pythonExe -ArgumentList @('-m','uvicorn','studio.server:app','--host','127.0.0.1','--port','8000') -WorkingDirectory $root -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'api.log') -RedirectStandardError (Join-Path $logs 'api-error.log')
$web=$null
if($Desenvolvimento){$web=Start-Process -FilePath $nodeExe -ArgumentList @('node_modules/vite/bin/vite.js','--host','127.0.0.1') -WorkingDirectory (Join-Path $root 'studio\web') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'web.log') -RedirectStandardError (Join-Path $logs 'web-error.log')}
$bridge=Start-Process -FilePath $nodeExe -ArgumentList @('src/index.ts') -WorkingDirectory (Join-Path $root 'studio\mcp') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'ponte.log') -RedirectStandardError (Join-Path $logs 'ponte-error.log')
@{api=$api.Id;interface=$web.Id;ponte=$bridge.Id;inicio=(Get-Date).ToString('o')}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $logs 'processos.json')
$url=if($Desenvolvimento){'http://127.0.0.1:5173'}else{'http://127.0.0.1:8000'}
Write-Host "Estúdio iniciado: $url. O OpenClaw/Gateway deve estar aberto com sua assinatura."
Start-Process $url
