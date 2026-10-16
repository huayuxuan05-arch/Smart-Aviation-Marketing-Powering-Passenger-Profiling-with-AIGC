@echo off
chcp 65001 >nul
echo.
echo  航旅智策 - 选择本地模型
echo  [1] Qwen3-4B，CPU，适合先运行项目（默认）
echo  [2] Qwen3-4B，Vulkan，适合支持 Vulkan 的显卡
echo  [3] Qwen3.5-9B，NVIDIA CUDA，需兼容显卡与显存
echo  [4] 仅准备网站及训练数据，不启用大模型
choice /C 1234 /N /M "请选择 1/2/3/4（推荐 1）："
set "taskModelChoice=%errorlevel%"
if "%taskModelChoice%"=="1" powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0航旅智策应用\Prepare-Demo.ps1" -EnableLocalModel -Model 4b -Backend CPU
if "%taskModelChoice%"=="2" powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0航旅智策应用\Prepare-Demo.ps1" -EnableLocalModel -Model 4b -Backend Vulkan
if "%taskModelChoice%"=="3" powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0航旅智策应用\Prepare-Demo.ps1" -EnableLocalModel -Model 9b -Backend CUDA
if "%taskModelChoice%"=="4" powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0航旅智策应用\Prepare-Demo.ps1" -DataOnly
if errorlevel 1 pause
