@echo off
setlocal EnableExtensions
title myharness (XiaoYi) setup
echo ============================================================
echo   myharness / XiaoYi  -  one-click setup for Windows
echo ============================================================
echo.

set "REPO=%USERPROFILE%\myharness"
set "CFGDIR=%USERPROFILE%\.xiaoyi"
set "CONSTRAINTS=%CFGDIR%\tool-constraints.txt"

REM ---------- 1/6 uv ----------
where uv >nul 2>nul
if not errorlevel 1 goto :uv_ok
echo [1/6] uv was not found. uv is required (https://docs.astral.sh/uv/).
set /p ANS=Install uv now using the official script? [y/N] 
if /i not "%ANS%"=="y" goto :no_uv
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul
if errorlevel 1 goto :no_uv
:uv_ok
echo [1/6] uv: OK

REM ---------- 2/6 repo ----------
if exist "%REPO%\pyproject.toml" goto :repo_ok
where git >nul 2>nul
if errorlevel 1 goto :no_git
echo [2/6] cloning repository to %REPO% ...
git clone https://github.com/ohhhhh-hyf/myharness.git "%REPO%"
if errorlevel 1 goto :fail_clone
:repo_ok
cd /d "%REPO%"
echo [2/6] repository: %REPO%

REM ---------- 3/6 sync ----------
echo [3/6] uv sync ...
uv sync
if errorlevel 1 goto :fail_sync

REM ---------- 4/6 pin dependency versions from uv.lock ----------
if not exist "%CFGDIR%" mkdir "%CFGDIR%"
echo [4/6] exporting locked versions ...
uv export --format requirements-txt --no-dev --no-emit-project --no-hashes -o "%CONSTRAINTS%"
if errorlevel 1 goto :fail_export

REM ---------- 5/6 install the global command ----------
echo [5/6] installing the global "xiaoyi" command ...
uv tool install --editable . -c "%CONSTRAINTS%"
if errorlevel 1 goto :fail_install
uv tool update-shell >nul 2>nul

REM ---------- 6/6 user-level config template ----------
if exist "%CFGDIR%\config.yaml" goto :cfg_ok
echo [6/6] writing config template ...
>  "%CFGDIR%\config.yaml" echo providers:
>> "%CFGDIR%\config.yaml" echo   - name: deepseek
>> "%CFGDIR%\config.yaml" echo     protocol: openai-compat
>> "%CFGDIR%\config.yaml" echo     base_url: https://api.deepseek.com
>> "%CFGDIR%\config.yaml" echo     model: deepseek-v4-flash
>> "%CFGDIR%\config.yaml" echo     api_key: ""
>> "%CFGDIR%\config.yaml" echo permission_mode: default
:cfg_ok
echo [6/6] config: %CFGDIR%\config.yaml

echo.
echo Done.
echo   1) Open a NEW terminal window.
echo   2) Set your API key:  setx OPENAI_API_KEY "sk-..."
echo   3) Run:  xiaoyi
echo.
echo If "xiaoyi" is not found, run:  uv tool update-shell   (then reopen the terminal)
pause
exit /b 0

:no_uv
echo.
echo [x] uv is required. Install it, then run this script again:
echo     powershell -c "irm https://astral.sh/uv/install.ps1 ^| iex"
pause
exit /b 1
:no_git
echo.
echo [x] Git was not found, and %REPO% does not exist.
echo     Install Git (https://git-scm.com/download/win), or clone the repo manually to:
echo     %REPO%
pause
exit /b 1
:fail_clone
echo.
echo [x] git clone failed. Check your network or clone manually to %REPO%.
pause
exit /b 1
:fail_sync
echo.
echo [x] uv sync failed. See the messages above.
pause
exit /b 1
:fail_export
echo.
echo [x] uv export failed (uv.lock may be missing).
pause
exit /b 1
:fail_install
echo.
echo [x] uv tool install failed. Make sure no xiaoyi session is running, then retry.
pause
exit /b 1
