@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0航旅智策应用\Prepare-Demo.ps1"
if errorlevel 1 pause
