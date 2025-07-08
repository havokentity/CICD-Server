@echo off
setlocal

REM Default port is 5000 if not specified
set PORT=9001

REM Default debug mode is False
set DEBUG=False

REM Check if port is provided as an argument
if not "%~1"=="" (
    set PORT=%~1
)

REM Check if debug mode is provided as an argument
if not "%~2"=="" (
    set DEBUG=%~2
)

echo Starting CICD Server on port %PORT% with debug mode %DEBUG%...
python app.py --port %PORT% --debug %DEBUG%

endlocal