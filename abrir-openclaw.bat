@echo off
if exist "%USERPROFILE%\.openclaw\openclaw.json" (
  call "%~dp0openclaw-local.cmd" dashboard
) else (
  call "%~dp0openclaw-local.cmd" onboard --classic
)
pause
