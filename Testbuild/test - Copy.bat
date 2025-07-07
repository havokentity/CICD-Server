@echo off
for /l %%i in (1,1,10) do (
    echo %%i
    timeout /t 1 >nul
)
echo "Succcess!"
exit /b 0