@echo off
REM ============================================================
REM  FactuPOS - Servicio de Huella Digital (Python) - arranque
REM ============================================================
REM  Levanta fingerprint_service.py en https://127.0.0.1:52181
REM  TODA la salida (incluyendo errores/tracebacks) se guarda en
REM  logs\error.log  -- abrí ese archivo si algo falla.
REM  Para detenerlo: cerrar esta ventana (o Ctrl+C).
REM ============================================================
REM --- ¿Somos administrador? (hace falta para cerrar el servicio C# viejo y el Servicio biometrico) ---
set "ESADMIN=1"
net session >nul 2>&1 || set "ESADMIN=0"
if "%ESADMIN%"=="0" (
    echo.
    echo  ====================================================================
    echo   AVISO: este .bat NO se esta ejecutando como administrador.
    echo   Para que pueda cerrar el servicio C# viejo (FingerprintService.exe)
    echo   y el "Servicio biometrico de Windows" -- que acaparan el lector --
    echo   cerralo y volve a abrirlo con: clic derecho -^> "Ejecutar como administrador".
    echo   Continuo igual, pero quiza no detecte el dedo hasta que lo corras como admin.
    echo  ====================================================================
    echo.
    timeout /t 4 >nul
)

setlocal EnableDelayedExpansion
cd /d "%~dp0"
if not exist "logs" mkdir "logs"
set "ERRLOG=%~dp0logs\error.log"

REM --- Cerrar TODO lo que pueda acaparar el lector DigitalPersona ---
REM (NO tocar DpHostW.exe — ese es el servicio del SDK que necesitamos corriendo)
echo Liberando el lector (cerrando servicio C# viejo, agentes DigitalPersona, Servicio biometrico de Windows)...
REM 1) deshabilitar y terminar la tarea programada del servicio C# viejo
schtasks /change /tn "FactuPOS Fingerprint" /disable >nul 2>&1
schtasks /end    /tn "FactuPOS Fingerprint"          >nul 2>&1
REM 2) matar procesos que acaparan el lector
for %%X in (FingerprintService.exe DPAgent.exe DpAgnt.exe DPApp.exe OneTouch.exe FpAgent.exe DPClientSrv.exe dpcardengine.exe) do (
    taskkill /F /T /IM %%X >nul 2>&1
)
REM 3) detener el Servicio biometrico de Windows (Windows Hello acapara el lector via WBF)
net stop WbioSrvc >nul 2>&1
REM 4) asegurar que el servicio del SDK DigitalPersona este corriendo
net start DpHostW >nul 2>&1
echo.

REM --- Buscar python ---
set "PY="
for %%P in (python.exe) do if not defined PY (where %%P >nul 2>&1 && set "PY=%%P")
if not defined PY if exist "C:\Python38\python.exe" set "PY=C:\Python38\python.exe"
if not defined PY if exist "C:\Python38-32\python.exe" set "PY=C:\Python38-32\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python38\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python38\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python38-32\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python38-32\python.exe"
if not defined PY (
    >"%ERRLOG%" echo [ERROR] No se encontro python.exe en el PATH ni en las rutas tipicas.
    >>"%ERRLOG%" echo Instala python-3.8.10.exe ^(esta en la carpeta Compartido^) marcando "Add Python to PATH",
    >>"%ERRLOG%" echo o edita este .bat y pone la ruta completa en la variable PY.
    type "%ERRLOG%"
    echo.
    echo *** Falta Python. Detalle en logs\error.log . Pulsa una tecla. ***
    pause >nul
    exit /b 1
)

echo ============================================================
echo  FactuPOS Fingerprint Service ^(Python^)
echo  Interprete: %PY%
echo  Log de errores: logs\error.log
echo  Log del servicio: logs\fingerprint-AAAA-MM-DD.log
echo ============================================================
echo (la salida del servicio se redirige a logs\error.log; abri ese archivo
echo  con el Bloc de notas para ver lo que pasa, o esperá a que se detenga)
echo.

REM --- Lanzar tambien el KIOSKO (ventana aparte, minimizada). El kiosko espera solo
REM     a que el servicio este listo, asi que da igual que arranque un toque antes. ---
echo Lanzando el kiosko...
start "FactuPOS Kiosko" /min "%~dp0iniciar_kiosko.bat"
echo.

REM Redirigimos stdout+stderr a logs\error.log para capturar TODO (incluido un crash de import)
"%PY%" "%~dp0fingerprint_service.py" > "%ERRLOG%" 2>&1

echo.
echo =================== logs\error.log ===================
type "%ERRLOG%"
echo ======================================================
echo.
echo *** El servicio se detuvo. Detalle completo en logs\error.log . Pulsa una tecla. ***
pause >nul
endlocal
