@echo off
title PyMentor Production Server & Cloudflare Tunnel
cd /d "%~dp0"
echo ========================================================
echo        Starting PyMentor Server & Cloudflare Tunnel
echo ========================================================
echo.
echo [1/2] Launching PyMentor server on http://localhost:8000...
start "PyMentor Server (Port 8000)" cmd /k "call start_pymentor.bat"
echo.
echo Waiting 3 seconds for server to start...
timeout /t 3 /nobreak >nul
echo.
echo [2/2] Launching Cloudflare Tunnel...
start "Cloudflare Tunnel" cmd /k "cloudflared tunnel --protocol http2 run --url http://localhost:8000 pymentor"
echo.
echo ========================================================
echo Both PyMentor and Cloudflare Tunnel are now running!
echo ========================================================
