@echo off
title Reiniciar Servicio Huella Digital

echo Deteniendo servicio...
taskkill /IM FingerprintService.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul

echo Iniciando servicio...
start "FactuPOS Fingerprint" "C:\FactuPOS\FingerprintService\FingerprintService.exe"
timeout /t 3 /nobreak >nul

powershell -Command "try { $r = Invoke-WebRequest -Uri 'https://127.0.0.1:52181/status' -UseBasicParsing -SkipCertificateCheck -TimeoutSec 5; Write-Host 'OK:' $r.Content } catch { Write-Host 'No responde' }"
pause
