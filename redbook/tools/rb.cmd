@echo off
REM rb.cmd — guarded redbook CLI wrapper
REM Blocks high-risk API subcommands (post/search/feed triggered risk control on 2026-10-22).
REM Usage: rb.cmd whoami / rb.cmd health / rb.cmd auth ... (read-only ops allowed)
setlocal
set CMD=%1

if "%CMD%"=="post" goto blocked
if "%CMD%"=="search" goto blocked
if "%CMD%"=="feed" goto blocked
if "%CMD%"=="like" goto blocked
if "%CMD%"=="comment" goto blocked
if "%CMD%"=="reply" goto blocked
if "%CMD%"=="batch-reply" goto blocked
if "%CMD%"=="collect" goto blocked
if "%CMD%"=="uncollect" goto blocked
if "%CMD%"=="delete" goto blocked

REM allowed: whoami, read, comments, topics, user, user-posts, favorites, health, auth, boards, board, render, analyze-viral, viral-template
node "%~dp0..\node_modules\@lucasygu\redbook\dist\cli.js" %*
exit /b %errorlevel%

:blocked
echo [GUARD] "%CMD%" is blocked: redbook API write/discovery endpoints triggered risk control (type=124/301/-104) on 2026-10-22.
echo [GUARD] Use the CDP browser channel scripts in redbook-tools\ instead (post-note.js / search-notes.js).
echo [GUARD] To override at your own risk: node D:\vue\node_modules\@lucasygu\redbook\dist\cli.js %*
exit /b 1
