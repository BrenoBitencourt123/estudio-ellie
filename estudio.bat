@echo off
cd /d "%~dp0"
rem Liga em segundo plano pelo supervisor (sem janelas, com auto-atualizacao). Sem pythonw, usa o iniciador antigo.
where pythonw >nul 2>nul
if not errorlevel 1 (
  start "" pythonw "%~dp0studio\supervisor.py" --abrir
  exit /b 0
)
powershell.exe -NoProfile -File "%~dp0iniciar.ps1"
if errorlevel 1 pause
