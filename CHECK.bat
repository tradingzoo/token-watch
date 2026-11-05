@echo off
rem Records today's market caps and writes checks\<date>.md
rem Double-click to run. Pass any word (e.g. CHECK.bat auto) to skip the pause at the end.
cd /d "%~dp0"
"C:\Users\zacha\AppData\Local\Programs\Python\Python313\python.exe" -X utf8 scan.py > last_run.txt 2>&1
if errorlevel 1 (
  echo CHECK FAILED - Claude will read last_run.txt
) else (
  echo Done. Newest result is in the checks folder.
)
if "%1"=="" pause
