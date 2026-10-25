@ECHO off
GOTO start
:find_dp0
SET dp0=%~dp0
EXIT /b
:start
SETLOCAL
CALL :find_dp0
node "%dp0%\..\vue\node_modules\@lucasygu\redbook\dist\cli.js"   %*
