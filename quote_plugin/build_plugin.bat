@echo off
setlocal
set "ROOT=%~dp0"
set "VCVARS=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
if not exist "%VCVARS%" (
  echo Visual Studio 2022 C++ tools were not found.
  exit /b 1
)
call "%VCVARS%" >nul
if errorlevel 1 exit /b 1
if not exist "%ROOT%dist" mkdir "%ROOT%dist"
cl /nologo /std:c++20 /O2 /EHsc /LD /I"%ROOT%..\third_party\minhook\include" ^
  "%ROOT%PeaceWalkerCustomQuotes.cpp" ^
  "%ROOT%..\third_party\minhook\src\buffer.c" ^
  "%ROOT%..\third_party\minhook\src\hook.c" ^
  "%ROOT%..\third_party\minhook\src\trampoline.c" ^
  "%ROOT%..\third_party\minhook\src\hde\hde64.c" ^
  /link /OUT:"%ROOT%dist\PeaceWalkerCustomQuotes.asi" /DLL
exit /b %errorlevel%
