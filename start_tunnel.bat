@echo off
title Cloudflare Tunnel - PyMentor
cd /d "%~dp0"
echo Starting Cloudflare Tunnel for PyMentor (http://localhost:8000)...
cloudflared tunnel --protocol http2 run --url http://localhost:8000 pymentor
pause
