@echo off
rem Doble clic para crear los accesos directos. Acepta los mismos parametros que el .ps1,
rem por ejemplo:  install_shortcuts_windows.bat -Uninstall
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_shortcuts_windows.ps1" %*
if errorlevel 1 (
    echo.
    echo Hubo un error al crear los accesos directos.
)
pause
