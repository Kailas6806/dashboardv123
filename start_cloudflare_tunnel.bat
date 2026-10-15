@echo off
title V12 PRO MAX - Cloudflare Tunnel Launcher
cd /d "%~dp0"

echo ===============================================================
echo   V12 PRO MAX - Cloudflare Tunnel Public HTTPS Launcher
echo ===============================================================
echo.

:: Check if cloudflared.exe exists in directory or system PATH
where cloudflared >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set CLOUDFLARED_BIN=cloudflared
    goto :RUN_TUNNEL
)

if exist "cloudflared.exe" (
    set CLOUDFLARED_BIN=.\cloudflared.exe
    goto :RUN_TUNNEL
)

echo [*] cloudflared not found. Downloading official Cloudflare Tunnel client...
powershell -Command "Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile 'cloudflared.exe'"
if not exist "cloudflared.exe" (
    echo [!] Failed to download cloudflared. Please install it manually or check your internet connection.
    pause
    exit /b 1
)
set CLOUDFLARED_BIN=.\cloudflared.exe
echo [+] Cloudflared installed successfully!
echo.

:RUN_TUNNEL
echo [*] Starting Cloudflare Tunnel pointing to Streamlit (http://localhost:8501)...
echo [*] Look for the public https://xxxx.trycloudflare.com link below:
echo.
%CLOUDFLARED_BIN% tunnel --url http://localhost:8501
pause
