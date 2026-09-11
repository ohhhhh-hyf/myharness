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

REM ---------- 2/6 pinned version list ----------
if not exist "%CFGDIR%" mkdir "%CFGDIR%"
echo [2/6] downloading the pinned version list ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -UseBasicParsing -Uri '%RAW%/docs/tool-constraints.txt' -OutFile '%CONSTRAINTS%' } catch { exit 1 }"
if errorlevel 1 goto :fail_fetch

REM ---------- 3/6 install from git ----------
echo [3/6] installing the global "xiaoyi" command (fetched from git, versions pinned) ...
REM --refresh forces a re-fetch, which needs git. Without git, uv still fetches
REM the repository itself, so only pass the flag when git is available.
set "REFRESH="
where git >nul 2>nul
if not errorlevel 1 set "REFRESH=--refresh"
uv tool install %REFRESH% "git+%GIT_URL%" -c "%CONSTRAINTS%"
if errorlevel 1 goto :fail_install
uv tool update-shell >nul 2>nul

REM ---------- 4/6 config template ----------
if exist "%CFGDIR%\config.yaml" goto :cfg_ok
echo [4/6] writing config template ...
>  "%CFGDIR%\config.yaml" echo providers:
>> "%CFGDIR%\config.yaml" echo   - name: deepseek
>> "%CFGDIR%\config.yaml" echo     protocol: openai-compat
>> "%CFGDIR%\config.yaml" echo     base_url: https://api.deepseek.com
>> "%CFGDIR%\config.yaml" echo     model: deepseek-v4-flash
>> "%CFGDIR%\config.yaml" echo     api_key: ""
>> "%CFGDIR%\config.yaml" echo permission_mode: default
:cfg_ok
echo [4/6] config: %CFGDIR%\config.yaml
goto :key_step

REM ---------- 5/6 api key ----------
:key_step
echo.
echo [5/6] API key
set "KEY="
set /p KEY=      Paste your API key, then press Enter. Leave empty to skip: 
if "%KEY%"=="" goto :key_skip
setx OPENAI_API_KEY "%KEY%" >nul 2>nul
if errorlevel 1 goto :key_fail
echo       Saved as the user environment variable OPENAI_API_KEY. The config
echo       template keeps api_key empty, so this variable is what the assistant
echo       reads (openai / openai-compat providers, e.g. DeepSeek).
echo       It takes effect in NEW terminal windows.
goto :key_done
:key_skip
echo       Skipped. Set it later with:  setx OPENAI_API_KEY "sk-..."
goto :key_done
:key_fail
echo       WARNING: could not save the key automatically. Set it manually:
echo           setx OPENAI_API_KEY "sk-..."
:key_done

REM ---------- 6/6 ----------
echo.
echo [6/6] done.
echo.
echo   Next steps:
echo     1) Open a NEW terminal window (so the new API key is picked up).
echo     2) Run:  xiaoyi
echo.
echo No source checkout is created on this machine: the code is installed
echo into a tool environment and uv's cache, not as a project folder.
echo To update later, run this script again. With git installed it also
echo re-fetches the latest code; without git it reuses uv's cached copy.
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
