@echo off
setlocal
cd /d "%~dp0"
where mvn >nul 2>&1
if errorlevel 1 (
    echo Maven was not found on PATH. Install Maven or add it to PATH.
    pause
    exit /b 1
)
echo Local test dashboard: http://127.0.0.1:8080/
call mvn spring-boot:run "-Dspring-boot.run.profiles=local-test"
set "result=%errorlevel%"
if not "%result%"=="0" pause
exit /b %result%
