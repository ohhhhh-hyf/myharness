@echo off
setlocal EnableExtensions
title myharness (XiaoYi) setup
echo ============================================================
echo   myharness / XiaoYi  -  one-click setup for Windows
echo ============================================================
echo.

set "GIT_URL=https://github.com/ohhhhh-hyf/myharness.git"
set "RAW=https://raw.githubusercontent.com/ohhhhh-hyf/myharness/main"
set "CFGDIR=%USERPROFILE%\.xiaoyi"
set "CONSTRAINTS=%CFGDIR%\tool-constraints.txt"

REM ---------- 1/5 uv ----------
where uv >nul 2>nul
if not errorlevel 1 goto :uv_ok
echo [1/5] uv was not found. uv is required (https://docs.astral.sh/uv/).
set /p ANS=Install uv now using the official script? [y/N] 
if /i not "%ANS%"=="y" goto :no_uv
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul
if errorlevel 1 goto :no_uv
:uv_ok
echo [1/5] uv: OK

REM ---------- 2/5 pinned version list ----------
if not exist "%CFGDIR%" mkdir "%CFGDIR%"
echo [2/5] downloading the pinned version list ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -UseBasicParsing -Uri '%RAW%/docs/tool-constraints.txt' -OutFile '%CONSTRAINTS%' } catch { exit 1 }"
if errorlevel 1 goto :fail_fetch

REM ---------- 3/5 install from git ----------
echo [3/5] installing the global "xiaoyi" command (fetched from git, versions pinned) ...
uv tool install --refresh "git+%GIT_URL%" -c "%CONSTRAINTS%"
if errorlevel 1 goto :fail_install
uv tool update-shell >nul 2>nul

REM ---------- 4/5 config template ----------
if exist "%CFGDIR%\config.yaml" goto :cfg_ok
echo [4/5] writing config template ...
>  "%CFGDIR%\config.yaml" echo providers:
>> "%CFGDIR%\config.yaml" echo   - name: deepseek
>> "%CFGDIR%\config.yaml" echo     protocol: openai-compat
>> "%CFGDIR%\config.yaml" echo     base_url: https://api.deepseek.com
>> "%CFGDIR%\config.yaml" echo     model: deepseek-v4-flash
>> "%CFGDIR%\config.yaml" echo     api_key: ""
>> "%CFGDIR%\config.yaml" echo permission_mode: default
:cfg_ok
echo [4/5] config: %CFGDIR%\config.yaml

REM ---------- 5/5 ----------
echo [5/5] done.
echo.
echo   Next steps:
echo     1) Open a NEW terminal window.
echo     2) Set your API key:  setx OPENAI_API_KEY "sk-..."
echo     3) Run:  xiaoyi
echo.
echo No source checkout is created on this machine: the code is installed
echo into a tool environment under %USERPROFILE%\.local and uv's cache.
echo To update later, simply run this script again.
echo If "xiaoyi" is not found, run:  uv tool update-shell   (then reopen the terminal)
pause
exit /b 0

:no_uv
echo.
echo [x] uv is required. Install it, then run this script again:
echo     powershell -c "irm https://astral.sh/uv/install.ps1 ^| iex"
pause
exit /b 1
:fail_fetch
echo.
echo [x] Could not download the pinned version list from GitHub.
echo     Check your network or proxy, then run this script again.
pause
exit /b 1
:fail_install
echo.
echo [x] Installation failed. Common causes:
echo     - no network access to github.com or pypi.org
echo     - a running "xiaoyi" session is holding the tool environment
pause
exit /b 1
