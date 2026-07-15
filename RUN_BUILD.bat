@echo off
setlocal
cd /d "%~dp0"

echo Starting the PDF Shrinker self-signed build...
echo You can minimize this window while it runs.
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0BUILD_PDF_SHRINKER.ps1"

if errorlevel 1 (
    echo.
    echo Build failed. Review LAST_BUILD_LOG.txt.
    pause
)
