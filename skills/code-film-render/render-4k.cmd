@echo off
setlocal
if "%~1"=="" (
  echo Drop a plan.json on this file, or pass plan.json and an optional output.mp4.
  exit /b 2
)
set "film_plan=%~f1"
set "film_output=%~dpn1-4K.mp4"
if not "%~2"=="" set "film_output=%~f2"
set "PYTHONUTF8=1"
call "%~dp0film.cmd" cut --background --plan "%film_plan%" --out "%film_output%" --preset uhd --fps 24
if errorlevel 1 exit /b 1
call "%~dp0film.cmd" cut --wait --out "%film_output%"
exit /b %errorlevel%


