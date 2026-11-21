@echo off
rem Converts every PDF in input\ into a JSON file in output\ (same tree, same names).
set "PYTHONPATH=%~dp0;%PYTHONPATH%"
python -m json4win %*
