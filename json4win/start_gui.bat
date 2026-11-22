@echo off
rem Starts the local json4win web GUI on 127.0.0.1 and opens it in a browser.
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
python -m json4win --gui %*
