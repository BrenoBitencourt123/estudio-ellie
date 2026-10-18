param([string]$Python='python')
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
& $Python -m pip install -r requirements.txt
if($LASTEXITCODE -ne 0){throw 'A instalação das dependências Python falhou.'}
Push-Location 'studio\mcp'
try{npm.cmd ci --no-audit --no-fund;if($LASTEXITCODE -ne 0){throw 'A instalação da ponte falhou.'}}finally{Pop-Location}
if(-not(Test-Path -LiteralPath 'studio\web\dist\index.html')){
 Push-Location 'studio\web'
 try{npm.cmd ci --no-audit --no-fund;if($LASTEXITCODE -ne 0){throw 'A instalação da interface falhou.'};npm.cmd run build;if($LASTEXITCODE -ne 0){throw 'A compilação falhou.'}}finally{Pop-Location}
}
if(-not(Test-Path -LiteralPath '.env')){Copy-Item -LiteralPath '.env.example' -Destination '.env'}
Write-Host 'Dependências prontas. Conecte a assinatura no OpenClaw e rode python configurar_openclaw.py para ver o registro do agente.'
