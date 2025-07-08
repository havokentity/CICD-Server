@echo off
echo Testing CICD Server with different configurations...

REM Test with custom port (8080) and default debug mode (False)
echo Running on port 8080 with default debug mode:
call run_server.bat 8080

REM Test with default port (5000) and debug mode enabled (True)
echo.
echo Running on default port with debug mode enabled:
call run_server.bat 5000 True

REM Test with custom port (8080) and debug mode enabled (True)
echo.
echo Running on port 8080 with debug mode enabled:
call run_server.bat 8080 True