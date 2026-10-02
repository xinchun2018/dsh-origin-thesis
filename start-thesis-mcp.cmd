@echo off
rem ============================================================================
rem  dsh-origin-thesis launcher
rem ----------------------------------------------------------------------------
rem  Why a .cmd launcher instead of pointing DSH straight at python.exe?
rem
rem  DSH evaluates `!!js` expressions in a sandbox where `__dirname`,
rem  `__filename` and `require` are NOT available (measured: `typeof __dirname`
rem  raises "ReferenceError: __dirname is not defined"). Only `process` is
rem  reliably present. That makes it impossible for the patch file to compute its
rem  own package directory in JavaScript.
rem
rem  `%~dp0` is a standard Windows batch expansion for "directory of this
rem  script", so this launcher locates itself with no JS involved. The patch only
rem  has to name this file, and the package can live anywhere.
rem
rem  Interpreter resolution order:
rem    1. DSH_THESIS_PYTHON                       (explicit override)
rem    2. conda env `origin` in the usual places  (auto-detect)
rem    3. `python` on PATH                        (last resort)
rem
rem  The interpreter must be able to `import originpro`
rem  (originpro ships wheels up to python 3.9 only).
rem ============================================================================

setlocal

set "HERE=%~dp0"
set "SERVER=%HERE%thesis_mcp_server.py"

if not exist "%SERVER%" (
  echo [dsh-origin-thesis] ERROR: thesis_mcp_server.py not found next to launcher 1>&2
  echo [dsh-origin-thesis] looked in: %HERE% 1>&2
  exit /b 1
)

set "PY=%DSH_THESIS_PYTHON%"
if not defined PY if exist "%USERPROFILE%\miniconda3\envs\origin\python.exe" set "PY=%USERPROFILE%\miniconda3\envs\origin\python.exe"
if not defined PY if exist "%USERPROFILE%\anaconda3\envs\origin\python.exe" set "PY=%USERPROFILE%\anaconda3\envs\origin\python.exe"
if not defined PY if exist "C:\ProgramData\miniconda3\envs\origin\python.exe" set "PY=C:\ProgramData\miniconda3\envs\origin\python.exe"
if not defined PY if exist "C:\ProgramData\anaconda3\envs\origin\python.exe" set "PY=C:\ProgramData\anaconda3\envs\origin\python.exe"
if not defined PY set "PY=python"

if /i "%DSH_THESIS_LAUNCHER_DEBUG%"=="1" (
  echo [dsh-origin-thesis] python=%PY% 1>&2
  echo [dsh-origin-thesis] server=%SERVER% 1>&2
  echo [dsh-origin-thesis] cwd=%CD% 1>&2
)

rem -u and -X utf8: unbuffered stdout and UTF-8 source/IO encoding, both required
rem for the newline-delimited JSON-RPC stdio loop to work with non-ASCII payloads.
rem %* forwards any extra arguments (e.g. --info, --list-tools) to the server.
"%PY%" -u -X utf8 "%SERVER%" %*
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
  echo [dsh-origin-thesis] server exited with code %RC% 1>&2
  echo [dsh-origin-thesis] if it failed to import originpro, set DSH_THESIS_PYTHON 1>&2
  echo [dsh-origin-thesis] to an interpreter that can: pip install originpro numpy Pillow 1>&2
)

endlocal & exit /b %RC%
