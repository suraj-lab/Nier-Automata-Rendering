@echo off
::This will remove NieRAutomataCompat, leaving only the Windows 10 executable.
DEL /Q /F NieRAutomataCompat.exe
DEL /Q /F installation_os_check.vdf
DEL /Q /F win8_7_setup.bat
DEL /Q /F win10setup.bat
EXIT 1