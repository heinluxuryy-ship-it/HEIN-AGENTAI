@echo off
title HEIN Luxury Agent - Executable Environment

echo ========================================================
echo   Starting Node WA Bridge (Port 5001)...
echo ========================================================
start cmd /k "node wa_bridge.js"

echo ========================================================
echo   Starting Python Flask Agent (Port 5000)...
echo ========================================================
start cmd /k "py app.py"

echo   System is starting. 
echo   Check the two console windows for logs.
echo   Opening dashboard in your browser...
timeout /t 5
start http://127.0.0.1:5000
