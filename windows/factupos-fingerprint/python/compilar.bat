@echo off
REM ============================================================
REM  Compilar a .EXE con PyInstaller (OPCIONAL)
REM ============================================================
REM  Genera en dist\ :
REM    FactuposFpServicio.exe   (el servicio del lector, con consola para ver el log)
REM    FactuposKiosko.exe       (la interfaz de marcaje, sin consola)
REM  y copia al lado los archivos que el .exe necesita (certs\, config.json, token.conf, prints\, logs\).
REM
REM  Ejecutar en el PC Windows (PyInstaller NO cross-compila).
REM  Requiere internet (baja pyinstaller con pip).
REM
REM  Nota: aunque uses los .exe, el RUNTIME del DigitalPersona SDK
REM        (DPFPApi.dll / dpHFtrEx.dll / dpHMatch.dll + DpHostW) igual debe estar instalado.
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM ============================================================
REM  >>>  VERSION del paquete  <<<   (bumpear en cada release)
REM ============================================================
set "APP_VERSION=1.1.0"
set "ZIPNAME=factupos-fingerprint-windows_v%APP_VERSION%.zip"

REM --- Buscar python (igual que iniciar_servicio.bat: PATH primero, luego rutas tipicas) ---
set "PY="
for %%P in (python.exe) do if not defined PY (where %%P >nul 2>&1 && set "PY=%%P")
if not defined PY if exist "C:\Python38\python.exe" set "PY=C:\Python38\python.exe"
if not defined PY if exist "C:\Python38-32\python.exe" set "PY=C:\Python38-32\python.exe"
if not defined PY if exist "C:\Python39\python.exe" set "PY=C:\Python39\python.exe"
if not defined PY if exist "C:\Python310\python.exe" set "PY=C:\Python310\python.exe"
if not defined PY if exist "C:\Python311\python.exe" set "PY=C:\Python311\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python38\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python38\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python38-32\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python38-32\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python39\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python39\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if not defined PY (
    echo.
    echo [ERROR] No se encontro python.exe. Instala python-3.8.10.exe ^(esta en la carpeta Compartido^)
    echo         marcando "Add Python to PATH", o edita este .bat y pone la ruta completa en PY.
    pause
    exit /b 1
)
echo Usando Python: %PY%
echo.

"%PY%" -m pip install --upgrade pyinstaller || (echo Fallo instalando pyinstaller ^(revisa internet^) & pause & exit /b 1)

if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo.
echo === Compilando FactuposFpServicio.exe (servicio, con consola para ver el log) ===
"%PY%" -m PyInstaller --noconfirm --onefile --console --name FactuposFpServicio fingerprint_service.py
if not exist "dist\FactuposFpServicio.exe" (echo Fallo la compilacion del servicio & pause & exit /b 1)

echo.
echo === Compilando FactuposKiosko.exe (interfaz, sin consola) ===
"%PY%" -m PyInstaller --noconfirm --onefile --windowed --name FactuposKiosko kiosk.py
if not exist "dist\FactuposKiosko.exe" (echo Fallo la compilacion del kiosko & pause & exit /b 1)

REM --- Copiar al lado de los .exe lo que necesitan en runtime ---
if not exist "dist\certs"  mkdir "dist\certs"
copy /Y "certs\cert.pem"      "dist\certs\" >nul
copy /Y "certs\key.pem"       "dist\certs\" >nul
copy /Y "config.json"         "dist\" >nul
copy /Y "token.conf"          "dist\" >nul 2>nul
copy /Y "iniciar_oculto.vbs"  "dist\" >nul 2>nul
REM Generar version.txt con la version actual
> "dist\version.txt" echo FactuPOS Biometria - Kiosko + Servicio de Huella Digital (Windows)
>>"dist\version.txt" echo version: %APP_VERSION%
>>"dist\version.txt" echo build:   2026-10-11
if not exist "dist\prints" mkdir "dist\prints"
if not exist "dist\logs"   mkdir "dist\logs"

REM --- Pequeño launcher dentro de dist\ que hace la limpieza y abre ambos ---
> "dist\iniciar.bat" echo @echo off
>>"dist\iniciar.bat" echo cd /d "%%~dp0"
>>"dist\iniciar.bat" echo net session ^>nul 2^>^&1 ^|^| ^(echo CONVIENE EJECUTAR COMO ADMINISTRADOR ^& timeout /t 3 ^>nul^)
>>"dist\iniciar.bat" echo schtasks /change /tn "FactuPOS Fingerprint" /disable ^>nul 2^>^&1
>>"dist\iniciar.bat" echo for %%%%X in ^(FingerprintService.exe DPAgent.exe DpAgnt.exe DPApp.exe OneTouch.exe FpAgent.exe DPClientSrv.exe FactuposFpServicio.exe FactuposKiosko.exe^) do taskkill /F /T /IM %%%%X ^>nul 2^>^&1
>>"dist\iniciar.bat" echo net stop WbioSrvc ^>nul 2^>^&1
>>"dist\iniciar.bat" echo net start DpHostW ^>nul 2^>^&1
>>"dist\iniciar.bat" echo REM El servicio lanza el kiosko solo (NO lo abrimos aca, sale duplicado).
>>"dist\iniciar.bat" echo start "" /min "%%~dp0FactuposFpServicio.exe"
>>"dist\iniciar.bat" echo exit

REM --- Empaquetar TODO el contenido de dist\ en un .zip versionado listo para subir ---
REM    (la version sale de APP_VERSION definida arriba del .bat)
if exist "%ZIPNAME%" del /q "%ZIPNAME%"
powershell -NoProfile -Command "Compress-Archive -Path 'dist\*' -DestinationPath '%ZIPNAME%' -Force" >nul 2>&1
if exist "%ZIPNAME%" (
    REM Mantener tambien un alias sin version (el "latest") por compatibilidad de links viejos
    copy /Y "%ZIPNAME%" "factupos-fingerprint-windows.zip" >nul
    set "ZIPOK=1"
) else (
    set "ZIPOK=0"
)

echo.
echo ============================================================
if "%ZIPOK%"=="1" (
    echo  LISTO. ZIPs generados:
    echo    %CD%\%ZIPNAME%             ^<- subi este a downloads
    echo    %CD%\factupos-fingerprint-windows.zip  (alias "latest")
    echo  Contenido: FactuposFpServicio.exe + FactuposKiosko.exe + INICIAR.bat
    echo             + iniciar_oculto.vbs + config.json + token.conf + certs\ + prints\ + logs\
    echo.
    echo  -^> Subilo a downloads, o dejalo en  Y:\Compartido\  para que lo suba Claude.
) else (
    echo  Los .exe quedaron en  %CD%\dist\  pero no se pudo crear el .zip automaticamente.
    echo  Comprimi a mano el CONTENIDO de la carpeta dist\ en un .zip.
)
echo.
echo  Para probar: descomprimi el .zip, y clic derecho en  iniciar.bat
echo               -^> "Ejecutar como administrador"  (la primera vez).
echo  Requisito en el PC: el runtime del DigitalPersona One Touch SDK instalado.
echo ============================================================
pause
endlocal
