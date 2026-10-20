@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  python "%~dp0uu_gpu_patch.py" --launch %*
) else (
  py -3 "%~dp0uu_gpu_patch.py" --launch %*
)
if errorlevel 1 pause
