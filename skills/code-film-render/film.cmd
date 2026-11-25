@echo off
setlocal
chcp 65001 >nul
if not exist "%LOCALAPPDATA%\CodeFilm\python312.path" (echo Run START-HERE.cmd first. & exit /b 2)
set /p "film_py="<"%LOCALAPPDATA%\CodeFilm\python312.path"
"%film_py%" -X utf8 "%~dp0film.py" %*
exit /b %errorlevel%
