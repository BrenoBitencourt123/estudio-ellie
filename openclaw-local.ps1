param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Comando)
$ErrorActionPreference='Stop'
$candidates=@()
$found=Get-Command node -ErrorAction SilentlyContinue
if($found){$candidates+=$found.Source}
$candidates+=@(Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe')
$nodeExe=$null
foreach($candidate in $candidates){
 if(Test-Path -LiteralPath $candidate){
  $versionText=& $candidate --version
  $runtimeVersion=[version]($versionText.Trim().TrimStart('v'))
  if($LASTEXITCODE -eq 0 -and (($runtimeVersion.Major -eq 24 -and $runtimeVersion.Minor -ge 16) -or ($runtimeVersion.Major -eq 26 -and $runtimeVersion.Minor -ge 1) -or $runtimeVersion.Major -gt 26)){$nodeExe=$candidate;break}
 }
}
if(-not $nodeExe){throw 'Instale Node.js 24.16+ ou 26.1+ antes de abrir o OpenClaw.'}
$launcher=Join-Path $env:APPDATA 'npm\node_modules\openclaw\openclaw.mjs'
if(-not(Test-Path -LiteralPath $launcher)){
 throw 'OpenClaw não encontrado na instalação npm do usuário. Siga o instalador oficial e confira o caminho da sua instalação.'
}
$env:PATH="$(Split-Path -Parent $nodeExe);$env:PATH"
if(-not $Comando){$Comando=@('onboard','--classic')}
& $nodeExe $launcher @Comando
exit $LASTEXITCODE
