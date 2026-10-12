@echo off
REM ============================================================
REM  FactuPOS - Kiosko de Huella Digital (Python/Tkinter)
REM ============================================================
REM  Lanza kiosk.py (interfaz de marcaje). Requiere que
REM  fingerprint_service.py ya este corriendo (iniciar_servicio.bat).
REM  TODA la salida va a logs\error_kiosko.log .
REM ============================================================
setlocal
cd /d "%~dp0"
if not exist "logs" mkdir "logs"
set "ERRLOG=%~dp0logs\error_kiosko.log"

REM --- Buscar python (preferimos pythonw para que no quede ventana negra) ---
set "PY="
for %%P in (pythonw.exe) do if not defined PY (where %%P >nul 2>&1 && set "PY=%%P")
if not defined PY for %%P in (python.exe) do if not defined PY (where %%P >nul 2>&1 && set "PY=%%P")
if not defined PY if exist "C:\Python38\pythonw.exe" set "PY=C:\Python38\pythonw.exe"
if not defined PY if exist "C:\Python38-32\pythonw.exe" set "PY=C:\Python38-32\pythonw.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python38\pythonw.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python38\pythonw.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python38-32\pythonw.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python38-32\pythonw.exe"
if not defined PY (
    >"%ERRLOG%" echo [ERROR] No se encontro python/pythonw. Instala python-3.8.10.exe con "Add Python to PATH".
    type "%ERRLOG%"
    echo.
    echo *** Falta Python. Detalle en logs\error_kiosko.log . Pulsa una tecla. ***
    pause >nul
    exit /b 1
)

echo Lanzando kiosko con: %PY%
echo (errores en logs\error_kiosko.log y logs\kiosk-AAAA-MM-DD.log)
"%PY%" "%~dp0kiosk.py" > "%ERRLOG%" 2>&1

echo.
echo =================== logs\error_kiosko.log ===================
type "%ERRLOG%"
echo.
echo *** El kiosko se cerro. Pulsa una tecla. ***
pause >nul
endlocal
