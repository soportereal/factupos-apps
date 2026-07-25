@echo off
title FactuPOS - Instalador Huella Digital
color 0A

echo.
echo ==========================================
echo  FactuPOS - Fingerprint Service v1.0
echo  Digital Persona U.are.U 4500
echo ==========================================
echo.

:: Verificar permisos de administrador
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Ejecute como Administrador
    echo Click derecho ^> Ejecutar como administrador
    echo.
    pause
    exit /b 1
)

set INSTALL_DIR=C:\FactuPOS\FingerprintService
set CSC=C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe

echo [1/6] Verificando lector USB...
wmic path Win32_PnPEntity where "DeviceID like '%%05BA%%'" get Name 2>nul | findstr /i "digital finger" >nul
if %errorlevel% equ 0 (
    echo       Lector detectado OK
) else (
    echo       [AVISO] Lector no detectado. Conectelo antes de usar.
)

echo.
echo [2/6] Instalando driver DigitalPersona...
if exist "%~dp0drivers\dpinst64.exe" (
    start /wait "%~dp0drivers\dpinst64.exe" /S
    echo       Driver instalado
) else (
    echo       [AVISO] Carpeta drivers\ no encontrada.
    echo       Descargue drivers de: https://www.hidglobal.com/drivers
)

echo.
echo [3/6] Creando directorio de instalacion...
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"
if not exist "%INSTALL_DIR%\prints" mkdir "%INSTALL_DIR%\prints"

:: Copiar DLLs del SDK
echo       Copiando DLLs del SDK...
if exist "%~dp0sdk\DPFPDevNET.dll" (
    copy /Y "%~dp0sdk\DPFPDevNET.dll" "%INSTALL_DIR%\" >nul
    copy /Y "%~dp0sdk\DPFPShrNET.dll" "%INSTALL_DIR%\" >nul
    copy /Y "%~dp0sdk\DPFPEngNET.dll" "%INSTALL_DIR%\" >nul
    copy /Y "%~dp0sdk\DPFPVerNET.dll" "%INSTALL_DIR%\" >nul
    copy /Y "%~dp0sdk\DPFPGuiNET.dll" "%INSTALL_DIR%\" >nul
    echo       DLLs copiados
) else (
    echo       [AVISO] Carpeta sdk\ con DLLs no encontrada.
    echo       Copie los DLLs del SDK a la carpeta sdk\ y reinstale.
)

:: Copiar fuente
copy /Y "%~dp0src\FingerprintService.cs" "%INSTALL_DIR%\" >nul

echo.
echo [4/6] Compilando servicio...
if not exist "%CSC%" (
    echo       [ERROR] Compilador C# no encontrado en:
    echo       %CSC%
    echo       Instale .NET Framework 4.x
    pause
    exit /b 1
)

"%CSC%" /nologo /target:winexe /platform:x64 /out:"%INSTALL_DIR%\FingerprintService.exe" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:"%INSTALL_DIR%\DPFPDevNET.dll" /reference:"%INSTALL_DIR%\DPFPShrNET.dll" /reference:"%INSTALL_DIR%\DPFPEngNET.dll" /reference:"%INSTALL_DIR%\DPFPVerNET.dll" /reference:"%INSTALL_DIR%\DPFPGuiNET.dll" "%INSTALL_DIR%\FingerprintService.cs"

if %errorlevel% neq 0 (
    echo       [ERROR] Fallo la compilacion
    pause
    exit /b 1
)
echo       Compilado OK: FingerprintService.exe

echo.
echo [5/6] Configurando certificado SSL...

:: Copiar script SSL
copy /Y "%~dp0src\setup_ssl.ps1" "%INSTALL_DIR%\" >nul

:: Ejecutar script SSL
powershell -ExecutionPolicy Bypass -File "%INSTALL_DIR%\setup_ssl.ps1"

echo.
echo [6/6] Registrando servicio Windows...

:: Detener si existe
sc query "FactuPOSFingerprint" >nul 2>&1
if %errorlevel% equ 0 (
    sc stop "FactuPOSFingerprint" >nul 2>&1
    timeout /t 2 /nobreak >nul
    sc delete "FactuPOSFingerprint" >nul 2>&1
    timeout /t 1 /nobreak >nul
)

:: Crear tarea programada (mas simple que servicio Windows para consola)
schtasks /delete /tn "FactuPOS Fingerprint" /f >nul 2>&1
schtasks /create /tn "FactuPOS Fingerprint" /tr "\"%INSTALL_DIR%\FingerprintService.exe\"" /sc onlogon /rl highest /f >nul 2>&1
echo       Tarea programada creada (inicia con Windows)

:: Iniciar ahora
echo.
echo Iniciando servicio...
start "FactuPOS Fingerprint" "%INSTALL_DIR%\FingerprintService.exe"
timeout /t 3 /nobreak >nul

:: Verificar
powershell -Command "try { $r = Invoke-WebRequest -Uri 'https://127.0.0.1:52181/status' -UseBasicParsing -SkipCertificateCheck -TimeoutSec 5; Write-Host '      Servicio activo:' $r.Content } catch { Write-Host '      [AVISO] No responde aun. Acepte el certificado en Chrome.' }" 2>nul

echo.
echo ==========================================
echo  Instalacion completada
echo ==========================================
echo.
echo Instalado en: %INSTALL_DIR%
echo.
echo Siguiente paso:
echo   1. Abra Chrome: https://127.0.0.1:52181/status
echo   2. Acepte el certificado
echo   3. Debe ver: {"ok":true,"connected":true}
echo   4. Ya puede usar "Marcar con huella" en FactuPOS
echo.
pause
