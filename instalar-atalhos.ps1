# Cria os atalhos do Estúdio Ellie (rode uma vez):
#  - "Estúdio Ellie" na área de trabalho: liga em segundo plano e abre no navegador
#  - "Parar Estúdio Ellie" na área de trabalho
#  - Inicialização do Windows: liga sozinho em segundo plano ao entrar no PC (use -SemIniciarComWindows para não criar)
param([switch]$SemIniciarComWindows)
$ErrorActionPreference='Stop'
$root=$PSScriptRoot
$pythonw=(Get-Command pythonw -ErrorAction SilentlyContinue).Source
if(-not $pythonw){
 $python=(Get-Command python -ErrorAction Stop).Source
 $pythonw=Join-Path (Split-Path -Parent $python) 'pythonw.exe'
}
if(-not(Test-Path -LiteralPath $pythonw)){throw 'pythonw.exe não encontrado. Confira a instalação do Python.'}
& (Join-Path (Split-Path -Parent $pythonw) 'python.exe') -c 'import fastapi,uvicorn,PIL,requests,multipart'
if($LASTEXITCODE -ne 0){throw 'Instale as dependências: python -m pip install -r requirements.txt'}
$supervisor=Join-Path $root 'studio\supervisor.py'
$shell=New-Object -ComObject WScript.Shell
function Novo-Atalho($caminho,$argumentos,$descricao){
 $a=$shell.CreateShortcut($caminho)
 $a.TargetPath=$pythonw
 $a.Arguments="`"$supervisor`" $argumentos"
 $a.WorkingDirectory=$root
 $a.Description=$descricao
 $a.Save()
 Write-Host "Criado: $caminho"
}
$desktop=[Environment]::GetFolderPath('Desktop')
Novo-Atalho (Join-Path $desktop 'Estúdio Ellie.lnk') '--abrir' 'Liga o Estúdio Ellie em segundo plano e abre no navegador'
Novo-Atalho (Join-Path $desktop 'Parar Estúdio Ellie.lnk') '--parar' 'Encerra o Estúdio Ellie'
if(-not $SemIniciarComWindows){
 Novo-Atalho (Join-Path ([Environment]::GetFolderPath('Startup')) 'Estúdio Ellie.lnk') '' 'Liga o Estúdio Ellie em segundo plano ao entrar no Windows'
}
Write-Host 'Pronto. Use o atalho "Estúdio Ellie" na área de trabalho.'
